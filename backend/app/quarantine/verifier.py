"""The verifier: finished downloads are checked in the sandbox, then handed off to media.

One tick finds every completed Film or SerieTV torrent that sits in quarantine and has no
`fx-ok-` tag (D-45, D-49, D-51). Files come only from qBittorrent's file list, never from walking
a folder. The files `files_to_check` chooses are probed one at a time through the runner (D-52) and
judged with the backend's own stat size (D-64, D-65). Only when every checked file passed, each one
is hardlinked into the media folder of its category and then the torrent is tagged `fx-ok-<epoch>`
(D-46, D-54). The tag comes last, so a crash at any point leaves the torrent untagged and the next
tick checks it again (D-63).

Faults of the host are never verdicts (D-58): a runner that cannot answer stops the tick, writes one
audit line per outage and leaves every row Checking, and so does a hardlink that cannot be made
(never a copy, D-48). A video whose probe times out or crashes is probed once more in a fresh VM
before it fails (D-57). When no video passes, every failing video is hardlinked into the rejected
folder, an outcome sidecar is written and only then the torrent is deleted with its files, so a
suspect file is never seeded and a crash at any point leaves the torrent in qBittorrent to be
decided again (RESEARCH Pattern 5). The hand-off runs under the torrent's lock and re-reads the
torrent and the files inside it, so a cancel, a vanished torrent or a changed file links nothing
(Pitfall 10).
"""

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from app import audit
from app.config import Settings
from app.content_type import ContentType, type_for_category
from app.download.allowlist import final_extension
from app.download.listing import READY_STATES, display_name, download_id, tags_of
from app.qbit.bootstrap import Readiness
from app.qbit.client import QbitClient, QbitError
from app.quarantine.guard import HandoffGuard
from app.quarantine.handoff import (
    HandoffError,
    link_into_media,
    link_into_rejected,
    media_target,
    source_path,
)
from app.quarantine.outcomes import Outcome, OutcomeStore
from app.quarantine.rules import (
    FileToCheck,
    files_to_check,
    in_quarantine,
    judge,
    min_minutes_for,
    summary,
    verified_at,
    verified_tag,
)
from app.quarantine.runner_client import (
    ProbeFacts,
    RunnerClient,
    RunnerRefused,
    RunnerUnavailable,
)
from app.quarantine.subtitles import check_subtitle

logger = logging.getLogger(__name__)

# A re-hash of a finished torrent is not a candidate until it settles.
CANDIDATE_STATES = READY_STATES - {"checkingUP"}
# A finished torrent that stopped seeding (qBittorrent 5.x says stoppedUP, 4.x pausedUP).
SEEDING_END_STATES = frozenset({"stoppedUP", "pausedUP"})
# While bootstrap has not marked qBittorrent ready (its categories do not point at quarantine yet),
# the loop does not touch qBittorrent at all; it looks again after this many seconds.
READINESS_WAIT_SECONDS = 1


@dataclass(frozen=True, slots=True)
class _Checked:
    """A file that was checked in this run, with the identity it had at its probe (T-02.1-23)."""

    file: FileToCheck
    identity: tuple[int, int, int]
    passed: bool
    reason: str | None = None
    facts: ProbeFacts | None = None


class _Stop(Exception):
    """Ends the check of one torrent early with the outcome token to report."""

    def __init__(self, outcome: str) -> None:
        super().__init__(outcome)
        self.outcome = outcome


def is_candidate(row: dict, settings: Settings) -> bool:
    """A finished Film or SerieTV torrent saved strictly inside quarantine, not yet verified."""
    return (
        type_for_category(settings, str(row.get("category") or "")) is not None
        and str(row.get("state") or "") in CANDIDATE_STATES
        and in_quarantine(str(row.get("save_path") or ""), settings.quarantine_root)
        and verified_at(tags_of(row)) is None
    )


class Verifier:
    def __init__(
        self,
        qbit: QbitClient,
        runner: RunnerClient,
        settings: Settings,
        *,
        guard: HandoffGuard | None = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        readiness: Readiness | None = None,
        outcomes: OutcomeStore | None = None,
    ) -> None:
        self._qbit = qbit
        self._runner = runner
        self._settings = settings
        self._guard = guard if guard is not None else HandoffGuard()
        self._clock = clock
        self._sleep = sleep
        self._readiness = readiness
        self._outcomes = outcomes if outcomes is not None else OutcomeStore(settings.rejected_root)
        self._runner_down: str | None = None
        self._link_failures: set[tuple[str, str]] = set()

    @property
    def runner_down(self) -> str | None:
        """Why the sandbox could not be used on the last probe, or None while it answers."""
        return self._runner_down

    async def run_forever(self) -> None:
        """Wait for readiness, then tick every VERIFY_POLL_SECONDS until cancelled (D-50)."""
        while self._readiness is not None and self._readiness.state != "ready":
            await self._sleep(READINESS_WAIT_SECONDS)
        while True:
            await self._sleep(self._settings.verify_poll_seconds)
            try:
                await self.run_once()
            except QbitError as exc:
                audit.error("verifier", type(exc).__name__, exc.status)
            except Exception as exc:  # noqa: BLE001 - the loop must never die; only the class is logged
                logger.error("verifier tick failed (%s)", type(exc).__name__)

    async def run_once(self) -> None:
        """Check every candidate, oldest completion first, one at a time (D-52)."""
        rows = await self._qbit.torrents_info()
        listed = {str(row.get("hash") or "").lower() for row in rows}
        for gone in self._guard.known() - listed:
            self._guard.forget(gone)
        self._link_failures = {key for key in self._link_failures if key[0] in listed}
        candidates = [row for row in rows if is_candidate(row, self._settings)]
        candidates.sort(key=lambda row: (row.get("completion_on") or 0, str(row.get("hash"))))
        for row in candidates:
            if await self.check_torrent(row) == "waiting":
                break  # the runner is down: later torrents would only hit the same wall
        await self._purge()
        await self._finish_seeding(rows)

    async def _purge(self) -> None:
        """Remove held files and outcomes older than the retention (D-55)."""
        removed = await asyncio.to_thread(
            self._outcomes.purge, self._clock(), self._settings.rejected_retention_seconds
        )
        if removed > 0:
            audit.quarantine_purged(removed)

    async def _finish_seeding(self, rows: list[dict]) -> None:
        """Delete a verified torrent whose seeding ended, keeping its film (D-47).

        Only a Film or SerieTV torrent saved inside quarantine that carries the verified tag and
        has stopped (stoppedUP or pausedUP) qualifies: a legacy torrent in media, an unchecked one
        and one that is still seeding are never touched. The film is already hardlinked into media
        (the tag is written after the links), so `deleteFiles=true` removes only the quarantine
        name and the media link keeps the file. The household's Ready row is stored first, while
        the torrent is still young enough to be shown (D-28).

        The backend does this, not qBittorrent's share-limit action (RESEARCH Anti-Patterns): with
        `max_ratio_act` set to RemoveWithContent qBittorrent would also delete torrents that were
        never checked, so its action stays "Stop" and the verifier removes what it verified.
        """
        settings = self._settings
        now = self._clock()
        for row in rows:
            content_type = type_for_category(settings, str(row.get("category") or ""))
            verified = verified_at(tags_of(row))
            if (
                content_type is None
                or verified is None
                or str(row.get("state") or "") not in SEEDING_END_STATES
                or not in_quarantine(str(row.get("save_path") or ""), settings.quarantine_root)
            ):
                continue
            torrent_hash = str(row["hash"])
            async with self._guard.lock(torrent_hash):
                if now - verified < settings.completed_visible_seconds:
                    self._outcomes.write(
                        Outcome(
                            self._outcome_id(row),
                            display_name(row),
                            content_type,
                            "ready",
                            0,
                            verified,
                        )
                    )
                await self._qbit.delete([torrent_hash], delete_files=True)
            audit.quarantine_seeding_done(display_name(row))

    def _runner_unavailable(self, why: str) -> None:
        if self._runner_down is None:  # one line per outage, not one per tick
            audit.quarantine_runner_unavailable(why)
        self._runner_down = why

    def _link_failed(self, row: dict, why: str) -> None:
        """One audit line per torrent and reason per process: a stuck link must not flood the log."""
        key = (str(row["hash"]).lower(), why)
        if key not in self._link_failures:
            self._link_failures.add(key)
            audit.quarantine_link_failed(display_name(row), why)

    def _outcome_id(self, row: dict) -> str:
        return download_id(self._settings.secret_key.get_secret_value(), str(row["hash"]))

    async def check_torrent(self, row: dict) -> str:
        """Probe, judge and hand off one torrent.

        Returns "passed" (everything linked, torrent tagged), "partial" (what passed is in media,
        the rest held, torrent deleted), "rejected" (no video passed: held, torrent deleted),
        "waiting" (the runner is down), "aborted" (a cancel, a vanished torrent or a changed file:
        nothing linked) or "held" (a file cannot be read, or a link failed: the torrent stays
        Checking and nothing else happens to it).
        """
        settings = self._settings
        torrent_hash = str(row["hash"])
        content_type = type_for_category(settings, str(row["category"]))
        if content_type is None:
            return "held"
        if self._guard.cancel_requested(torrent_hash):
            return "aborted"
        pending = self._pending_outcome(row)
        if pending is not None:
            return await self._finish_delete(torrent_hash, pending)
        try:
            file_rows = await self._qbit.torrent_files(torrent_hash)
        except QbitError as exc:
            if exc.status == 404:
                return "aborted"  # deleted between the listing and now
            raise
        if not file_rows:
            return "held"  # no file list at all is qBittorrent not being ready, never a verdict
        files = files_to_check(file_rows, content_type)
        videos = [f for f in files if f.kind == "video"]
        try:
            checked = [await self._check_video(row, file, content_type) for file in videos]
            if any(item.passed for item in checked):  # subtitles follow a passing video (D-62)
                checked += [
                    await self._check_subtitle(row, file)
                    for file in files
                    if file.kind == "subtitle"
                ]
        except _Stop as stop:
            return stop.outcome
        return await self._hand_off(row, checked, content_type)

    def _pending_outcome(self, row: dict) -> Outcome | None:
        """The stored outcome of a torrent whose delete failed earlier, else None.

        A torrent that finished after its outcome was stored is a new download of the same hash
        (someone fetched the film again), not a pending delete: it is checked like any other.
        """
        outcome = self._outcomes.get(self._outcome_id(row))
        if outcome is None:
            return None
        try:
            completed = float(row.get("completion_on") or 0)
        except (TypeError, ValueError):
            completed = 0.0
        return outcome if outcome.at >= completed else None

    async def _finish_delete(self, torrent_hash: str, outcome: Outcome) -> str:
        """Retry the delete of a torrent whose links and outcome are already stored."""
        async with self._guard.lock(torrent_hash):
            await self._qbit.delete([torrent_hash], delete_files=True)
        return "rejected" if outcome.kind == "rejected" else "partial"

    def _resolve(self, row: dict, file: FileToCheck) -> tuple[Path, tuple[int, int, int]]:
        try:
            src = source_path(str(row["save_path"]), file.name, self._settings.quarantine_root)
            return src, _identity(src)
        except (HandoffError, OSError):
            raise _Stop("held") from None

    async def _check_video(
        self, row: dict, file: FileToCheck, content_type: ContentType
    ) -> _Checked:
        """Probe one video, once more when the probe crashed or timed out (D-57), and judge it."""
        settings = self._settings
        torrent_hash = str(row["hash"])
        if self._guard.cancel_requested(torrent_hash):
            raise _Stop("aborted")
        src, identity = self._resolve(row, file)
        relative = os.path.relpath(src, settings.quarantine_root)
        facts: ProbeFacts | None = None
        for _attempt in range(2):
            if self._guard.cancel_requested(torrent_hash):
                raise _Stop("aborted")
            try:
                facts = await self._runner.probe(relative)
            except RunnerUnavailable as exc:
                self._runner_unavailable(exc.why)
                raise _Stop("waiting") from None
            except RunnerRefused as refused:
                if refused.code != "not_regular_file":
                    # The backend lstat'ed this file a moment ago, so "not found" or "invalid path"
                    # means the runner and the backend disagree about the quarantine folder (a stale
                    # bind mount, another version): a host fault, never a verdict (D-58, CR-02).
                    self._runner_unavailable("path_mismatch")
                    raise _Stop("waiting") from None
                # It answered about this file, and not about the host: this file cannot be probed.
                self._runner_down = None
                return _Checked(file, identity, False, "unprobeable")
            self._runner_down = None
            if facts.status == "ok":
                break
        assert facts is not None
        verdict = judge(
            final_extension(file.name),
            facts,
            identity[1],
            min_minutes=min_minutes_for(
                content_type,
                file.is_main,
                film_minutes=settings.min_film_duration_minutes,
                episode_minutes=settings.min_episode_duration_minutes,
            ),
            min_kbps=settings.min_bitrate_kbps,
            max_kbps=settings.max_bitrate_kbps,
        )
        return _Checked(file, identity, verdict.passed, verdict.reason, facts)

    async def _check_subtitle(self, row: dict, file: FileToCheck) -> _Checked:
        """Screen a subtitle in the backend itself: it never reaches the VM."""
        settings = self._settings
        if self._guard.cancel_requested(str(row["hash"])):
            raise _Stop("aborted")
        src, identity = self._resolve(row, file)
        head = await asyncio.to_thread(_read_head, src, settings.subtitle_text_max_bytes)
        verdict = check_subtitle(
            final_extension(file.name),
            identity[1],
            head,
            text_max_bytes=settings.subtitle_text_max_bytes,
            bitmap_max_bytes=settings.subtitle_bitmap_max_bytes,
        )
        return _Checked(file, identity, verdict.passed, verdict.reason)

    async def _hand_off(self, row: dict, checked: list[_Checked], content_type: ContentType) -> str:
        """Deliver the outcome of a check, all under the torrent's lock (D-54).

        Inside the lock the torrent is read again and every file is re-resolved and compared with
        the identity it had at its probe, so nothing is linked that was cancelled, deleted or
        changed since the VM looked at it. Everything that can fail comes first and the delete
        comes last: links, then the outcome sidecar, then the audit lines, then the delete.

        Every checked file passed: link all into media and tag the torrent (it keeps seeding).
        Otherwise a file failed, or there was no video to check: link what passed into media and
        the failing files into the rejected folder, store a sidecar ("ready" when a video
        passed, else "rejected"), and delete the torrent with its files at once, so a torrent
        that held a suspect file is never seeded (D-61, D-62). The delete removes only the
        quarantine names; the media links keep the files that passed.
        """
        settings = self._settings
        torrent_hash = str(row["hash"])
        category = str(row["category"])
        media_dir = settings.media_paths[category]
        passing = [item for item in checked if item.passed]
        failing = [item for item in checked if not item.passed]
        async with self._guard.lock(torrent_hash):
            if self._guard.cancel_requested(torrent_hash):
                return "aborted"
            current = next(
                (
                    r
                    for r in await self._qbit.torrents_info(hashes=torrent_hash)
                    if str(r.get("hash") or "").lower() == torrent_hash.lower()
                ),
                None,
            )
            if (
                current is None
                or not is_candidate(current, settings)
                or current.get("save_path") != row["save_path"]
            ):
                return "aborted"
            if self._guard.cancel_requested(torrent_hash):
                return "aborted"
            sources: dict[int, Path] = {}
            for item in checked:
                try:
                    src = source_path(
                        str(row["save_path"]), item.file.name, settings.quarantine_root
                    )
                    if _identity(src) != item.identity:
                        return "aborted"
                except (HandoffError, OSError):
                    return "aborted"
                sources[item.file.index] = src
            rejected_dir = self._outcomes.rejected_dir(self._outcome_id(row))
            try:
                for item in passing:
                    link_into_media(
                        sources[item.file.index],
                        media_target(media_dir, item.file.name),
                        media_dir=media_dir,
                    )
                for item in failing:
                    link_into_rejected(sources[item.file.index], rejected_dir, item.file.name)
            except HandoffError as exc:
                self._link_failed(row, exc.why)
                return "held"
            if not failing and checked:
                await self._qbit.add_tags([torrent_hash], [verified_tag(self._clock())])
                audit.quarantine_passed(display_name(row), len(passing))
                return "passed"
            video_passed = any(item.file.kind == "video" for item in passing)
            skipped = sum(1 for item in failing if item.file.kind == "video")
            self._outcomes.write(
                Outcome(
                    self._outcome_id(row),
                    display_name(row),
                    content_type,
                    "ready" if video_passed else "rejected",
                    skipped,
                    self._clock(),
                )
            )
            for item in failing:
                self._audit_rejected(row, item)
            if not checked:  # nothing to check at all: a torrent without a video to keep
                audit.quarantine_rejected(
                    display_name(row), None, "no_video", None, None, None, None, None
                )
            await self._qbit.delete([torrent_hash], delete_files=True)
            if video_passed:
                audit.quarantine_passed(display_name(row), len(passing))
        return "partial" if video_passed else "rejected"

    def _audit_rejected(self, row: dict, item: _Checked) -> None:
        facts = summary(item.facts) if item.facts is not None else {}
        audit.quarantine_rejected(
            display_name(row),
            item.file.name,
            item.reason or "failed",
            facts.get("format"),
            facts.get("codec"),
            facts.get("duration"),
            item.identity[1],
            item.facts.ffmpeg if item.facts is not None else None,
        )


def _identity(path: Path) -> tuple[int, int, int]:
    """(inode, size, mtime_ns) of a file: what must not change between its probe and its link."""
    info = os.stat(path)
    return (info.st_ino, info.st_size, info.st_mtime_ns)


def _read_head(path: Path, limit: int) -> bytes:
    """At most `limit` bytes of a file, read-only (a subtitle is screened by the backend itself)."""
    with open(path, "rb") as handle:
        return handle.read(limit)
