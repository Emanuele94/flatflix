"""Outcomes that outlive their torrent (D-54, D-77).

When a torrent leaves qBittorrent (its failing files held in the rejected folder, or its seeding
finished) the household must still see what happened to it. The verifier writes one small JSON
sidecar per torrent next to the held files: `<rejected_root>/<id>.json`. It holds the opaque
download id, the torrent name, its type, the kind of outcome, how many videos were skipped and when.
It never holds a reason, a path or an info-hash: the reason is for the admin, in the audit log
(D-60), and the household reads a plain sentence built from `kind` and `skipped`.

Writes are atomic (a temp file, then `os.replace`) and owner-only. Nothing here follows a symlink.
Sidecars and held folders are purged after the retention (D-55); a purge never raises and logs
only the class name of a failure.
"""

import json
import logging
import os
import re
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.content_type import ContentType

OutcomeKind = Literal["rejected", "ready"]

logger = logging.getLogger(__name__)

_ID = re.compile(r"[0-9a-f]{16}")
_SIDECAR = re.compile(r"([0-9a-f]{16})\.json")
_KEYS = frozenset({"id", "name", "type", "kind", "skipped", "at"})
_KINDS = ("rejected", "ready")
_TYPES = ("film", "serie")


@dataclass(frozen=True, slots=True)
class Outcome:
    """What became of a torrent that is no longer (or soon no longer) in qBittorrent."""

    id: str
    name: str | None
    type: ContentType | None
    kind: OutcomeKind
    skipped: int
    at: float


def valid_id(value: object) -> bool:
    return isinstance(value, str) and _ID.fullmatch(value) is not None


def _parse(raw: object, expected_id: str | None = None) -> Outcome | None:
    """The outcome a decoded sidecar describes, or None when anything about it is off."""
    if not isinstance(raw, dict) or set(raw) != _KEYS:
        return None
    outcome_id, name, kind_type = raw["id"], raw["name"], raw["type"]
    kind, skipped, at = raw["kind"], raw["skipped"], raw["at"]
    if not valid_id(outcome_id) or (expected_id is not None and outcome_id != expected_id):
        return None
    if name is not None and not isinstance(name, str):
        return None
    if kind_type is not None and kind_type not in _TYPES:
        return None
    if kind not in _KINDS:
        return None
    if isinstance(skipped, bool) or not isinstance(skipped, int) or skipped < 0:
        return None
    if isinstance(at, bool) or not isinstance(at, int | float):
        return None
    return Outcome(outcome_id, name, kind_type, kind, skipped, float(at))


def _read_json(path: str) -> object:
    """The decoded content of a regular file, never through a symlink; None when unreadable."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        with os.fdopen(fd, "rb", closefd=False) as handle:
            return json.loads(handle.read(65536))
    except (OSError, ValueError):
        return None
    finally:
        os.close(fd)


class OutcomeStore:
    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    @property
    def root(self) -> Path:
        return self._root

    def rejected_dir(self, outcome_id: str) -> Path:
        """The folder that holds the failing files of one torrent."""
        if not valid_id(outcome_id):
            raise ValueError("invalid outcome id")
        return self._root / outcome_id

    def _sidecar(self, outcome_id: str) -> Path:
        return self._root / f"{outcome_id}.json"

    def write(self, outcome: Outcome) -> None:
        """Store the outcome atomically, owner-only. Exactly six keys, no reason (D-77)."""
        if not valid_id(outcome.id):
            raise ValueError("invalid outcome id")
        payload = json.dumps(
            {
                "id": outcome.id,
                "name": outcome.name,
                "type": outcome.type,
                "kind": outcome.kind,
                "skipped": outcome.skipped,
                "at": outcome.at,
            }
        ).encode("utf-8")
        os.makedirs(self._root, mode=0o700, exist_ok=True)
        temp = self._root / f".{outcome.id}.json.tmp"
        try:
            os.unlink(temp)  # a leftover of an interrupted write
        except FileNotFoundError:
            pass
        fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self._sidecar(outcome.id))
        except BaseException:
            try:
                os.unlink(temp)
            except OSError:
                pass
            raise

    def get(self, outcome_id: str) -> Outcome | None:
        """The stored outcome of an id, or None when there is none or it is malformed."""
        if not valid_id(outcome_id):
            return None
        return _parse(_read_json(str(self._sidecar(outcome_id))), outcome_id)

    def load_all(self) -> list[Outcome]:
        """Every well-formed outcome; never raises. Anything else in the folder is ignored."""
        found: list[Outcome] = []
        try:
            with os.scandir(self._root) as entries:
                listing = sorted(entries, key=lambda entry: entry.name)
        except OSError:
            return found
        for entry in listing:
            match = _SIDECAR.fullmatch(entry.name)
            if match is None:
                continue
            try:
                if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                    continue
            except OSError:
                continue
            outcome = _parse(_read_json(entry.path), match.group(1))
            if outcome is not None:
                found.append(outcome)
        return found

    def remove(self, outcome_id: str) -> bool:
        """Delete the sidecar of an id; True only when there was one to delete."""
        if not valid_id(outcome_id):
            return False
        try:
            os.unlink(self._sidecar(outcome_id))
        except OSError:
            return False
        return True

    def purge(
        self, now: float, retention_seconds: float, ready_retention_seconds: float | None = None
    ) -> int:
        """Remove sidecars and held folders older than the retention; returns how many entries.

        A "ready" sidecar lives for `ready_retention_seconds` (how long the household sees a Ready
        row, COMPLETED_VISIBLE_DAYS) and every other entry for `retention_seconds`
        (REJECTED_RETENTION_DAYS); without the first, both are the same (WR-08). A sidecar is aged by its `at` (its file time when unreadable), a folder or a stray file by
        its own modification time. A symlink is never one of ours: it is removed as a link at once
        and never followed, and `shutil.rmtree` does not follow links inside a folder. Never raises.
        """
        cutoff = now - retention_seconds
        ready_cutoff = now - (
            retention_seconds if ready_retention_seconds is None else ready_retention_seconds
        )
        try:
            with os.scandir(self._root) as entries:
                listing = [entry.path for entry in entries]
        except OSError:
            return 0
        removed = 0
        for path in listing:
            try:
                if self._purge_entry(path, cutoff, ready_cutoff):
                    removed += 1
            except Exception as exc:  # noqa: BLE001 - one stubborn entry must not stop the rest
                logger.error("purge of a held entry failed (%s)", type(exc).__name__)
        return removed

    @staticmethod
    def _purge_entry(path: str, cutoff: float, ready_cutoff: float) -> bool:
        info = os.lstat(path)
        if stat.S_ISLNK(info.st_mode):
            os.unlink(path)
            return True
        if stat.S_ISDIR(info.st_mode):
            if info.st_mtime >= cutoff:
                return False
            shutil.rmtree(path)
            return True
        stored_at = info.st_mtime
        match = _SIDECAR.fullmatch(os.path.basename(path))
        if match is not None:
            outcome = _parse(_read_json(path), match.group(1))
            if outcome is not None:
                stored_at = outcome.at
                if outcome.kind == "ready":
                    cutoff = ready_cutoff
        if stored_at >= cutoff:
            return False
        os.unlink(path)
        return True
