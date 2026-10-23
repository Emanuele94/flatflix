"""Outcomes that outlive their torrent (D-54, D-77).

When a torrent leaves qBittorrent (its failing files held in the rejected folder, or its seeding
finished) the household must still see what happened to it. The verifier writes one small JSON
sidecar per torrent next to the held files: `<rejected_root>/<id>.json`. It holds the opaque
download id, the torrent name, its type, the kind of outcome, how many videos were skipped and when.
It never holds a reason, a path or an info-hash: the reason is for the admin, in the audit log
(D-60), and the household reads a plain sentence built from `kind` and `skipped`.

Writes are atomic (a temp file, then `os.replace`) and owner-only. Nothing here follows a symlink.
"""

import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.content_type import ContentType

OutcomeKind = Literal["rejected", "ready"]

_ID = re.compile(r"[0-9a-f]{16}")
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
