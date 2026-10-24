"""HTTP front of the sandbox runner (QUAR-05: one stable interface).

POST /probe takes a path relative to the quarantine root and answers plain
facts about the file. The runner never judges them (D-70). One lock makes
sure only one VM runs at a time (D-52). The server never starts a process
itself: only runner.vm does.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from runner.paths import InvalidPath, NotFound, NotRegular, resolve_probe_path
from runner.vm import RunnerConfig, RunnerFault, check_kvm, probe_file

VM_LOCK = threading.Lock()
MAX_BODY_BYTES = 4096


def read_versions(path: Path) -> dict[str, str]:
    """Parse ``key=value`` lines; a missing file yields no versions."""
    versions: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return versions
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip():
            versions[key.strip()] = value.strip()
    return versions


class RunnerServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], cfg: RunnerConfig) -> None:
        super().__init__(address, Handler)
        self.cfg = cfg


class Handler(BaseHTTPRequestHandler):
    server: RunnerServer  # type: ignore[assignment]
    protocol_version = "HTTP/1.1"
    _vm_ms: int | None = None

    # -- logging: method, URL path, status and vm_ms only, never a file name --
    def log_request(self, code: Any = "-", size: Any = "-") -> None:
        sys.stderr.write(
            f"{self.command} {self.path.split('?', 1)[0]} {code} vm_ms={self._vm_ms}\n"
        )

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write("runner: " + (format % args) + "\n")

    # -- plumbing --
    def _send(self, status: int, body: dict[str, Any]) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _read_json_body(self) -> dict[str, Any] | None:
        """The request body as a JSON object, or None when it is unusable."""
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self.close_connection = True
            return None
        if length < 0 or length > MAX_BODY_BYTES:
            self.close_connection = True
            return None
        try:
            body = json.loads(self.rfile.read(length))
        except ValueError:
            return None
        return body if isinstance(body, dict) else None

    def _probe_answer(self, path: Path, min_bytes: int | None = None) -> tuple[int, dict[str, Any]]:
        """Run one probe under the VM lock; a host fault is a 503, never a verdict."""
        try:
            with VM_LOCK:
                answer = probe_file(self.server.cfg, path, min_bytes)
        except RunnerFault as fault:
            return 503, {"error": "runner_unavailable", "why": fault.why}
        answer["ffmpeg"] = read_versions(self.server.cfg.versions_file).get("ffmpeg", "unknown")
        self._vm_ms = answer["vm_ms"]
        return 200, answer

    # -- routes --
    def do_POST(self) -> None:
        route = self.path.split("?", 1)[0]
        if route == "/selftest":
            self._selftest()
            return
        if route != "/probe":
            # Not the file-not-found answer: the backend must tell "wrong route" from "no such file".
            self._send(404, {"error": "unknown_route"})
            return
        body = self._read_json_body()
        rel = body.get("path") if body is not None else None
        if not isinstance(rel, str):
            self._send(400, {"error": "invalid_json"})
            return
        try:
            real = resolve_probe_path(self.server.cfg.quarantine_root, rel)
        except InvalidPath:
            self._send(400, {"error": "invalid_path"})
            return
        except NotFound:
            self._send(404, {"error": "not_found"})
            return
        except NotRegular:
            self._send(409, {"error": "not_regular_file"})
            return
        except PermissionError:
            self._send(503, {"error": "runner_unavailable", "why": "permission"})
            return
        self._send(*self._probe_answer(real))

    def _selftest(self) -> None:
        """Probe the clip baked into the image: not under the quarantine root, so no resolving."""
        self._read_json_body()  # the body, if any, is ignored but must not stay on the wire
        clip = self.server.cfg.selftest_file
        if not (clip.is_file() and os.access(clip, os.R_OK)):
            self._send(503, {"error": "runner_unavailable", "why": "artifacts"})
            return
        self._send(*self._probe_answer(clip, min_bytes=1))

    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] != "/health":
            self._send(404, {"error": "unknown_route"})
            return
        cfg = self.server.cfg
        versions = read_versions(cfg.versions_file)
        try:
            check_kvm(cfg)
            kvm = True
        except RunnerFault:
            kvm = False
        self._send(
            200,
            {
                "ok": True,
                "kvm": kvm,
                **{
                    k: versions.get(k, "unknown")
                    for k in ("firecracker", "kernel", "alpine", "ffmpeg")
                },
            },
        )


def make_server(cfg: RunnerConfig, host: str, port: int) -> RunnerServer:
    return RunnerServer((host, port), cfg)


def main() -> None:
    cfg = RunnerConfig.from_env()
    server = make_server(cfg, "0.0.0.0", cfg.port)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
