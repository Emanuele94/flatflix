"""The verifier: finished downloads are checked in the sandbox, then handed off to media.

One tick finds every completed Film or SerieTV torrent that sits in quarantine and has no
`fx-ok-` tag (D-45, D-49, D-51). Files come only from qBittorrent's file list, never from walking
a folder. The files `files_to_check` chooses are probed one at a time through the runner (D-52) and
judged with the backend's own stat size (D-64, D-65). Only when every checked file passed, each one
is hardlinked into the media folder of its category and then the torrent is tagged `fx-ok-<epoch>`
(D-46, D-54). The tag comes last, so a crash at any point leaves the torrent untagged and the next
tick checks it again (D-63).
"""

import asyncio
import os
import time
from collections.abc import Callable
from pathlib import Path

from app.config import Settings
from app.content_type import type_for_category
from app.download.allowlist import final_extension
from app.download.listing import READY_STATES, tags_of
from app.qbit.client import QbitClient
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
from app.quarantine.runner_client import RunnerClient, RunnerRefused
from app.quarantine.subtitles import check_subtitle

# A re-hash of a finished torrent is not a candidate until it settles.
CANDIDATE_STATES = READY_STATES - {"checkingUP"}


def is_candidate(row: dict, settings: Settings) -> bool:
    """A finished Film or SerieTV torrent saved strictly inside quarantine, not yet verified."""
    return (
        type_for_category(settings, str(row.get("category") or "")) is not None
        and str(row.get("state") or "") in CANDIDATE_STATES
        and in_quarantine(str(row.get("save_path") or ""), settings.quarantine_root)
        and verified_at(tags_of(row)) is None
    )


def _read_head(path: Path, limit: int) -> bytes:
    """At most `limit` bytes of a file, read-only (a subtitle is screened by the backend itself)."""
    with open(path, "rb") as handle:
        return handle.read(limit)


class Verifier:
    def __init__(
        self,
        qbit: QbitClient,
        runner: RunnerClient,
        settings: Settings,
        *,
        guard=None,
        clock: Callable[[], float] = time.time,
        sleep=asyncio.sleep,
        readiness=None,
    ) -> None:
        self._qbit = qbit
        self._runner = runner
        self._settings = settings
        self._guard = guard
        self._clock = clock
        self._sleep = sleep
        self._readiness = readiness

    async def run_once(self) -> None:
        """Check every candidate, oldest completion first, one at a time (D-52)."""
        rows = await self._qbit.torrents_info()
        candidates = [row for row in rows if is_candidate(row, self._settings)]
        candidates.sort(key=lambda row: (row.get("completion_on") or 0, str(row.get("hash"))))
        for row in candidates:
            await self.check_torrent(row)

    async def check_torrent(self, row: dict) -> str:
        """Probe, judge and hand off one torrent: "passed" or "held" (nothing linked)."""
        settings = self._settings
        torrent_hash = str(row["hash"])
        category = str(row["category"])
        content_type = type_for_category(settings, category)
        if content_type is None:
            return "held"
        save_path = str(row["save_path"])
        files = files_to_check(await self._qbit.torrent_files(torrent_hash), content_type)
        if not any(f.kind == "video" for f in files):
            return "held"
        passed: list[tuple[FileToCheck, Path]] = []
        for file in files:
            try:
                src = source_path(save_path, file.name, settings.quarantine_root)
            except HandoffError:
                return "held"
            size = os.stat(src).st_size
            if file.kind == "video":
                rel = os.path.relpath(src, settings.quarantine_root)
                try:
                    facts = await self._runner.probe(rel)
                except RunnerRefused:
                    return "held"
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
            passed.append((file, src))
        media_dir = settings.media_paths[category]
        try:
            for file, src in passed:
                link_into_media(src, media_target(media_dir, file.name), media_dir=media_dir)
        except HandoffError:
            return "held"
        await self._qbit.add_tags([torrent_hash], [verified_tag(self._clock())])
        return "passed"
