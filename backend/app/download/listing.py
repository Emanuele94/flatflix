"""The downloads list: what the household sees about a qBittorrent torrent (DOWN-04, D-25..D-35).

Pure functions over qBittorrent `torrents/info` rows, with no I/O, so the route and the later
plans (jobs in the list, cancel) share one set of rules. This is the only place that knows
qBittorrent state names (source of truth: `torrentStateToString` in qBittorrent release-5.2.4
`src/webui/api/serialize/serialize_torrent.cpp`), the only place that decides what a person is
told about a torrent, and the place where Phase 2.1 adds its verifying / rejected-by-probe states.
"""

import hashlib
import hmac
import math
import re
from collections.abc import Iterable

from app.config import Settings
from app.content_type import type_for_category

# Tags set by the download pipeline on the torrents it adds.
TAG_PORTAL = "fx"
TAG_PENDING = "fx-pending"
TAG_JOB_PREFIX = "fx-job-"

# The `...UP` states exist only for a finished torrent (qBittorrent `updateState()`), so they are
# the only route to "ready". 4.x says `pausedUP` where 5.x says `stoppedUP`.
READY_STATES = frozenset(
    {"uploading", "stalledUP", "stoppedUP", "queuedUP", "forcedUP", "checkingUP", "pausedUP"}
)
# `moving` is a finished torrent whose files are not at their final place yet: never "ready".
DOWNLOADING_STATES = frozenset({"downloading", "forcedDL", "moving"})
PREPARING_STATES = frozenset(
    {"metaDL", "forcedMetaDL", "checkingResumeData", "checkingDL", "queuedDL"}
)
PROBLEM_STATES = frozenset({"error", "missingFiles"})
STOPPED_DL_STATES = frozenset({"stoppedDL", "pausedDL"})

# Rows in these plain states are shown first (D-30).
ACTIVE_PLAIN_STATES = frozenset({"preparing", "downloading", "stalled"})

# qBittorrent's "infinite" ETA (`MAX_ETA` in src/base/types.h of release-5.2.4).
MAX_ETA = 8640000

# Until its metadata arrives a magnet without `dn` is named by its bare info-hash (Pitfall 11).
HASH_NAME = re.compile(r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$")

SECONDS_PER_DAY = 86400


def tags_of(row: dict) -> list[str]:
    return [t.strip() for t in str(row.get("tags") or "").split(",") if t.strip()]


def job_tag_of(tags: list[str]) -> str | None:
    return next((t for t in tags if t.startswith(TAG_JOB_PREFIX)), None)


def plain_state(row: dict) -> str:
    """One of preparing, downloading, stalled, ready, problem for a qBittorrent row."""
    state = str(row.get("state") or "")
    if state in READY_STATES:
        return "ready"
    if state in PROBLEM_STATES:
        return "problem"
    if state in DOWNLOADING_STATES:
        return "downloading"
    if state in PREPARING_STATES:
        return "preparing"
    if state in STOPPED_DL_STATES:
        # Stopped on purpose by the portal while the allowlist runs, or stopped by the admin.
        return "preparing" if TAG_PENDING in tags_of(row) else "stalled"
    return "stalled"  # stalledDL and anything unknown: never claim "ready"


def download_id(secret: str, torrent_hash: str) -> str:
    """Opaque id of a torrent: the browser never holds an info-hash (D-35).

    An HMAC, not a bare digest, so an id cannot be tested against a known info-hash without the
    key. It needs no storage: the backend finds the torrent by listing and comparing.
    """
    mac = hmac.new(
        secret.encode("utf-8"),
        b"download-id:" + torrent_hash.lower().encode("utf-8"),
        hashlib.sha256,
    )
    return mac.hexdigest()[:16]


def display_name(row: dict) -> str | None:
    """The torrent name, or None when it is empty or just the info-hash."""
    name = str(row.get("name") or "").strip()
    if not name or HASH_NAME.match(name):
        return None
    return name


def percent(row: dict, state: str) -> int:
    """Whole percent, 0..99 until the torrent is ready (only a finished one reads 100)."""
    if state == "ready":
        return 100
    try:
        value = float(row.get("progress") or 0)
    except (TypeError, ValueError):
        return 0
    if not math.isfinite(value):
        return 0
    return max(0, min(99, math.floor(value * 100)))


def eta_of(row: dict, state: str) -> int | None:
    """Seconds left, only for a downloading torrent with a real estimate."""
    if state != "downloading" or str(row.get("state") or "") == "moving":
        return None
    try:
        eta = int(row.get("eta") or 0)
    except (TypeError, ValueError):
        return None
    return eta if 0 < eta < MAX_ETA else None


def sort_time(row: dict) -> float:
    """When the torrent finished, or was added when it has no completion time (-1 or 0)."""
    for key in ("completion_on", "added_on"):
        try:
            value = float(row.get(key) or 0)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return 0.0


def build_items(rows: Iterable[dict], settings: Settings, *, now: float, secret: str) -> list[dict]:
    """The list the household sees: Film and SerieTV torrents only, active first, newest first."""
    kept: list[tuple[tuple[int, float, str], dict]] = []
    for row in rows:
        content_type = type_for_category(settings, str(row.get("category") or ""))
        if content_type is None:
            continue
        state = plain_state(row)
        stamp = sort_time(row)
        item_id = download_id(secret, str(row.get("hash") or ""))
        item = {
            "id": item_id,
            "name": display_name(row),
            "type": content_type,
            "state": state,
            "progress": percent(row, state),
            "eta_seconds": eta_of(row, state),
            "action": "remove" if state == "ready" else "cancel",
        }
        kept.append(((0 if state in ACTIVE_PLAIN_STATES else 1, -stamp, item_id), item))
    kept.sort(key=lambda pair: pair[0])
    return [item for _, item in kept]
