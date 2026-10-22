"""The download pipeline: add, wait for metadata, filter, verify, start (DOWN-01..03, FILT-02).

Order of one job, with the reason for each step:

1. `torrents/add` with `stopCondition=MetadataReceived`, so the torrent fetches its file list and
   then stops by itself with no payload requested (D-23; a magnet added fully stopped never gets
   its metadata). Tags `fx`, `fx-pending` and `fx-job-<id>` mark it as ours and unfinished.
2. Poll `torrents/files` until it is non-empty (an empty list means no metadata yet).
3. `decide()` splits the files into keep and zero ids; a torrent with no usable video is deleted.
4. File priorities 0 and 1 are set and re-read; any mismatch deletes the torrent.
5. Only then `torrents/start`, and the pending tags are removed.

The category comes from `qbit_category(settings, job.type)` for the job's own type and nowhere
else, and the client has no method that re-categorizes a torrent (SEC-03).
"""

import asyncio
import logging
import secrets
import time
from collections.abc import Awaitable, Callable

from app.config import Settings
from app.content_type import ContentType, qbit_category
from app.download.allowlist import TorrentFile, decide
from app.download.jobs import Job, JobRegistry, JobState
from app.qbit.client import QbitClient, QbitError
from app.search.service import SearchService

logger = logging.getLogger(__name__)

TAG_PORTAL = "fx"
TAG_PENDING = "fx-pending"
TAG_JOB_PREFIX = "fx-job-"
POLL_SECONDS = 1
HTTP_NOT_FOUND = 404


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
    ) -> None:
        self._qbit = qbit
        self._settings = settings
        self._search = search
        self._registry = registry
        # Epoch seconds, because qBittorrent reports `added_on` the same way.
        self._clock = clock
        self._sleep = sleep

    def submit(self, result_id: str, content_type: ContentType) -> Job:
        """Create a job for a cached result and start it; returns at once."""
        cached = self._search.get_result(result_id)
        if cached is None:
            raise ResultExpired(result_id)
        if cached.type != content_type:
            raise TypeMismatch(result_id)
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
        try:
            await self._run(job, url, engine)
        except (QbitError, ValueError) as exc:
            # Class and HTTP status only. The fx-pending tag stays, so a restart cleans up.
            logger.warning(
                "download job %s failed: %s (HTTP %s)",
                job.job_id,
                type(exc).__name__,
                getattr(exc, "status", None),
            )
            job.state = JobState.FAILED

    async def _run(self, job: Job, url: str, engine: str) -> None:
        assert job.type is not None  # only a reconciled job lacks a type, and it never adds
        job_tag = TAG_JOB_PREFIX + job.job_id
        added = await self._qbit.add_torrent(
            url,
            qbit_category(self._settings, job.type),
            [TAG_PORTAL, TAG_PENDING, job_tag],
        )
        if not added.added_ids:
            job.state = JobState.FAILED
            return
        job.torrent_hash = added.added_ids[0]
        await self._filter_and_start(job, job.torrent_hash, job_tag)

    async def _filter_and_start(self, job: Job, torrent_hash: str, job_tag: str) -> None:
        files = await self._wait_for_files(torrent_hash)
        decision = decide([TorrentFile.from_qbit(row) for row in files])
        await self._qbit.set_file_priority(torrent_hash, decision.zero_ids, 0)
        await self._qbit.set_file_priority(torrent_hash, decision.keep_ids, 1)
        reread = {
            int(row["index"]): int(row["priority"])
            for row in await self._qbit.torrent_files(torrent_hash)
        }
        if any(reread.get(i) != 0 for i in decision.zero_ids) or any(
            reread.get(i, 0) < 1 for i in decision.keep_ids
        ):
            await self._qbit.delete([torrent_hash], True)
            job.state = JobState.FAILED
            return
        await self._qbit.start([torrent_hash])
        await self._qbit.remove_tags([torrent_hash], [TAG_PENDING, job_tag])
        await self._qbit.delete_tags([job_tag])
        job.state = JobState.STARTED

    async def _wait_for_files(self, torrent_hash: str) -> list[dict]:
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
            await self._sleep(POLL_SECONDS)
