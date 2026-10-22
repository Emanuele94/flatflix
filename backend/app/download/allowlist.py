"""Pure file-decision rules for FILT-01/FILT-02.

No I/O and no framework imports: the pipeline (01-08) feeds it qBittorrent file rows.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

VIDEO_EXTENSIONS = frozenset({".mkv", ".mp4", ".avi", ".m4v"})
SUBTITLE_EXTENSIONS = frozenset({".srt", ".ass", ".ssa", ".sub", ".idx"})

# Sent to qBittorrent as defence in depth (FILT-01); the per-file allowlist in decide() is the
# real control. The first 11 entries are the FILT-01 list, in order. All lower-case: qBittorrent
# matches case-insensitively. Never add domain or folder suffixes (qBittorrent also matches
# parent folder names, so such a pattern would silently exclude real videos).
EXCLUDED_FILE_PATTERNS: tuple[str, ...] = (
    "*.exe",
    "*.bat",
    "*.cmd",
    "*.ps1",
    "*.scr",
    "*.lnk",
    "*.msi",
    "*.zip",
    "*.rar",
    "*.7z",
    "*.iso",
    "*.pif",
    "*.vbs",
    "*.jar",
    "*.dll",
    "*.apk",
    "*.dmg",
    "*.cab",
)

# A video smaller than this share of the largest allowed video is treated as a sample (D-14).
SAMPLE_SIZE_RATIO = 0.10

_SAMPLE_WORD = re.compile(r"(^|[\W_])sample([\W_]|$)")


def is_sample_name(path: str) -> bool:
    """True when any '/'-separated component contains 'sample' as a separate word."""
    return any(_SAMPLE_WORD.search(part.casefold()) for part in path.split("/"))


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
    """Split a torrent's files into keep/zero indexes, or reject it when no main video exists.

    Allowed videos and subtitles are kept; samples and every other file get priority 0.
    Only the final lower-cased extension counts, so `movie.mkv.exe` is blocked.
    """
    videos = [f for f in files if final_extension(f.name) in VIDEO_EXTENSIONS]
    largest = max((f.size for f in videos), default=0)
    # Integer math: a video of exactly 10 % of the largest is kept (ratio 0.10 == 1/10).
    main_videos = {f.index for f in videos if not is_sample_name(f.name) and f.size * 10 >= largest}
    all_ids = sorted(f.index for f in files)
    if not main_videos:
        return FileDecision(accept=False, keep_ids=(), zero_ids=tuple(all_ids), reason="no_video")

    keep = sorted(
        f.index
        for f in files
        if f.index in main_videos or final_extension(f.name) in SUBTITLE_EXTENSIONS
    )
    keep_set = set(keep)
    zero = [i for i in all_ids if i not in keep_set]
    return FileDecision(accept=True, keep_ids=tuple(keep), zero_ids=tuple(zero), reason=None)
