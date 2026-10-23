"""QUAR-03 rules, pure: the verdict on a probed video file (D-64..D-67).

No I/O and no framework imports; thresholds are parameters, so the rules are unit-tested without
KVM and survive a sandbox swap (D-70). The size comes from the backend's own stat, never from the
runner or ffprobe (ffprobe reports 0 for a block device, RESEARCH Pitfall 4). A grossly truncated
file is caught by the bitrate band, while BitTorrent piece hashing guarantees completeness
(Pitfall 9).
"""

import math
import posixpath
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal

from app.content_type import ContentType
from app.download.allowlist import (
    SUBTITLE_EXTENSIONS,
    VIDEO_EXTENSIONS,
    final_extension,
    is_sample_name,
)
from app.quarantine.runner_client import ProbeFacts


@dataclass(frozen=True, slots=True)
class Verdict:
    passed: bool
    reason: str | None


PASS = Verdict(True, None)


def fail(reason: str) -> Verdict:
    return Verdict(False, reason)


# D-66: the container family an extension must have, as tokens of ffprobe's format_name.
FAMILY: dict[str, frozenset[str]] = {
    ".mkv": frozenset({"matroska"}),
    ".mp4": frozenset({"mov", "mp4"}),
    ".m4v": frozenset({"mov", "mp4"}),
    ".avi": frozenset({"avi"}),
}

_NO_CODEC = (None, "", "unknown", "none")


def _duration(facts: ProbeFacts) -> float | None:
    try:
        value = float(facts.duration)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def judge(
    extension: str,
    facts: ProbeFacts,
    size_bytes: int,
    *,
    min_minutes: float,
    min_kbps: int,
    max_kbps: int,
) -> Verdict:
    """Pass a file only when every rule holds; the first broken rule is the reason."""
    if facts.status != "ok":
        return fail(facts.status)
    family = FAMILY.get(extension.lower())
    if family is None:
        return fail("unknown_extension")
    if not family.intersection((facts.format_name or "").split(",")):
        return fail("container_mismatch")
    if not any(
        s.codec_type == "video" and s.codec_name not in _NO_CODEC and not s.attached_pic
        for s in facts.streams
    ):
        return fail("no_video_stream")
    duration = _duration(facts)
    if duration is None or not duration > 0:
        return fail("no_duration")
    if duration < min_minutes * 60:
        return fail("too_short")
    bits = size_bytes * 8
    if bits < min_kbps * 1000 * duration:
        return fail("bitrate_low")
    if bits > max_kbps * 1000 * duration:
        return fail("bitrate_high")
    return PASS


# A token that may go into an audit line: ffprobe output is attacker-influenced.
_LOG_TOKEN = re.compile(r"[A-Za-z0-9_.+-]{1,32}")


def _token(value: str | None) -> str:
    return value if value is not None and _LOG_TOKEN.fullmatch(value) else "none"


def summary(facts: ProbeFacts) -> dict[str, str]:
    """Format, video codec and whole seconds of duration, each safe to log ("none" if unknown)."""
    format_name = (facts.format_name or "").split(",")[0]
    codec = next(
        (
            s.codec_name
            for s in facts.streams
            if s.codec_type == "video" and s.codec_name not in _NO_CODEC and not s.attached_pic
        ),
        None,
    )
    duration = _duration(facts)
    return {
        "format": _token(format_name),
        "codec": _token(codec),
        "duration": str(int(duration)) if duration is not None and duration >= 0 else "none",
    }


@dataclass(frozen=True, slots=True)
class FileToCheck:
    """One file of a torrent that the verifier handles; `name` is relative to the torrent root."""

    index: int
    name: str
    size: int
    kind: Literal["video", "subtitle"]
    is_main: bool


def _usable(row: dict) -> FileToCheck | None:
    """The row as a candidate, or None when it must not be checked or handed off."""
    try:
        index = int(row["index"])
        name = str(row["name"])
        size = int(row["size"])
        priority = int(row["priority"])
        progress = float(row["progress"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if priority <= 0 or not progress >= 1.0:
        return None  # not selected for download, or not finished
    segments = name.split("/")
    # D-46: a dotfile or dot folder is never checked (no "..", no hidden temp parts).
    if any(not part or part.startswith(".") for part in segments):
        return None
    extension = final_extension(name)
    if extension in VIDEO_EXTENSIONS:
        kind: Literal["video", "subtitle"] = "video"
    elif extension in SUBTITLE_EXTENSIONS:
        kind = "subtitle"
    else:
        return None
    if is_sample_name(name):  # D-43: a sample is skipped, never handed off, never a failure
        return None
    return FileToCheck(index, name, size, kind, False)


def files_to_check(rows: Sequence[dict], content_type: ContentType) -> list[FileToCheck]:
    """Choose the files of a torrent to verify, in index order (D-46, D-63, D-64).

    A film's main video is its largest checked video (the lowest index on a tie); the other videos
    are extras. Every video of a series is main, because each is an episode.
    """
    found = [f for row in rows if (f := _usable(row)) is not None]
    videos = [f for f in found if f.kind == "video"]
    if content_type == "film":
        main = min(videos, key=lambda f: (-f.size, f.index), default=None)
        main_ids = {main.index} if main is not None else set()
    else:
        main_ids = {f.index for f in videos}
    return sorted(
        (
            FileToCheck(f.index, f.name, f.size, f.kind, f.index in main_ids and f.kind == "video")
            for f in found
        ),
        key=lambda f: f.index,
    )


def min_minutes_for(
    content_type: ContentType, is_main: bool, *, film_minutes: float, episode_minutes: float
) -> float:
    """D-64: the film minimum applies to the main video only; an extra needs just a real duration
    and the bitrate band. Every video of a series uses the episode minimum."""
    if content_type == "film":
        return film_minutes if is_main else 0.0
    return episode_minutes


# D-54: the qBittorrent tag that marks a torrent as verified, with the epoch seconds of the check.
TAG_VERIFIED_PREFIX = "fx-ok-"
_VERIFIED_TAG = re.compile(re.escape(TAG_VERIFIED_PREFIX) + r"([0-9]{1,12})")


def verified_tag(epoch: float) -> str:
    return f"{TAG_VERIFIED_PREFIX}{int(epoch)}"


def verified_at(tags: Iterable[str]) -> float | None:
    """When the torrent was verified (latest such tag), or None for none or a malformed one."""
    stamps = [float(m.group(1)) for tag in tags if (m := _VERIFIED_TAG.fullmatch(tag.strip()))]
    return max(stamps, default=None)


def in_quarantine(save_path: str, quarantine_root: str) -> bool:
    """True only strictly inside the quarantine root (D-54); the root itself and a sibling that
    merely shares its prefix are outside."""
    path = PurePosixPath(posixpath.normpath(save_path))
    root = PurePosixPath(posixpath.normpath(quarantine_root))
    return path != root and path.is_relative_to(root)
