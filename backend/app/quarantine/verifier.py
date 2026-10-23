"""The verifier: finished downloads are checked in the sandbox, then handed off to media.

One tick finds every completed Film or SerieTV torrent that sits in quarantine and has no
`fx-ok-` tag (D-45, D-49, D-51). Files come only from qBittorrent's file list, never from walking
a folder. The files `files_to_check` chooses are probed one at a time through the runner (D-52) and
judged with the backend's own stat size (D-64, D-65). Only when every checked file passed, each one
is hardlinked into the media folder of its category and then the torrent is tagged `fx-ok-<epoch>`
(D-46, D-54). The tag comes last, so a crash at any point leaves the torrent untagged and the next
tick checks it again (D-63).

Faults of the host are never verdicts (D-58): a runner that cannot answer stops the tick, writes one
audit line per outage and leaves every row Checking. A file that fails or cannot be probed, in this
plan, leaves its torrent untouched in quarantine, which is the fail-closed base that plan 02.1-07's
rejection path replaces. The hand-off runs under the torrent's lock and re-reads the torrent and
the files inside it, so a cancel, a vanished torrent or a changed file links nothing (RESEARCH
Pattern 5, Pitfall 10).
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
from app.content_type import type_for_category
from app.download.allowlist import final_extension
from app.download.listing import READY_STATES, display_name, tags_of
from app.qbit.bootstrap import Readiness
from app.qbit.client import QbitClient, QbitError
from app.quarantine.guard import HandoffGuard
from app.quarantine.handoff import (
    HandoffError,
    link_into_media,
    media_target,
    source_path,
)
from app.quarantine.rules import (
    FileToCheck,
    files_to_check,
    in_quarantine,
    judge,
    min_minutes_for,
    verified_at,
    verified_tag,
)
from app.quarantine.runner_client import RunnerClient, RunnerRefused, RunnerUnavailable
from app.quarantine.subtitles import check_subtitle

logger = logging.getLogger(__name__)

# A re-hash of a finished torrent is not a candidate until it settles.
CANDIDATE_STATES = READY_STATES - {"checkingUP"}
# While bootstrap has not marked qBittorrent ready (its categories do not point at quarantine yet),
# the loop does not touch qBittorrent at all; it looks again after this many seconds.
READINESS_WAIT_SECONDS = 1


@dataclass(frozen=True, slots=True)
class _Passed:
    """A file that passed in this run, with the identity it had when it was probed (T-02.1-23)."""

    file: FileToCheck
    identity: tuple[int, int, int]


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
    ) -> None:
        self._qbit = qbit
        self._runner = runner
        self._settings = settings
        self._guard = guard if guard is not None else HandoffGuard()
        self._clock = clock
        self._sleep = sleep
        self._readiness = readiness
        self._runner_down: str | None = None

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
        candidates = [row for row in rows if is_candidate(row, self._settings)]
        candidates.sort(key=lambda row: (row.get("completion_on") or 0, str(row.get("hash"))))
        for row in candidates:
            if await self.check_torrent(row) == "waiting":
                break  # the runner is down: later torrents would only hit the same wall

    def _runner_unavailable(self, why: str) -> None:
        if self._runner_down is None:  # one line per outage, not one per tick
            audit.quarantine_runner_unavailable(why)
        self._runner_down = why

    async def check_torrent(self, row: dict) -> str:
        """Probe, judge and hand off one torrent.

        Returns "passed" (linked and tagged), "waiting" (the runner is down), "aborted" (a cancel,
        a vanished torrent or a changed file: nothing linked) or "held" (a file failed or could
        not be checked, or a link failed: nothing more happens to the torrent here).
        """
        settings = self._settings
        torrent_hash = str(row["hash"])
        category = str(row["category"])
        save_path = str(row["save_path"])
        content_type = type_for_category(settings, category)
        if content_type is None:
            return "held"
        if self._guard.cancel_requested(torrent_hash):
            return "aborted"
        try:
            file_rows = await self._qbit.torrent_files(torrent_hash)
        except QbitError as exc:
            if exc.status == 404:
                return "aborted"  # deleted between the listing and now
            raise
        files = files_to_check(file_rows, content_type)
        if not any(f.kind == "video" for f in files):
            return "held"
        passed: list[_Passed] = []
        for file in files:
            if self._guard.cancel_requested(torrent_hash):
                return "aborted"
            try:
                src = source_path(save_path, file.name, settings.quarantine_root)
                identity = _identity(src)
            except (HandoffError, OSError):
                return "held"
            size = identity[1]
            if file.kind == "video":
                try:
                    facts = await self._runner.probe(os.path.relpath(src, settings.quarantine_root))
                except RunnerUnavailable as exc:
                    self._runner_unavailable(exc.why)
                    return "waiting"
                except RunnerRefused:
                    self._runner_down = None  # it answered: about this file, not the host
                    return "held"
                self._runner_down = None
                verdict = judge(
                    final_extension(file.name),
                    facts,
                    size,
                    min_minutes=min_minutes_for(
                        content_type,
                        file.is_main,
                        film_minutes=settings.min_film_duration_minutes,
                        episode_minutes=settings.min_episode_duration_minutes,
                    ),
                    min_kbps=settings.min_bitrate_kbps,
                    max_kbps=settings.max_bitrate_kbps,
                )
            else:
                head = await asyncio.to_thread(_read_head, src, settings.subtitle_text_max_bytes)
                verdict = check_subtitle(
                    final_extension(file.name),
                    size,
                    head,
                    text_max_bytes=settings.subtitle_text_max_bytes,
                    bitmap_max_bytes=settings.subtitle_bitmap_max_bytes,
                )
            if not verdict.passed:
                return "held"
            passed.append(_Passed(file, identity))
        return await self._hand_off(row, passed)

    async def _hand_off(self, row: dict, passed: list[_Passed]) -> str:
        """Link every passed file and tag the torrent, all under the torrent's lock (D-54).

        Inside the lock the torrent is read again and every file is re-resolved and compared with
        the identity it had at its probe, so nothing is linked that was cancelled, deleted or
        changed since the VM looked at it.
        """
        settings = self._settings
        torrent_hash = str(row["hash"])
        category = str(row["category"])
        media_dir = settings.media_paths[category]
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
            sources: list[Path] = []
            for item in passed:
                try:
                    src = source_path(
                        str(row["save_path"]), item.file.name, settings.quarantine_root
                    )
                    if _identity(src) != item.identity:
                        return "aborted"
                except (HandoffError, OSError):
                    return "aborted"
                sources.append(src)
            try:
                for item, src in zip(passed, sources, strict=True):
                    link_into_media(
                        src, media_target(media_dir, item.file.name), media_dir=media_dir
                    )
            except HandoffError:
                return "held"
            await self._qbit.add_tags([torrent_hash], [verified_tag(self._clock())])
        audit.quarantine_passed(display_name(row), len(passed))
        return "passed"


def _identity(path: Path) -> tuple[int, int, int]:
    """(inode, size, mtime_ns) of a file: what must not change between its probe and its link."""
    info = os.stat(path)
    return (info.st_ino, info.st_size, info.st_mtime_ns)


def _read_head(path: Path, limit: int) -> bytes:
    """At most `limit` bytes of a file, read-only (a subtitle is screened by the backend itself)."""
    with open(path, "rb") as handle:
        return handle.read(limit)
