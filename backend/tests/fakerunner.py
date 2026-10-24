"""Fake of the sandbox runner's HTTP service for tests (plan 02.1-02 contract, D-75).

`FakeRunner.transport` is an `httpx.MockTransport`; hand it to `RunnerClient(..., transport=...)`.

- `script(rel_path, *answers)` says what `POST /probe` answers for one path. An answer is a facts
  dict (HTTP 200), an int HTTP status (answered with the contract's error body), or
  `("down", why)` (HTTP 503 `runner_unavailable`). Each call consumes the next answer; the last
  one repeats. A path nobody scripted answers 404 `not_found` unless `answer_unscripted` says
  otherwise, and an unknown route answers 404 `unknown_route`.
- `script_selftest(*answers)` does the same for `POST /selftest`; `health_body` is what
  `GET /health` answers.
- `calls` lists the relative paths probed, in order; `bodies` keeps the decoded request bodies.
- `unreachable = True` makes every request raise `httpx.ConnectError`.

The builders produce the facts dicts the runner answers with, so tests read like the contract.
"""

import json
from collections.abc import Callable

import httpx

FFMPEG = "8.1.2-r0"

ERROR_BODIES: dict[int, dict] = {
    400: {"error": "invalid_path"},
    404: {"error": "not_found"},
    409: {"error": "not_regular_file"},
    503: {"error": "runner_unavailable", "why": "kvm"},
}

HEALTH_OK = {
    "ok": True,
    "kvm": True,
    "firecracker": "1.17.0",
    "kernel": "6.18.58",
    "alpine": "3.22",
    "ffmpeg": FFMPEG,
}


def film_facts(
    duration: float = 6000.0,
    size: int = 4_000_000_000,
    format_name: str = "matroska,webm",
    codec: str = "h264",
    status: str = "ok",
) -> dict:
    """The runner's answer for a normal film: one video stream and one audio stream."""
    return {
        "status": status,
        "reason": None,
        "ffprobe_exit": 0,
        "size_bytes": size,
        "vm_ms": 520,
        "ffmpeg": FFMPEG,
        "format": {
            "format_name": format_name,
            "duration": str(duration),
            "nb_streams": 2,
            "size": str(size),
        },
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": codec,
                "attached_pic": False,
                "width": 1920,
                "height": 1080,
            },
            {
                "index": 1,
                "codec_type": "audio",
                "codec_name": "aac",
                "attached_pic": False,
                "width": None,
                "height": None,
            },
        ],
        "stderr": "",
    }


def failed_facts(status: str = "probe_failed") -> dict:
    """The runner's answer when ffprobe could not read the file (or the VM timed out)."""
    return {
        "status": status,
        "reason": "Invalid data found when processing input" if status == "probe_failed" else None,
        "ffprobe_exit": 1 if status == "probe_failed" else None,
        "size_bytes": 1_669_418,
        "vm_ms": 90_000 if status == "timeout" else 480,
        "ffmpeg": FFMPEG,
        "format": {"format_name": None, "duration": None, "nb_streams": None, "size": None},
        "streams": [],
        "stderr": "",
    }


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.bodies: list[dict] = []
        self.unreachable = False
        self.health_body: dict = dict(HEALTH_OK)
        self._scripts: dict[str, list] = {}
        self._unscripted: list | None = None
        self._selftest: list = [film_facts(duration=60.0, size=1_600_000)]

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def script(self, rel_path: str, *answers) -> None:
        self._scripts[rel_path] = list(answers)

    def answer_unscripted(self, *answers) -> None:
        """What `POST /probe` answers for a path nobody scripted (default: 404 not_found)."""
        self._unscripted = list(answers)

    def script_selftest(self, *answers) -> None:
        self._selftest = list(answers)

    @staticmethod
    def _take(answers: list):
        """The next answer; the last one stays and repeats."""
        return answers.pop(0) if len(answers) > 1 else answers[0]

    @staticmethod
    def _render(answer) -> httpx.Response:
        if isinstance(answer, dict):
            return httpx.Response(200, json=answer)
        if isinstance(answer, int):
            return httpx.Response(answer, json=ERROR_BODIES.get(answer, {"error": "other"}))
        kind, why = answer
        assert kind == "down", answer
        return httpx.Response(503, json={"error": "runner_unavailable", "why": why})

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.unreachable:
            raise httpx.ConnectError("runner is down", request=request)
        route: Callable[[httpx.Request], httpx.Response] | None = {
            ("POST", "/probe"): self._probe,
            ("POST", "/selftest"): self._selftest_route,
            ("GET", "/health"): self._health,
        }.get((request.method, request.url.path))
        if route is None:
            return httpx.Response(404, json={"error": "unknown_route"})
        return route(request)

    def _probe(self, request: httpx.Request) -> httpx.Response:
        try:
            body = json.loads(request.content)
            path = body["path"]
        except (ValueError, KeyError, TypeError):
            return httpx.Response(400, json={"error": "invalid_json"})
        self.bodies.append(body)
        self.calls.append(path)
        answers = self._scripts.get(path, self._unscripted)
        if answers is None:
            return httpx.Response(404, json={"error": "not_found"})
        return self._render(self._take(answers))

    def _selftest_route(self, request: httpx.Request) -> httpx.Response:
        return self._render(self._take(self._selftest))

    def _health(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=self.health_body)
