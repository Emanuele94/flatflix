"""The download pipeline: add, wait for metadata, filter, verify, start (DOWN-01..03, FILT-02).

Order of one job, with the reason for each step:

1. `torrents/add` with `stopCondition=MetadataReceived`, so the torrent fetches its file list and
   then stops by itself with no payload requested (D-23; a magnet added fully stopped never gets
   its metadata). Tags `fx`, `fx-pending` and `fx-job-<id>` mark it as ours and unfinished.
2. Poll `torrents/files` until it is non-empty (an empty list means no metadata yet), but never
   longer than METADATA_TIMEOUT after the add (D-12).
3. `decide()` splits the files into keep and zero ids; a torrent with no usable video is deleted.
4. File priorities 0 and 1 are set and re-read; any mismatch deletes the torrent.
5. Only then `torrents/start`, and the pending tags are removed.

A torrent carries `fx-pending` from the add until step 5, so a restart can find every torrent
that was never filtered (`reconcile`). The category comes from `qbit_category(settings, type)` for
the job's own type and nowhere else, and the client has no method that re-categorizes a torrent
(SEC-03).
"""

import asyncio
import logging
import re
import secrets
import time
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from app.config import Settings
from app.content_type import ContentType, qbit_category
from app.download.allowlist import TorrentFile, decide
from app.download.jobs import Job, JobRegistry, JobState
from app.netutil import resolve_host
from app.qbit.client import QbitClient, QbitError
from app.search.filters import infohash, is_public_address, is_safe_torrent_url
from app.search.service import SearchService

logger = logging.getLogger(__name__)

TAG_PORTAL = "fx"
TAG_PENDING = "fx-pending"
TAG_JOB_PREFIX = "fx-job-"
POLL_SECONDS = 1
HTTP_NOT_FOUND = 404
HTTP_CONFLICT = 409
JOB_ID = re.compile(r"^[0-9a-f]{16}$")
# A second tap on a result whose job already started returns that job for this long; after it,
# the tap runs again and the btih check answers "already there" (or re-adds a deleted torrent).
STARTED_DEDUPE_SECONDS = 60
# qBittorrent states of a torrent that has never run: waiting for metadata, or stopped (v5 says
# "stopped", v4 "paused"). Any other state means the torrent is, or was, downloading.
NOT_STARTED_STATES = frozenset({"stoppedDL", "pausedDL", "metaDL", "forcedMetaDL"})
# Tries to clear the pending tags after a start (a leftover tag costs a re-filter, never a delete).
TAG_CLEANUP_ATTEMPTS = 3


Resolver = Callable[[str], Awaitable[list[str]]]


def _tags_of(row: dict) -> list[str]:
    return [t.strip() for t in str(row.get("tags") or "").split(",") if t.strip()]


def _job_tag_of(tags: list[str]) -> str | None:
    return next((t for t in tags if t.startswith(TAG_JOB_PREFIX)), None)


def _has_started(row: dict) -> bool:
    """True when a torrent is running, finished, or already holds payload bytes.

    A torrent like this must never be deleted just because its `fx-pending` tag is old (CR-01):
    `added_on` is the time of the add, so a started download looks as old as a stuck one.
    """
    if str(row.get("state") or "") not in NOT_STARTED_STATES:
        return True
    for key in ("downloaded", "completed", "progress"):
        try:
            if float(row.get(key) or 0) > 0:
                return True
        except (TypeError, ValueError):
            return True  # an odd value: do not risk deleting a download
    return False


class ResultExpired(Exception):
    """The result is not in the server-side cache (unknown id, or the search expired)."""


class TypeMismatch(Exception):
    """The requested type differs from the type the result was found under."""


class DownloadPipeline:
    def __init__(
        self,
        qbit: QbitClient,
        settings: Settings,
        search: SearchService,
        registry: JobRegistry,
        *,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        resolver: Resolver = resolve_host,
    ) -> None:
        self._qbit = qbit
        self._settings = settings
        self._search = search
        self._registry = registry
        # Epoch seconds, because qBittorrent reports `added_on` the same way.
        self._clock = clock
        self._sleep = sleep
        self._resolver = resolver

    def submit(self, result_id: str, content_type: ContentType) -> Job:
        """Create a job for a cached result and start it; returns at once.

        There is no `await` between the dedupe check and `spawn`, so two requests for one
        result cannot both pass the check: the second gets the first job.
        """
        cached = self._search.get_result(result_id)
        if cached is None:
            raise ResultExpired(result_id)
        if cached.type != content_type:
            raise TypeMismatch(result_id)
        existing = self._registry.active_for_result(result_id)
        if existing is not None and (
            existing.state is JobState.PREPARING
            or self._clock() - existing.created_at < STARTED_DEDUPE_SECONDS
        ):
            return existing
        job = Job(
            job_id=secrets.token_hex(8),
            result_id=result_id,
            type=content_type,
            state=JobState.PREPARING,
            torrent_hash=None,
            created_at=self._clock(),
        )
        self._registry.spawn(job, self.run(job, cached.file_url, cached.engine))
        return job

    async def run(self, job: Job, url: str, engine: str) -> None:
        """Add the torrent and carry it through the allowlist; settles `job.state`."""
        await self._settle(job, self._add_and_process(job, url, engine))

    async def _settle(self, job: Job, work: Awaitable[None]) -> None:
        try:
            await work
        except (QbitError, ValueError) as exc:
            # Class and HTTP status only. The fx-pending tag stays, so a restart cleans up.
            logger.warning(
                "download job %s failed: %s (HTTP %s)",
                job.job_id,
                type(exc).__name__,
                getattr(exc, "status", None),
            )
            job.state = JobState.FAILED

    async def _add_and_process(self, job: Job, url: str, engine: str) -> None:
        if job.type is None:
            raise ValueError("a job without a type cannot add a torrent")
        if "\n" in url or "\r" in url:
            raise ValueError("a torrent URL must be a single line")
        if not is_safe_torrent_url(url) or not await self._url_is_public(url):
            logger.warning("download job %s: the result URL is not allowed", job.job_id)
            job.state = JobState.FAILED
            return
        digest = infohash(url)
        if digest is not None:
            existing = await self._qbit.torrents_info(hashes=digest)
            if existing:
                await self._resume_or_duplicate(job, existing[0])
                return
        job_tag = TAG_JOB_PREFIX + job.job_id
        is_magnet = url.lower().startswith("magnet:")
        added = await self._qbit.add_torrent(
            url,
            qbit_category(self._settings, job.type),
            [TAG_PORTAL, TAG_PENDING, job_tag],
            downloader=None if is_magnet else engine,
        )
        if added.status_code == HTTP_CONFLICT:
            job.state = JobState.DUPLICATE
            return
        if not 200 <= added.status_code < 300:
            logger.warning("download job %s: add answered HTTP %s", job.job_id, added.status_code)
            job.state = JobState.FAILED
            return
        deadline = self._clock() + self._settings.metadata_timeout
        # A magnet answers with its hash; a plugin page URL answers 202 with none, and the
        # torrent shows up a few seconds later under the job tag (research Pitfall 5).
        torrent_hash = (
            added.added_ids[0] if added.added_ids else await self._find_by_tag(job_tag, deadline)
        )
        if torrent_hash is None:
            # Nothing to delete. If the torrent appears later it keeps fx-pending and is
            # removed by the next reconcile once it is older than METADATA_TIMEOUT.
            job.state = JobState.UNAVAILABLE
            return
        job.torrent_hash = torrent_hash
        await self._process(job, torrent_hash, job_tag, deadline)

    async def _url_is_public(self, url: str) -> bool:
        """A magnet always; an http(s) URL only when every address its host resolves to is public.

        Plugin URLs are untrusted (WR-03): a name that resolves to a loopback, private or
        link-local address would make qBittorrent fetch from inside the household network.
        """
        if url.lower().startswith("magnet:"):
            return True
        host = (urlsplit(url).hostname or "").rstrip(".")
        try:
            addresses = await self._resolver(host)
        except OSError:
            return False  # an unresolvable host cannot be fetched either
        return bool(addresses) and all(is_public_address(a) for a in addresses)

    async def _resume_or_duplicate(self, job: Job, row: dict) -> None:
        """The torrent is already in qBittorrent: ours and unfinished, or somebody else's.

        A torrent still tagged `fx-pending` that no running job owns was left by a job that
        failed after the add (WR-01). It is not "already added": nothing runs. Run it through the
        allowlist again, which is idempotent, so the next tap can finish it.
        """
        tags = _tags_of(row)
        old_tag = _job_tag_of(tags)
        owner = self._registry.task(old_tag.removeprefix(TAG_JOB_PREFIX)) if old_tag else None
        if TAG_PENDING not in tags or (owner is not None and not owner.done()):
            job.state = JobState.DUPLICATE
            return
        torrent_hash = str(row["hash"])
        job.torrent_hash = torrent_hash
        deadline = self._clock() + self._settings.metadata_timeout
        await self._process(job, torrent_hash, old_tag or TAG_JOB_PREFIX, deadline)

    async def _find_by_tag(self, job_tag: str, deadline: float) -> str | None:
        while True:
            rows = await self._qbit.torrents_info(tag=job_tag)
            if rows:
                return str(rows[0]["hash"])
            if self._clock() >= deadline:
                return None
            await self._sleep(POLL_SECONDS)

    async def _process(self, job: Job, torrent_hash: str, job_tag: str, deadline: float) -> None:
        """Metadata -> allowlist -> priorities -> verify -> start. Nothing starts before step 4."""
        files = await self._wait_for_files(torrent_hash, deadline)
        if files is None:
            await self._discard(torrent_hash, job_tag)
            job.state = JobState.UNAVAILABLE
            return
        decision = decide([TorrentFile.from_qbit(row) for row in files])
        if not decision.accept:
            await self._discard(torrent_hash, job_tag)
            job.state = JobState.REJECTED
            return
        await self._qbit.set_file_priority(torrent_hash, decision.zero_ids, 0)
        await self._qbit.set_file_priority(torrent_hash, decision.keep_ids, 1)
        reread = {
            int(row["index"]): int(row["priority"])
            for row in await self._qbit.torrent_files(torrent_hash)
        }
        if any(reread.get(i) != 0 for i in decision.zero_ids) or any(
            reread.get(i, 0) < 1 for i in decision.keep_ids
        ):
            await self._discard(torrent_hash, job_tag)
            job.state = JobState.FAILED
            return
        await self._qbit.start([torrent_hash])
        job.state = JobState.STARTED
        await self._clear_pending_tags(torrent_hash, job_tag)

    async def _clear_pending_tags(self, torrent_hash: str, job_tag: str) -> None:
        """Drop `fx-pending` and the job tag from a started torrent, retrying a few times.

        If every try fails the torrent keeps `fx-pending`. That is safe: `reconcile` sees that it
        has started and runs the allowlist again instead of deleting it (CR-01).
        """
        for attempt in range(1, TAG_CLEANUP_ATTEMPTS + 1):
            try:
                await self._qbit.remove_tags([torrent_hash], [TAG_PENDING, job_tag])
                await self._qbit.delete_tags([job_tag])
                return
            except QbitError as exc:
                logger.warning(
                    "tag cleanup failed after start (try %s): %s", attempt, type(exc).__name__
                )
                if attempt < TAG_CLEANUP_ATTEMPTS:
                    await self._sleep(POLL_SECONDS)

    async def _wait_for_files(self, torrent_hash: str, deadline: float) -> list[dict] | None:
        """The file list, or None when it has not arrived by the deadline."""
        while True:
            try:
                files = await self._qbit.torrent_files(torrent_hash)
            except QbitError as exc:
                # Right after a magnet add the real engine can still answer 404 for a moment.
                if exc.status != HTTP_NOT_FOUND:
                    raise
                files = []
            if files:
                return files
            if self._clock() >= deadline:
                return None
            await self._sleep(POLL_SECONDS)

    async def _discard(self, torrent_hash: str, job_tag: str) -> None:
        """Delete a torrent with its files; the job tag is cleaned up on a best-effort basis."""
        await self._qbit.delete([torrent_hash], True)
        try:
            await self._qbit.delete_tags([job_tag])
        except QbitError as exc:
            logger.warning("tag cleanup failed after delete: %s", type(exc).__name__)

    async def reconcile(self) -> None:
        """Finish what a restart interrupted (D-12, FILT-02).

        Every portal torrent carries `fx-pending` until it was filtered. One older than
        METADATA_TIMEOUT that never started is deleted with its files. The others go through
        the same allowlist and are started only after it; that includes a torrent that already
        runs but kept its tag after a failed cleanup, which must never be deleted (CR-01). The
        category qBittorrent holds is never changed.
        """
        now = self._clock()
        timeout = self._settings.metadata_timeout
        types = {
            self._settings.category_film: "film",
            self._settings.category_tv: "serie",
        }
        for row in await self._qbit.torrents_info(tag=TAG_PENDING):
            torrent_hash = str(row["hash"])
            job_tag = _job_tag_of(_tags_of(row))
            known_id = job_tag.removeprefix(TAG_JOB_PREFIX) if job_tag else None
            if known_id is not None and self._registry.get(known_id) is not None:
                continue  # a job of this process owns the torrent
            added_on = float(row.get("added_on") or 0)
            started = _has_started(row)
            if now - added_on > timeout and not started:
                logger.info("reconcile: deleting a pending torrent older than %s s", timeout)
                await self._discard(torrent_hash, job_tag or TAG_JOB_PREFIX)
                continue
            # A started torrent already has its file list; give it the full wait anyway so one
            # failed read never turns into a delete.
            deadline = now + timeout if started else added_on + timeout
            job_id = known_id if known_id and JOB_ID.fullmatch(known_id) else secrets.token_hex(8)
            job = Job(
                job_id=job_id,
                result_id=None,
                type=types.get(str(row.get("category") or "")),  # type: ignore[arg-type]
                state=JobState.PREPARING,
                torrent_hash=torrent_hash,
                created_at=now,
            )
            self._registry.spawn(
                job,
                self._settle(
                    job,
                    self._process(job, torrent_hash, TAG_JOB_PREFIX + job_id, deadline),
                ),
            )
