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
from app.download.jobs import FAILED_STATES, Job, JobState

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

# Raw states of a torrent that has not finished and that the portal treats as in progress: the only
# ones whose partial files a cancel deletes (D-32). `moving` is a finished torrent on its way to
# its final folder, so it is left out; so is every `...UP` state and any state qBittorrent adds
# later, which keep their files (D-33).
IN_PROGRESS_RAW_STATES = (
    (DOWNLOADING_STATES - {"moving"})
    | PREPARING_STATES
    | STOPPED_DL_STATES
    | PROBLEM_STATES
    | {"stalledDL"}
)

# The job states that get a row of their own while young: the plain state is the job state value.
FAILED_JOB_STATES = frozenset(state.value for state in FAILED_STATES)

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


def cancel_deletes_files(row: dict) -> bool:
    """True when cancelling this torrent deletes its files: it never finished and is below 100 %.

    Decided on the server from the row it just read, never from the browser. The files go only on
    positive evidence that the film never completed: a known in-progress state, a progress below
    100 % and no completion time. qBittorrent reports `completion_on` as -1 until a torrent first
    completes, while a finished film that is being re-checked, or has not loaded its resume data
    yet after a restart, can read as progress 0. So a torrent that finished once keeps its files,
    and so does a moving, completed or unrecognised one (D-33). A progress or a completion time
    that is not a number reads as finished.
    """
    if str(row.get("state") or "") not in IN_PROGRESS_RAW_STATES:
        return False
    try:
        completed_at = row.get("completion_on")
        if completed_at not in (None, "") and not float(completed_at) <= 0:
            return False  # it finished at least once (and a non-finite value reads as finished)
        progress = float(row.get("progress") or 0)
    except (TypeError, ValueError):
        return False
    return math.isfinite(progress) and progress < 1


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


def find_torrent(
    rows: Iterable[dict], wanted_id: str, settings: Settings, secret: str
) -> dict | None:
    """The Film or SerieTV torrent whose opaque id is `wanted_id`, or None (D-35).

    A row in any other category (Other, Film/Extra) never matches, whatever id was sent.
    """
    for row in rows:
        if type_for_category(settings, str(row.get("category") or "")) is None:
            continue
        if hmac.compare_digest(download_id(secret, str(row.get("hash") or "")), wanted_id):
            return row
    return None


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


def job_name(job: Job | None) -> str | None:
    """A job's name for a torrent row; a bare info-hash is no name (a reconciled job)."""
    if job is None:
        return None
    name = (job.name or "").strip()
    return None if not name or HASH_NAME.match(name) else name


def build_items(
    rows: Iterable[dict],
    settings: Settings,
    *,
    now: float,
    secret: str,
    jobs: Iterable[Job] = (),
) -> list[dict]:
    """The list the household sees: Film and SerieTV torrents and attempts no torrent shows.

    The torrent is the primary identity and appears exactly once. A job adds a row only when no
    torrent represents it: a failed attempt (while young, D-29) or a Preparing tap whose torrent
    is not in qBittorrent yet. Active rows come first, newest first inside each group (D-30).
    """
    jobs = list(jobs)
    by_hash = {j.torrent_hash.lower(): j for j in jobs if j.torrent_hash}
    by_id = {j.job_id: j for j in jobs}
    kept: list[tuple[tuple[int, float, str], dict]] = []
    kept_hashes: set[str] = set()
    tagged_job_ids: set[str] = set()
    for row in rows:
        content_type = type_for_category(settings, str(row.get("category") or ""))
        if content_type is None:
            continue
        state = plain_state(row)
        stamp = sort_time(row)
        # D-28: a finished download leaves the list from exactly this age on; the torrent stays.
        if state == "ready" and now - stamp >= settings.completed_visible_seconds:
            continue
        torrent_hash = str(row.get("hash") or "")
        job_tag = job_tag_of(tags_of(row))
        tagged_id = job_tag.removeprefix(TAG_JOB_PREFIX) if job_tag else None
        # The job was cancelled: its torrent is on its way out (a sweep or the next reconcile).
        cancelled = by_id.get(tagged_id or "")
        if cancelled is not None and cancelled.state is JobState.CANCELLED:
            continue
        kept_hashes.add(torrent_hash.lower())
        if tagged_id:
            tagged_job_ids.add(tagged_id)
        name = display_name(row)
        if name is None:  # a magnet still named by its hash takes its job's name (Pitfall 11)
            owner = by_hash.get(torrent_hash.lower()) or by_id.get(tagged_id or "")
            name = job_name(owner)
        item_id = download_id(secret, torrent_hash)
        item = {
            "id": item_id,
            "name": name,
            "type": content_type,
            "state": state,
            "progress": percent(row, state),
            "eta_seconds": eta_of(row, state),
            # The button must name what DELETE then does: "cancel" deletes the partial files,
            # "remove" keeps them, and the server decides with the same function (D-32, D-33).
            "action": "cancel" if cancel_deletes_files(row) else "remove",
        }
        kept.append(((0 if state in ACTIVE_PLAIN_STATES else 1, -stamp, item_id), item))
    for job in jobs:
        if job.state is JobState.PREPARING:
            if job.job_id in tagged_job_ids or (
                job.torrent_hash and job.torrent_hash.lower() in kept_hashes
            ):
                continue  # the torrent row represents it
            item = _job_item(job, "preparing", "cancel")
            kept.append(((0, -job.created_at, job.job_id), item))
        # D-29: a failed attempt stays visible, with its plain reason, until this age.
        elif (
            job.state.value in FAILED_JOB_STATES
            and job.finished_at is not None
            and now - job.finished_at < settings.failed_visible_seconds
        ):
            item = _job_item(job, job.state.value, None)
            kept.append(((1, -job.finished_at, job.job_id), item))
    kept.sort(key=lambda pair: pair[0])
    return [item for _, item in kept]


def _job_item(job: Job, state: str, action: str | None) -> dict:
    """The same seven keys as a torrent row; the id is the opaque job id the browser holds."""
    return {
        "id": job.job_id,
        "name": job_name(job),
        "type": job.type,
        "state": state,
        "progress": 0,
        "eta_seconds": None,
        "action": action,
    }
