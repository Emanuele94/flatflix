"""One throwaway Firecracker microVM per probe (QUAR-02, QUAR-05).

The runner never parses a downloaded file. It stats it, copies at most 511
tail bytes, attaches the file read-only to a VM that has no network device and
reads ffprobe's answer from the serial console. It never judges the facts: the
backend does (D-70).
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SECTOR = 512
FRAME_PREFIX = "FXP"
BOOT_ARGS = (
    "console=ttyS0 reboot=k panic=1 pci=off loglevel=3 8250.nr_uarts=1 root=/dev/vda ro init=/init"
)


class RunnerFault(Exception):
    """The host cannot run a probe right now; never a statement about the file."""

    def __init__(self, why: str) -> None:
        super().__init__(why)
        self.why = why


@dataclass(frozen=True)
class RunnerConfig:
    quarantine_root: Path = Path("/data/quarantine")
    firecracker: Path = Path("/usr/local/bin/firecracker")
    kernel: Path = Path("/opt/fx/vmlinux")
    rootfs: Path = Path("/opt/fx/rootfs.ext4")
    selftest_file: Path = Path("/opt/fx/selftest.mkv")
    versions_file: Path = Path("/etc/fx-versions")
    work_dir: Path = Path("/run/fx")
    kvm_device: Path = Path("/dev/kvm")
    vcpus: int = 1
    memory_mib: int = 256
    timeout_seconds: float = 60
    port: int = 8090
    max_console_bytes: int = 262144
    min_probe_bytes: int = 4096

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> RunnerConfig:
        env = os.environ if environ is None else environ
        d = cls()

        def text(name: str, default: Path) -> Path:
            return Path(env.get(name, str(default)))

        return cls(
            quarantine_root=text("QUARANTINE_ROOT", d.quarantine_root),
            firecracker=text("FX_FIRECRACKER", d.firecracker),
            kernel=text("FX_KERNEL", d.kernel),
            rootfs=text("FX_ROOTFS", d.rootfs),
            selftest_file=text("FX_SELFTEST_FILE", d.selftest_file),
            versions_file=text("FX_VERSIONS_FILE", d.versions_file),
            work_dir=text("FX_WORK_DIR", d.work_dir),
            kvm_device=text("FX_KVM_DEVICE", d.kvm_device),
            vcpus=int(env.get("VM_VCPUS", d.vcpus)),
            memory_mib=int(env.get("VM_MEMORY_MIB", d.memory_mib)),
            timeout_seconds=float(env.get("VM_TIMEOUT_SECONDS", d.timeout_seconds)),
            port=int(env.get("RUNNER_PORT", d.port)),
            max_console_bytes=int(env.get("MAX_CONSOLE_BYTES", d.max_console_bytes)),
            min_probe_bytes=int(env.get("MIN_PROBE_BYTES", d.min_probe_bytes)),
        )


@dataclass(frozen=True)
class Console:
    begin: bool = False
    exit_code: int | None = None
    json_text: str = ""
    stderr_text: str = ""
    ended: bool = False


@dataclass(frozen=True)
class RunResult:
    begin_seen: bool
    exit_code: int | None
    json_text: str
    stderr_text: str
    timed_out: bool
    vm_ms: int
    console: Console = field(default_factory=Console)
    console_len: int = 0


def build_config(
    cfg: RunnerConfig, file_path: Path, tail_path: Path, nonce: str, size: int
) -> dict[str, Any]:
    """The Firecracker config for one probe, as data (never string formatting).

    Exact-bytes design: a virtio disk holds whole 512-byte sectors, so
    Firecracker drops the partial last sector of the file. The runner attaches
    the last ``size % 512`` bytes as a third, 512-byte drive and the guest
    reads both pieces with ffprobe's ``concat:`` of two ``subfile`` ranges
    (RESEARCH Pattern 2). There is deliberately no ``network-interfaces`` key:
    the guest has no NIC. Every drive is read-only.
    """
    return {
        "boot-source": {
            "kernel_image_path": str(cfg.kernel),
            "boot_args": f"{BOOT_ARGS} fxnonce={nonce} fxsize={size}",
        },
        "drives": [
            {
                "drive_id": "rootfs",
                "path_on_host": str(cfg.rootfs),
                "is_root_device": True,
                "is_read_only": True,
            },
            {
                "drive_id": "probe",
                "path_on_host": str(file_path),
                "is_root_device": False,
                "is_read_only": True,
            },
            {
                "drive_id": "tail",
                "path_on_host": str(tail_path),
                "is_root_device": False,
                "is_read_only": True,
            },
        ],
        "machine-config": {
            "vcpu_count": cfg.vcpus,
            "mem_size_mib": cfg.memory_mib,
            "smt": False,
        },
    }


def write_tail(file_path: Path, size: int, dest: Path) -> None:
    """Write the last ``size % 512`` bytes of the file, zero-padded to 512 bytes.

    A file whose size is an exact multiple of 512 gets 512 zero bytes (the
    guest never reads them). The file is opened read-only and at most 511
    bytes are read: the runner never parses downloaded content (QUAR-02).
    """
    remainder = size % SECTOR
    data = b""
    with open(file_path, "rb") as src:
        if remainder:
            src.seek(size - remainder)
            data = src.read(remainder)
    dest.write_bytes(data.ljust(SECTOR, b"\x00"))


STDERR_LIMIT = 1024


def _printable(text: str) -> str:
    """At most STDERR_LIMIT characters, anything outside space..tilde replaced by '?'."""
    return "".join(c if " " <= c <= "~" else "?" for c in text[:STDERR_LIMIT])


def parse_console(text: str, nonce: str) -> Console:
    """Read the framed answer of the guest init out of the serial console.

    The nonce is a trust boundary: it is random per VM and only the guest init
    knows it, so a hostile file cannot print its own BEGIN/EXIT/JSON frame.
    Only lines starting with ``FXP:<nonce>:`` act as markers; every other line
    (kernel messages, forged frames of another nonce) is ignored, or kept as
    block content between the JSON and ERR markers.
    """
    prefix = f"{FRAME_PREFIX}:{nonce}:"
    begin = False
    ended = False
    exit_code: int | None = None
    block: str | None = None
    json_lines: list[str] = []
    err_lines: list[str] = []
    for raw in text.split("\n"):
        line = raw.rstrip("\r")
        if line.startswith(prefix):
            if ended:
                continue
            tag = line[len(prefix) :]
            if tag == "BEGIN":
                begin = True
            elif tag.startswith("EXIT:"):
                try:
                    exit_code = int(tag[5:])
                except ValueError:
                    exit_code = None
            elif tag == "JSON":
                block = "json"
            elif tag == "ERR":
                block = "err"
            elif tag == "END":
                ended = True
                block = None
            continue
        if block == "json":
            json_lines.append(line)
        elif block == "err":
            err_lines.append(line)
    return Console(
        begin=begin,
        exit_code=exit_code,
        json_text="\n".join(json_lines),
        stderr_text=_printable(" ".join(err_lines)),
        ended=ended,
    )


def _read_console(stream_fd: int, cap: int, out: list[bytes]) -> None:
    """Keep the first ``cap`` bytes of the console and drain (discard) the rest.

    Draining matters: a guest that floods the console must not block on a full
    pipe and sit there until the timeout. Nothing past the cap is ever parsed.
    """
    kept = 0
    while True:
        chunk = os.read(stream_fd, 65536)
        if not chunk:
            return
        if kept < cap:
            piece = chunk[: cap - kept]
            out.append(piece)
            kept += len(piece)


def run_vm(cfg: RunnerConfig, config: dict[str, Any], workdir: Path, nonce: str) -> RunResult:
    """Boot one VM with ``firecracker --no-api --config-file`` and read its console."""
    vm_json = workdir / "vm.json"
    fd = os.open(vm_json, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(json.dumps(config))

    started = time.monotonic()
    proc = subprocess.Popen(
        [str(cfg.firecracker), "--no-api", "--config-file", str(vm_json)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    assert proc.stdout is not None
    chunks: list[bytes] = []
    reader = threading.Thread(
        target=_read_console,
        args=(proc.stdout.fileno(), cfg.max_console_bytes, chunks),
        daemon=True,
    )
    reader.start()
    timed_out = False
    try:
        proc.wait(timeout=cfg.timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        proc.kill()
        proc.wait()
    reader.join(timeout=2)
    proc.stdout.close()
    vm_ms = int((time.monotonic() - started) * 1000)

    raw = b"".join(chunks)
    console = parse_console(raw.decode("utf-8", errors="replace"), nonce)
    return RunResult(
        begin_seen=console.begin,
        exit_code=console.exit_code,
        json_text=console.json_text,
        stderr_text=console.stderr_text,
        timed_out=timed_out,
        vm_ms=vm_ms,
        console=console,
        console_len=len(raw),
    )


def facts_from_ffprobe(obj: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Keep only the contract keys of ffprobe's JSON, streams in ffprobe order."""
    raw_format = obj.get("format") if isinstance(obj.get("format"), dict) else {}
    fmt = {
        "format_name": raw_format.get("format_name"),
        "duration": raw_format.get("duration"),
        "nb_streams": raw_format.get("nb_streams"),
        "size": raw_format.get("size"),
    }
    streams: list[dict[str, Any]] = []
    raw_streams = obj.get("streams")
    for item in raw_streams if isinstance(raw_streams, list) else []:
        if not isinstance(item, dict):
            continue
        disposition = item.get("disposition")
        attached = isinstance(disposition, dict) and bool(disposition.get("attached_pic"))
        streams.append(
            {
                "index": item.get("index"),
                "codec_type": item.get("codec_type"),
                "codec_name": item.get("codec_name"),
                "attached_pic": attached,
                "width": item.get("width"),
                "height": item.get("height"),
            }
        )
    return fmt, streams


def _answer(
    status: str, reason: str | None, size: int, result: RunResult | None = None, **facts: Any
) -> dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "ffprobe_exit": result.exit_code if result else None,
        "size_bytes": size,
        "vm_ms": result.vm_ms if result else None,
        "ffmpeg": "",
        "format": facts.get(
            "format",
            {"format_name": None, "duration": None, "nb_streams": None, "size": None},
        ),
        "streams": facts.get("streams", []),
        "stderr": result.stderr_text if result else "",
    }


def probe_file(cfg: RunnerConfig, path: Path) -> dict[str, Any]:
    """Probe one already-resolved file in a fresh VM and report plain facts."""
    size = os.stat(path).st_size
    if size < cfg.min_probe_bytes:
        return _answer("probe_failed", "too_small", size)

    cfg.work_dir.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(dir=cfg.work_dir))
    try:
        nonce = secrets.token_hex(8)
        tail = workdir / "tail.bin"
        write_tail(path, size, tail)
        result = run_vm(cfg, build_config(cfg, path, tail, nonce, size), workdir, nonce)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    if result.exit_code not in (0, None):
        return _answer("probe_failed", "exit", size, result)
    try:
        obj = json.loads(result.json_text)
    except ValueError:
        return _answer("probe_failed", "no_json", size, result)
    if not isinstance(obj, dict):
        return _answer("probe_failed", "no_json", size, result)
    fmt, streams = facts_from_ffprobe(obj)
    return _answer("ok", None, size, result, format=fmt, streams=streams)


__all__ = [
    "Console",
    "RunResult",
    "RunnerConfig",
    "RunnerFault",
    "build_config",
    "facts_from_ffprobe",
    "parse_console",
    "probe_file",
    "run_vm",
    "write_tail",
]
