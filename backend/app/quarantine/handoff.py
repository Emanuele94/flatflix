"""The hand-off: the only code that writes into the media folders (D-46, D-48).

A checked file becomes visible to Jellyfin as a hardlink of the quarantine file: `os.link` only,
never a copy and never a move, so the torrent keeps seeding from quarantine (D-21) and a failed
link can never lose the original. Torrent file names are attacker-controlled, so both ends of a
link are resolved here with the same strict rules (T-02.1-22): no absolute name, no empty, "." or
".." segment, no NUL, no symlink hop, and the result strictly inside its folder.

Every failure is a `HandoffError` whose `why` is a short token (an errno name such as "EXDEV" or
"EPERM", "unsafe_path", "missing", "collision"). It never carries a path.
"""

import errno
import os
import stat
from pathlib import Path


class HandoffError(Exception):
    """A file could not be linked into media; `why` is a short token, never a path."""

    def __init__(self, why: str) -> None:
        super().__init__(f"hand-off refused ({why})")
        self.why = why


def _safe_segments(name: str) -> list[str]:
    """The segments of a torrent-relative file name, or HandoffError("unsafe_path")."""
    if not name or "\x00" in name or name.startswith("/"):
        raise HandoffError("unsafe_path")
    segments = name.split("/")
    if any(part in ("", ".", "..") for part in segments):
        raise HandoffError("unsafe_path")
    return segments


def _strictly_inside(path: str, root: str) -> bool:
    return path != root and path.startswith(root.rstrip("/") + "/")


def source_path(save_path: str, name: str, quarantine_root: str) -> Path:
    """The quarantine file of a torrent file: a regular file strictly inside the quarantine root.

    The path is rebuilt from the real save folder and the checked segments, and the real path of
    the result must equal it, so a symlink anywhere below the save folder is refused.
    """
    _safe_segments(name)
    root_real = os.path.realpath(quarantine_root)
    save_real = os.path.realpath(save_path)
    if not _strictly_inside(save_real, root_real):
        raise HandoffError("unsafe_path")
    expected = os.path.normpath(os.path.join(save_real, name))
    if not _strictly_inside(expected, save_real) or os.path.realpath(expected) != expected:
        raise HandoffError("unsafe_path")
    try:
        mode = os.lstat(expected).st_mode
    except (FileNotFoundError, NotADirectoryError):
        raise HandoffError("missing") from None
    except OSError:
        raise HandoffError("unsafe_path") from None
    if not stat.S_ISREG(mode):
        raise HandoffError("unsafe_path")
    return Path(expected)


def media_target(media_dir: str, name: str) -> Path:
    """Where the file of a torrent goes: the media folder plus the torrent's relative path."""
    _safe_segments(name)
    base = os.path.normpath(media_dir)
    target = os.path.normpath(os.path.join(base, name))
    if not _strictly_inside(target, base):
        raise HandoffError("unsafe_path")
    return Path(target)


def _refuse_symlinked_parents(dst: Path, media_dir: str) -> None:
    """No folder between the media folder and the target may be a symlink."""
    base = Path(os.path.normpath(media_dir))
    try:
        parts = dst.parent.relative_to(base).parts
    except ValueError:
        raise HandoffError("unsafe_path") from None
    current = base
    for part in parts:
        current = current / part
        try:
            if stat.S_ISLNK(os.lstat(current).st_mode):
                raise HandoffError("unsafe_path")
        except OSError as exc:
            raise HandoffError(errno.errorcode.get(exc.errno or 0, "unsafe_path")) from None


def link_into_media(src: Path, dst: Path, *, media_dir: str | None = None) -> Path:
    """Hardlink `src` at `dst`; idempotent and never a copy.

    A target that is already the same file (same device and inode) is left alone, so a hand-off
    interrupted half way is finished by the next try. A different file at the target is a
    collision, never overwritten. `media_dir`, when given, is the folder the target must stay in
    and under which no existing parent may be a symlink.
    """
    try:
        src_stat = os.lstat(src)
    except FileNotFoundError:
        raise HandoffError("missing") from None
    except OSError as exc:
        raise HandoffError(errno.errorcode.get(exc.errno or 0, "unsafe_path")) from None
    if not stat.S_ISREG(src_stat.st_mode):
        raise HandoffError("unsafe_path")
    try:
        os.makedirs(dst.parent, mode=0o775, exist_ok=True)
        if media_dir is not None:
            _refuse_symlinked_parents(dst, media_dir)
        try:
            existing = os.lstat(dst)
        except FileNotFoundError:
            existing = None
        if existing is not None:
            if (
                stat.S_ISREG(existing.st_mode)
                and existing.st_dev == src_stat.st_dev
                and existing.st_ino == src_stat.st_ino
            ):
                return dst
            raise HandoffError("collision")
        os.link(src, dst, follow_symlinks=False)
    except OSError as exc:
        raise HandoffError(errno.errorcode.get(exc.errno or 0, "OSError")) from None
    return dst
