"""Opt-in suite that runs real Firecracker microVMs (SANDBOX_TEST=1).

Nothing here runs by default: `pyproject.toml` deselects the `sandbox` marker, and this
directory is skipped unless SANDBOX_TEST=1. It needs the running stack (`docker compose up -d
--build --wait`) on a machine with /dev/kvm, and the host ffmpeg to make the fixtures.

The runner sits on the internal `sandbox` network with no published port, so the tests reach it
through `docker compose exec -T backend` (the backend is on that network). Fixtures are written
under `<DATA_ROOT>/quarantine/.fx-test/` and removed at the end.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

HERE = Path(__file__).parent
REPO_ROOT = HERE.parents[2]
ENV_FILE = REPO_ROOT / ".env"
FIXTURE_FOLDER = ".fx-test"
PROBE_TIMEOUT_SECONDS = 180

# Runs inside the backend container: POST /probe on the sandbox and print the answer as JSON.
_PROBE_SCRIPT = """
import json, sys, urllib.error, urllib.request
req = urllib.request.Request(
    "http://sandbox:8090/probe",
    data=json.dumps({"path": sys.argv[1]}).encode(),
    method="POST",
    headers={"Content-Type": "application/json"},
)
try:
    with urllib.request.urlopen(req, timeout=120) as resp:
        code, body = resp.status, resp.read()
except urllib.error.HTTPError as err:
    code, body = err.code, err.read()
print(json.dumps({"http": code, "body": json.loads(body)}))
"""


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip this directory's tests unless SANDBOX_TEST=1 (the hook sees every item)."""
    if os.environ.get("SANDBOX_TEST") == "1":
        return
    skip = pytest.mark.skip(reason="SANDBOX_TEST=1 is not set")
    for item in items:
        if HERE in Path(str(item.fspath)).parents:
            item.add_marker(skip)


def _env_file_value(key: str) -> str | None:
    if not ENV_FILE.is_file():
        return None
    for line in ENV_FILE.read_text().splitlines():
        name, sep, value = line.partition("=")
        if sep and name.strip() == key:
            return value.strip().strip("'\"")
    return None


def _data_root() -> Path:
    root = Path(_env_file_value("DATA_ROOT") or "./data")
    return root if root.is_absolute() else REPO_ROOT / root


def probe_rel(rel: str) -> tuple[int, dict]:
    """POST /probe through the backend container; returns (HTTP status, JSON body)."""
    done = subprocess.run(
        ["docker", "compose", "exec", "-T", "backend", "python", "-c", _PROBE_SCRIPT, rel],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=PROBE_TIMEOUT_SECONDS,
        check=False,
    )
    if done.returncode != 0:
        pytest.fail(f"docker compose exec failed ({done.returncode}): {done.stderr[-400:]}")
    answer = json.loads(done.stdout.strip().splitlines()[-1])
    return answer["http"], answer["body"]


@pytest.fixture(scope="session")
def fixtures_dir() -> Iterator[Path]:
    """The generated files, in the quarantine folder; removed at the end of the session."""
    if shutil.which("ffmpeg") is None:
        pytest.skip("host ffmpeg missing")
    folder = _data_root() / "quarantine" / FIXTURE_FOLDER
    shutil.rmtree(folder, ignore_errors=True)
    subprocess.run(
        [sys.executable, "-I", str(REPO_ROOT / "scripts" / "make_probe_fixtures.py"), str(folder)],
        check=True,
        capture_output=True,
        timeout=600,
    )
    try:
        yield folder
    finally:
        shutil.rmtree(folder, ignore_errors=True)


@pytest.fixture(scope="session")
def probe(fixtures_dir: Path) -> Callable[[str], tuple[int, dict]]:
    """probe("good.mkv") -> (HTTP status, JSON body) for a fixture file."""

    def run(name: str) -> tuple[int, dict]:
        return probe_rel(f"{FIXTURE_FOLDER}/{name}")

    return run
