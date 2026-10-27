"""init-host-dirs.sh sets the folder modes the threat model relies on (D-55, WR-07).

The script is run for real in a temporary copy of the repo layout, with a `.env` written here
(the repo's own `.env` is never read). It exits 1 on a host without /dev/kvm, after the folders
are done, so only the modes are asserted, not the exit status.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(
    subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent,
    ).stdout.strip()
)

OWNER_ONLY = ("jellyfin/config", "jellyfin/config/config", "jellyfin/cache", "data/rejected")
GROUP_WRITABLE = ("jellyfin/scratch", "jellyfin/scratch/Compat", "data/media", "data/quarantine")


def run_script(project: Path) -> None:
    (project / ".env").write_text(f"PUID={os.getuid()}\nPGID={os.getgid()}\nDATA_ROOT=./data\n", encoding="utf-8")
    subprocess.run(["bash", "scripts/init-host-dirs.sh"], cwd=project, capture_output=True, check=False)


def mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


def make_project(tmp_path: Path) -> Path:
    (tmp_path / "scripts").mkdir()
    shutil.copy(ROOT / "scripts" / "init-host-dirs.sh", tmp_path / "scripts" / "init-host-dirs.sh")
    return tmp_path


def test_the_jellyfin_database_folders_and_rejected_are_owner_only(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    run_script(project)

    for name in OWNER_ONLY:
        assert mode(project / name) == 0o700, name
    for name in GROUP_WRITABLE:
        assert mode(project / name) == 0o775, name


def test_an_existing_group_writable_jellyfin_config_is_tightened_on_the_next_run(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    (project / "jellyfin" / "config" / "config").mkdir(parents=True)
    (project / "jellyfin" / "config").chmod(0o775)
    (project / "jellyfin" / "config" / "config").chmod(0o775)

    run_script(project)

    assert mode(project / "jellyfin" / "config") == 0o700
    assert mode(project / "jellyfin" / "config" / "config") == 0o700
