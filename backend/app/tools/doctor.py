"""Admin diagnostic: is qBittorrent configured the way the portal needs?

Run inside the backend container:

    docker compose exec -T backend python -m app.tools.doctor --wait 90

Prints one line per check (names, paths, counts and versions only, never credentials) and
exits 0 when every check passes, 1 otherwise. `--wait SECONDS` re-checks every 2 s until all
checks pass or the time runs out, which covers the first start while bootstrap is running.
"""

import argparse
import asyncio
import sys
import time
from collections.abc import Sequence

from app.config import Settings, get_settings
from app.download.allowlist import EXCLUDED_FILE_PATTERNS
from app.qbit.bootstrap import parse_version, same_save_path
from app.qbit.client import QbitClient, QbitError

RECHECK_SECONDS = 2.0

Check = tuple[bool, str]


def line(ok: bool, text: str) -> str:
    return f"{'OK  ' if ok else 'FAIL'} {text}"


async def collect(qbit: QbitClient, settings: Settings) -> list[Check]:
    """Run every check once. A qBittorrent error becomes a single failed check."""
    try:
        version = await qbit.webapi_version()
        prefs = await qbit.get_preferences()
        categories = await qbit.categories()
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
    return checks


async def run(settings: Settings, wait_seconds: float) -> int:
    qbit = QbitClient.from_settings(settings)
    try:
        deadline = time.monotonic() + wait_seconds
        while True:
            checks = await collect(qbit, settings)
            if all(ok for ok, _ in checks) or time.monotonic() >= deadline:
                break
            await asyncio.sleep(RECHECK_SECONDS)
    finally:
        await qbit.aclose()
    for ok, text in checks:
        print(line(ok, text))
    return 0 if all(ok for ok, _ in checks) else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.tools.doctor", description=__doc__)
    parser.add_argument(
        "--wait", type=float, default=0, metavar="SECONDS", help="re-check until compliant"
    )
    args = parser.parse_args(argv)
    return asyncio.run(run(get_settings(), args.wait))


if __name__ == "__main__":
    sys.exit(main())
