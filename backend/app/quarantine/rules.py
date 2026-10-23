"""QUAR-03 rules, pure: the verdict on a probed video file (D-64..D-67).

No I/O and no framework imports; thresholds are parameters, so the rules are unit-tested without
KVM and survive a sandbox swap (D-70). The size comes from the backend's own stat, never from the
runner or ffprobe (ffprobe reports 0 for a block device, RESEARCH Pitfall 4). A grossly truncated
file is caught by the bitrate band, while BitTorrent piece hashing guarantees completeness
(Pitfall 9).
"""

import math
from dataclasses import dataclass

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
