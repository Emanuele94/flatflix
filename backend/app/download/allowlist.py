"""Pure file-decision rules for FILT-01/FILT-02.

No I/O and no framework imports: the pipeline (01-08) feeds it qBittorrent file rows.
"""

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
        return cls(
            index=int(row["index"]),
            name=str(row["name"]),
            size=int(row["size"]),
            priority=int(row["priority"]),
        )


@dataclass(frozen=True, slots=True)
class FileDecision:
    accept: bool
    keep_ids: tuple[int, ...]
    zero_ids: tuple[int, ...]
    reason: str | None


def final_extension(path: str) -> str:
    """Final suffix (with dot) of the last '/'-separated component, lower-cased; '' if none."""
    base = path.rsplit("/", 1)[-1].lower()
    dot = base.rfind(".")
    return "" if dot == -1 else base[dot:]


def decide(files: Sequence[TorrentFile]) -> FileDecision:
    allowed = VIDEO_EXTENSIONS | SUBTITLE_EXTENSIONS
    keep = sorted(f.index for f in files if final_extension(f.name) in allowed)
    zero = sorted(f.index for f in files if final_extension(f.name) not in allowed)
    return FileDecision(accept=True, keep_ids=tuple(keep), zero_ids=tuple(zero), reason=None)
