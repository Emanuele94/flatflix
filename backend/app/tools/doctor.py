"""Admin diagnostic: is qBittorrent configured the way the portal needs?

Run inside the backend container:

    docker compose exec -T backend python -m app.tools.doctor --wait 90

Prints one line per check (names, paths, counts and versions only, never credentials) and
exits 0 when every check passes, 1 otherwise. `--wait SECONDS` re-checks every 2 s until all
checks pass or the time runs out, which covers the first start while bootstrap is running.

The sandbox lines need the stack's sandbox service: the runner with its Firecracker, kernel and
ffmpeg versions, a selftest VM, a canary file that proves the runner sees the same quarantine
folder as the backend, quarantine and media on one filesystem, a test hardlink between
them, how many files are held in rejected, and a note with the number of Film/SerieTV torrents
that save outside quarantine (never checked, D-79). A sandbox that is down, has no usable
/dev/kvm or fails its selftest prints a FAIL line and the exit code is 1; the qBittorrent lines
are still printed. These lines hold names, counts, versions and short tokens only.

`--torrents` prints instead one line per portal torrent (tag `fx`): name, category, save path,
download path, state and progress. It never prints a hash or a credential, and it exits 0 unless
qBittorrent is unreachable.
"""

import argparse
import asyncio
import contextlib
import errno
import os
import stat
import sys
import tempfile
import time
from collections.abc import Sequence

from app.config import Settings, get_settings
from app.download.allowlist import EXCLUDED_FILE_PATTERNS
from app.qbit.bootstrap import parse_version, same_save_path
from app.qbit.client import QbitClient, QbitError
from app.quarantine.rules import in_quarantine
from app.quarantine.runner_client import RunnerClient, RunnerError, RunnerRefused

RECHECK_SECONDS = 2.0
PORTAL_TAG = "fx"
LINK_PROBE_PREFIX = ".fx-doctor-"
NAME_WIDTH = 60

Check = tuple[bool, str]


def line(ok: bool, text: str) -> str:
    return f"{'OK  ' if ok else 'FAIL'} {text}"


async def collect(qbit: QbitClient, settings: Settings) -> list[Check]:
    """Run every check once. A qBittorrent error becomes a single failed check."""
    try:
        version = await qbit.webapi_version()
        prefs = await qbit.get_preferences()
        categories = await qbit.categories()
        plugins = await qbit.search_plugins()
        rows = await qbit.torrents_info()
    except QbitError as exc:
        return [(False, f"qBittorrent not reachable or refused access ({type(exc).__name__})")]

    checks: list[Check] = []
    try:
        version_ok = parse_version(version) >= parse_version(settings.min_webapi_version)
    except QbitError:
        version_ok = False
    checks.append((version_ok, f"WebAPI version {version} (minimum {settings.min_webapi_version})"))

    for name, wanted in settings.category_paths.items():
        stored = categories.get(name)
        stored_path = str(stored.get("savePath", "")) if stored else None
        ok = stored_path is not None and same_save_path(stored_path, wanted)
        shown = stored_path if stored_path is not None else "missing"
        checks.append((ok, f"category {name} -> {shown} (wanted {wanted})"))

    checks.append(
        (bool(prefs.get("auto_tmm_enabled")), f"auto_tmm_enabled {prefs.get('auto_tmm_enabled')}")
    )
    temp_ok = bool(prefs.get("temp_path_enabled")) and prefs.get("temp_path") == (
        settings.incomplete_path
    )
    checks.append(
        (temp_ok, f"temp path {prefs.get('temp_path')} enabled {prefs.get('temp_path_enabled')}")
    )

    stored_patterns = {
        p.strip().casefold() for p in str(prefs.get("excluded_file_names") or "").splitlines()
    }
    present = sum(1 for p in EXCLUDED_FILE_PATTERNS if p.casefold() in stored_patterns)
    exclusion_ok = bool(prefs.get("excluded_file_names_enabled")) and present == len(
        EXCLUDED_FILE_PATTERNS
    )
    exclusion_text = (
        f"exclusion list enabled {prefs.get('excluded_file_names_enabled')}, "
        f"{len(stored_patterns)} patterns, "
        f"{present}/{len(EXCLUDED_FILE_PATTERNS)} required present"
    )
    checks.append((exclusion_ok, exclusion_text))

    checks.append(share_limit_check(prefs, settings))
    checks.extend(plugin_checks(plugins, settings))
    checks.append(legacy_note(rows, settings))
    return checks


def share_limit_check(prefs: dict, settings: Settings) -> Check:
    ratio = prefs.get("max_ratio")
    minutes = prefs.get("max_seeding_time")
    action = prefs.get("max_ratio_act")
    ok = (
        bool(prefs.get("max_ratio_enabled"))
        and bool(prefs.get("max_seeding_time_enabled"))
        and isinstance(ratio, int | float)
        and float(ratio) == settings.share_ratio_limit
        and minutes == settings.share_time_limit_minutes
        and action == 0
    )
    shown_ratio = float(ratio) if isinstance(ratio, int | float) else ratio
    text = (
        f"share limits max_ratio {shown_ratio} max_seeding_time {minutes} max_ratio_act {action} "
        f"(wanted {settings.share_ratio_limit}, {settings.share_time_limit_minutes}, 0 = stop)"
    )
    return ok, text


def plugin_checks(plugins: list[dict], settings: Settings) -> list[Check]:
    """Every configured plugin must be installed. A disabled one is an admin's choice."""
    by_name = {str(plugin.get("name")): plugin for plugin in plugins}
    checks: list[Check] = []
    for name in settings.search_plugin_names:
        plugin = by_name.get(name)
        if plugin is None:
            checks.append((False, f"plugin {name} missing"))
        else:
            checks.append((True, f"plugin {name} installed enabled {plugin.get('enabled')}"))
    return checks


def errno_token(exc: OSError) -> str:
    """The errno name (EXDEV, EACCES, ...), never the message, which can carry a path."""
    return errno.errorcode.get(exc.errno or 0, "OSError")


async def sandbox_checks(runner: RunnerClient) -> list[Check]:
    """The runner's health, then a selftest VM. A host fault is a FAIL line with a token only."""
    try:
        health = await runner.health()
    except RunnerError as exc:
        return [(False, f"sandbox runner not reachable ({runner_token(exc)})")]
    if health.get("kvm") is not True:
        return [(False, "sandbox cannot use /dev/kvm: check KVM_GID and docs/setup.md")]
    checks: list[Check] = [
        (
            health.get("ok") is True,
            (
                f"sandbox runner reachable, kvm {health['kvm']}, "
                f"firecracker {health['firecracker']}, kernel {health['kernel']}, "
                f"ffmpeg {health['ffmpeg']}"
            ),
        )
    ]
    try:
        facts = await runner.selftest()
    except RunnerError as exc:
        checks.append((False, f"sandbox selftest failed ({runner_token(exc)})"))
        return checks
    if facts.status == "ok":
        checks.append((True, "sandbox selftest ok"))
    else:
        checks.append((False, f"sandbox selftest failed ({facts.status})"))
    return checks


async def canary_check(runner: RunnerClient, settings: Settings) -> Check:
    """Does the runner see the same quarantine folder as the backend? (D-58, CR-02)

    Writes a throwaway file into quarantine and asks the runner to probe it. Any contract answer
    about the content (even "probe_failed" for these bytes) proves the two share the folder; a
    refusal, such as "not_found", means a stale or wrong bind mount, where the verifier would
    otherwise wait on every torrent forever.
    """
    path: str | None = None
    try:
        fd, path = tempfile.mkstemp(dir=settings.quarantine_root, prefix=LINK_PROBE_PREFIX)
        with os.fdopen(fd, "wb") as handle:
            handle.write(b"flatflix doctor canary\n")
        os.chmod(path, 0o644)  # the runner reads as another user
        name = os.path.basename(path)
    except OSError as exc:
        if path is not None:
            with contextlib.suppress(OSError):
                os.unlink(path)
        return False, f"sandbox canary file could not be written ({errno_token(exc)})"
    try:
        await runner.probe(name)
    except RunnerRefused as exc:
        return False, (
            f"sandbox does not see the quarantine folder ({runner_token(exc)}): "
            "check the sandbox volume mount and docs/setup.md"
        )
    except RunnerError as exc:
        return False, f"sandbox canary probe failed ({runner_token(exc)})"
    finally:
        with contextlib.suppress(OSError):
            os.unlink(path)
    return True, "sandbox sees the quarantine folder"


def runner_token(exc: RunnerError) -> str:
    token = getattr(exc, "why", None) or getattr(exc, "code", None)
    return token if isinstance(token, str) else "unknown"


def storage_checks(settings: Settings) -> list[Check]:
    """Quarantine, media and rejected on one filesystem, a real hardlink, and the held files."""
    checks = filesystem_checks(settings)
    checks.append(hardlink_check(settings))
    checks.append(held_check(settings))
    return checks


def device_of(path: str) -> int | str:
    """st_dev of a folder, or the errno name when it cannot be read."""
    try:
        return os.stat(path).st_dev
    except OSError as exc:
        return errno_token(exc)


def filesystem_checks(settings: Settings) -> list[Check]:
    quarantine = device_of(settings.quarantine_root)
    media = device_of(settings.media_root)
    rejected = device_of(settings.rejected_root)
    checks: list[Check] = []
    for name, device in (("quarantine", quarantine), ("media", media), ("rejected", rejected)):
        if isinstance(device, str):
            checks.append((False, f"cannot read the {name} folder ({device})"))
    if isinstance(quarantine, int) and isinstance(media, int):
        if quarantine == media:
            checks.append((True, "quarantine and media are on one filesystem"))
        else:
            checks.append(
                (
                    False,
                    (
                        "quarantine and media are on different filesystems (EXDEV): a hardlink "
                        "cannot cross them and the backend never copies; see docs/setup.md"
                    ),
                )
            )
    if isinstance(quarantine, int) and isinstance(rejected, int) and quarantine != rejected:
        checks.append(
            (False, "rejected is on another filesystem than quarantine (EXDEV); see docs/setup.md")
        )
    return checks


def hardlink_check(settings: Settings) -> Check:
    """Link a throwaway file from quarantine into media, as the hand-off does, then remove both."""
    source: str | None = None
    target: str | None = None
    try:
        fd, source = tempfile.mkstemp(dir=settings.quarantine_root, prefix=LINK_PROBE_PREFIX)
        os.close(fd)
        target = os.path.join(settings.media_root, os.path.basename(source))
        os.link(source, target, follow_symlinks=False)
    except OSError as exc:
        return False, f"hardlink quarantine -> media failed ({errno_token(exc)})"
    else:
        return True, "hardlink quarantine -> media works"
    finally:
        for leftover in (target, source):
            if leftover is not None:
                with contextlib.suppress(OSError):
                    os.unlink(leftover)


def held_check(settings: Settings) -> Check:
    """Regular files below rejected/<id>/; the <id>.json sidecars and symlinks are not counted."""
    count = 0
    try:
        with os.scandir(settings.rejected_root) as entries:
            folders = [e.path for e in entries if e.is_dir(follow_symlinks=False)]
        for folder in folders:
            for current, _dirs, files in os.walk(folder, followlinks=False):
                for name in files:
                    with contextlib.suppress(OSError):
                        if stat.S_ISREG(os.lstat(os.path.join(current, name)).st_mode):
                            count += 1
    except OSError:
        count = 0
    return True, (
        f"{count} file(s) held in rejected (purged after {settings.rejected_retention_days} days)"
    )


def legacy_note(rows: list[dict], settings: Settings) -> Check:
    """Film/SerieTV torrents that save outside quarantine are never checked (D-79). Never a FAIL,
    so a box that still holds Phase 1-2 torrents stays green."""
    categories = set(settings.category_paths)
    outside = sum(
        1
        for row in rows
        if row.get("category") in categories
        and not in_quarantine(str(row.get("save_path") or ""), settings.quarantine_root)
    )
    return True, (
        f"note: {outside} Film/SerieTV torrent(s) save outside quarantine and are never checked; "
        "remove them in the qBittorrent WebUI without deleting the files (docs/setup.md)"
    )


def torrent_line(row: dict) -> str:
    """One torrent as `name | category | save | incomplete | state | percent` (no hash)."""
    progress = row.get("progress")
    percent = f"{float(progress) * 100:.1f}%" if isinstance(progress, int | float) else "?"
    fields = [
        str(row.get("name", ""))[:NAME_WIDTH],
        f"category {row.get('category') or '-'}",
        f"save {row.get('save_path') or '-'}",
        f"incomplete {row.get('download_path') or '-'}",
        f"state {row.get('state') or '-'}",
        percent,
    ]
    return " | ".join(fields)


async def list_torrents(settings: Settings) -> int:
    qbit = QbitClient.from_settings(settings)
    try:
        rows = await qbit.torrents_info(tag=PORTAL_TAG)
    except QbitError as exc:
        print(line(False, f"qBittorrent not reachable or refused access ({type(exc).__name__})"))
        return 1
    finally:
        await qbit.aclose()
    for row in rows:
        print(torrent_line(row))
    print(f"{len(rows)} portal torrent(s)")
    return 0


async def run(settings: Settings, wait_seconds: float) -> int:
    qbit = QbitClient.from_settings(settings)
    runner = RunnerClient(settings.sandbox_url, timeout=settings.probe_timeout_seconds)
    try:
        deadline = time.monotonic() + wait_seconds
        while True:
            checks = await collect(qbit, settings)
            sandbox = await sandbox_checks(runner)
            checks.extend(sandbox)
            if all(ok for ok, _ in sandbox):  # the canary boots a VM: only when the runner is up
                checks.append(await canary_check(runner, settings))
            checks.extend(await asyncio.to_thread(storage_checks, settings))
            if all(ok for ok, _ in checks) or time.monotonic() >= deadline:
                break
            await asyncio.sleep(RECHECK_SECONDS)
    finally:
        await runner.aclose()
        await qbit.aclose()
    for ok, text in checks:
        print(line(ok, text))
    return 0 if all(ok for ok, _ in checks) else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.tools.doctor", description=__doc__)
    parser.add_argument(
        "--wait", type=float, default=0, metavar="SECONDS", help="re-check until compliant"
    )
    parser.add_argument(
        "--torrents", action="store_true", help="list the portal torrents instead of the checks"
    )
    args = parser.parse_args(argv)
    if args.torrents:
        return asyncio.run(list_torrents(get_settings()))
    return asyncio.run(run(get_settings(), args.wait))


if __name__ == "__main__":
    sys.exit(main())
