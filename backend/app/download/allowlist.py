"""Pure file-decision rules for FILT-01/FILT-02 (RED skeleton: behaviour not implemented yet)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

VIDEO_EXTENSIONS = frozenset({".mkv", ".mp4", ".avi", ".m4v"})
SUBTITLE_EXTENSIONS = frozenset({".srt", ".ass", ".ssa", ".sub", ".idx"})


@dataclass(frozen=True, slots=True)
class TorrentFile:
    index: int
    name: str
    size: int
    priority: int

    @classmethod
    def from_qbit(cls, row: dict) -> TorrentFile:
        return cls(index=-1, name="", size=0, priority=0)


@dataclass(frozen=True, slots=True)
class FileDecision:
    accept: bool
    keep_ids: tuple[int, ...]
    zero_ids: tuple[int, ...]
    reason: str | None


def final_extension(path: str) -> str:
    return ""


def decide(files: Sequence[TorrentFile]) -> FileDecision:
    return FileDecision(accept=False, keep_ids=(), zero_ids=(), reason="not_implemented")
