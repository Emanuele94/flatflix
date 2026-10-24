"""The hand-off: the only code that writes into the media and rejected folders (D-46, D-48).

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


MAX_COLLISION_NAME = 99


def link_into_media(src: Path, dst: Path, *, media_dir: str | None = None) -> Path:
    """Hardlink `src` at `dst` or, when another file holds that name, at the first free
    "<stem> (n)<ext>" for n = 2..99; returns the path it used. Never a copy (D-48).

    Never overwrite: a different file at the target stays as it is (RESEARCH A12; Phase 4 renames
    the files anyway). A target that is already this file (same device and inode) is reused, so a
    hand-off interrupted half way is finished by the next try without a second link. When all names
    up to (99) are taken the answer is HandoffError("collision"). `media_dir`, when given, is the
    folder the target must stay in and under which no existing parent may be a symlink.
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
        candidates = [dst] + [
            dst.with_name(f"{dst.stem} ({n}){dst.suffix}") for n in range(2, MAX_COLLISION_NAME + 1)
        ]
        for candidate in candidates:
            try:
                existing = os.lstat(candidate)
            except FileNotFoundError:
                os.link(src, candidate, follow_symlinks=False)
                return candidate
            if (
                stat.S_ISREG(existing.st_mode)
                and existing.st_dev == src_stat.st_dev
                and existing.st_ino == src_stat.st_ino
            ):
                return candidate
    except OSError as exc:
        raise HandoffError(errno.errorcode.get(exc.errno or 0, "OSError")) from None
    raise HandoffError("collision")


def _private_dir(path: Path) -> None:
    """A real folder (never a symlink) that only the owner can enter; created when missing."""
    try:
        mode = os.lstat(path).st_mode
    except FileNotFoundError:
        os.mkdir(path, 0o700)
        os.chmod(path, 0o700)  # umask-proof
        return
    if not stat.S_ISDIR(mode):
        raise HandoffError("unsafe_path")


def link_into_rejected(src: Path, rejected_dir: Path, name: str) -> Path:
    """Hold a failing file where only the owner can read it: a hardlink at `rejected_dir/name`.

    A link, not a rename, so a crash never leaves a torrent with missing files (RESEARCH Pattern 5);
    the torrent's delete afterwards removes the quarantine name and leaves this one. Folders are
    created 0700, so nobody but the owner can enter them. The file's own mode is never changed: a
    hardlink shares its inode with the quarantine name, so a chmod here would also lock the sandbox
    runner (another uid) out of the quarantine file and stall every later check (CR-01).
    The rejected folder belongs to the backend, so a stale file at the target (a torrent that came
    back under the same id) is replaced; a target that already is this file is left alone.
    """
    segments = _safe_segments(name)
    try:
        src_stat = os.lstat(src)
    except FileNotFoundError:
        raise HandoffError("missing") from None
    except OSError as exc:
        raise HandoffError(errno.errorcode.get(exc.errno or 0, "unsafe_path")) from None
    if not stat.S_ISREG(src_stat.st_mode):
        raise HandoffError("unsafe_path")
    dst = rejected_dir.joinpath(*segments)
    try:
        current = rejected_dir.parent
        os.makedirs(current, exist_ok=True)
        for part in (rejected_dir.name, *segments[:-1]):
            current = current / part
            _private_dir(current)
        try:
            existing = os.lstat(dst)
        except FileNotFoundError:
            existing = None
        if existing is not None and not (
            stat.S_ISREG(existing.st_mode)
            and existing.st_dev == src_stat.st_dev
            and existing.st_ino == src_stat.st_ino
        ):
            if stat.S_ISDIR(existing.st_mode):
                raise HandoffError("collision")
            os.unlink(dst)
            existing = None
        if existing is None:
            os.link(src, dst, follow_symlinks=False)
    except OSError as exc:
        raise HandoffError(errno.errorcode.get(exc.errno or 0, "OSError")) from None
    return dst
