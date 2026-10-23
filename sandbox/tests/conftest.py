"""Fixtures for the sandbox runner tests: a stub `firecracker` and a live server.

No KVM and no Docker are needed. The stub reads the same `--config-file` the
real Firecracker would, records it, and prints the guest console protocol
(RESEARCH Pattern 3) framed with the nonce it finds on the kernel command line.
"""

from __future__ import annotations

import dataclasses
import json
import os
import sys
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runner.server import make_server
from runner.vm import RunnerConfig

STUB_SOURCE = r"""
import json
import os
import sys
import time

args = sys.argv[1:]
config = json.load(open(args[args.index("--config-file") + 1]))
boot_args = dict(
    part.split("=", 1) for part in config["boot-source"]["boot_args"].split() if "=" in part
)
nonce = boot_args["fxnonce"]
size = int(boot_args["fxsize"])
record_dir = os.environ["STUB_RECORD_DIR"]
mode = os.environ.get("STUB_MODE", "ok")

n = 0
while True:
    try:
        fd = os.open(os.path.join(record_dir, "%d.json" % n), os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        break
    except FileExistsError:
        n += 1
with os.fdopen(fd, "w") as handle:
    json.dump(config, handle)

FFPROBE = {
    "format": {
        "filename": "concat:subfile,,start,0,end,1,,:/dev/vdb",
        "format_name": "matroska,webm",
        "duration": "60.023152",
        "nb_streams": 2,
        "size": str(size),
        "tags": {"title": "ignored"},
    },
    "streams": [
        {
            "index": 0, "codec_type": "video", "codec_name": "h264", "width": 320,
            "height": 240, "disposition": {"default": 1, "attached_pic": 0},
            "tags": {"language": "eng"},
        },
        {
            "index": 1, "codec_type": "audio", "codec_name": "aac",
            "disposition": {"default": 1, "attached_pic": 0},
        },
    ],
}


def say(line):
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def frame(rc, json_text, err=""):
    say("FXP:%s:EXIT:%d" % (nonce, rc))
    say("FXP:%s:JSON" % nonce)
    if json_text:
        say(json_text)
    say("FXP:%s:ERR" % nonce)
    if err:
        say(err)
    say("FXP:%s:END" % nonce)


say("[    0.000000] Linux version stub")
say("FXP:%s:BEGIN" % nonce)
if mode == "ok":
    frame(0, json.dumps(FFPROBE, indent=2))
"""


@dataclass
class StubFirecracker:
    path: Path
    records: Path

    def configs(self) -> list[dict[str, Any]]:
        files = sorted(self.records.glob("*.json"), key=lambda p: int(p.stem))
        return [json.loads(p.read_text()) for p in files]


@pytest.fixture
def stub_firecracker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> StubFirecracker:
    records = tmp_path / "records"
    records.mkdir()
    script = tmp_path / "bin" / "firecracker"
    script.parent.mkdir()
    script.write_text(f"#!{sys.executable}\n{STUB_SOURCE}")
    script.chmod(0o755)
    monkeypatch.setenv("STUB_RECORD_DIR", str(records))
    monkeypatch.delenv("STUB_MODE", raising=False)
    return StubFirecracker(script, records)


@pytest.fixture
def quarantine(tmp_path: Path) -> Path:
    root = tmp_path / "quarantine"
    movie = root / "Film" / "Movie" / "movie.mkv"
    movie.parent.mkdir(parents=True)
    with open(movie, "wb") as handle:
        handle.truncate(2 * 1024 * 1024)
    return root


@dataclass
class RunnerHandle:
    base: str
    cfg: RunnerConfig
    quarantine: Path

    def request(
        self, method: str, route: str, body: Any = None, raw: bytes | None = None
    ) -> tuple[int, dict[str, Any]]:
        data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
        req = urllib.request.Request(self.base + route, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read())

    def probe(self, path: Any) -> tuple[int, dict[str, Any]]:
        return self.request("POST", "/probe", {"path": path})


@pytest.fixture
def make_runner(
    tmp_path: Path, stub_firecracker: StubFirecracker, quarantine: Path
) -> Callable[..., RunnerHandle]:
    servers: list[Any] = []

    def factory(**overrides: Any) -> RunnerHandle:
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir(exist_ok=True)
        for name in ("vmlinux", "rootfs.ext4", "selftest.mkv", "kvm"):
            target = artifacts / name
            if not target.exists():
                target.write_bytes(b"x" * 8192 if name == "selftest.mkv" else b"x")
        versions = artifacts / "fx-versions"
        versions.write_text("firecracker=1.17.0\nkernel=6.18.58\nalpine=3.24.3\nffmpeg=8.1.2-r0\n")
        cfg = RunnerConfig(
            quarantine_root=quarantine,
            firecracker=stub_firecracker.path,
            kernel=artifacts / "vmlinux",
            rootfs=artifacts / "rootfs.ext4",
            selftest_file=artifacts / "selftest.mkv",
            versions_file=versions,
            work_dir=tmp_path / "work",
            kvm_device=artifacts / "kvm",
            timeout_seconds=5,
        )
        cfg = dataclasses.replace(cfg, **overrides)
        server = make_server(cfg, "127.0.0.1", 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append(server)
        port = server.server_address[1]
        return RunnerHandle(f"http://127.0.0.1:{port}", cfg, quarantine)

    yield factory
    for server in servers:
        server.shutdown()
        server.server_close()


@pytest.fixture
def runner(make_runner: Callable[..., RunnerHandle]) -> RunnerHandle:
    return make_runner()


def running_as_root() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0
