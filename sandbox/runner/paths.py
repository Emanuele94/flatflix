"""Path resolution for the sandbox runner (QUAR-02, D-69).

The backend sends a path relative to the quarantine root. The runner trusts
nothing in it: the string is checked first, then the filesystem, and the file
that comes out is always a regular file inside the real quarantine root that
was reached without following a single symlink.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path


class InvalidPath(Exception):
    """The path is not a plain relative path inside the quarantine root."""


class NotFound(Exception):
    """The path is well formed but nothing is there."""


class NotRegular(Exception):
    """The path exists but is a directory or another non-regular file."""


def resolve_probe_path(root: Path, rel: str) -> Path:
    """Return the real path of a regular file under ``root``, or raise.

    Why each rule exists (the backend only ever sends names derived from a
    torrent's file list, which an attacker influences):

    - empty, absolute, NUL or backslash: never a name the backend produces;
      NUL would also crash the OS calls, a backslash hides a separator.
    - an empty, "." or ".." segment: lexical escapes and double slashes.
    - the real path must equal the lexical path: a symlink on any hop (a file
      or a directory segment) could point outside the root or at another file
      than the one the backend meant, so no hop is allowed.
    - the real path must sit inside the real root: belt and braces for the
      rule above.
    - lstat must say regular file: a FIFO or device would block or leak.
    """
    if not isinstance(rel, str) or rel == "":
        raise InvalidPath("empty")
    if rel.startswith("/") or "\x00" in rel or "\\" in rel:
        raise InvalidPath("absolute, NUL or backslash")
    for segment in rel.split("/"):
        if segment in ("", ".", ".."):
            raise InvalidPath("bad segment")

    real_root = os.path.realpath(root)
    lexical = os.path.normpath(os.path.join(real_root, rel))
    real = os.path.realpath(lexical)
    if real != lexical:
        raise InvalidPath("symlink hop")
    if not Path(real).is_relative_to(real_root):
        raise InvalidPath("outside root")

    try:
        mode = os.lstat(real).st_mode
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise NotFound(rel) from exc
    if not stat.S_ISREG(mode):
        raise NotRegular(rel)
    return Path(real)
