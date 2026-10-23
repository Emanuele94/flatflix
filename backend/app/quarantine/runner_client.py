"""Client for the sandbox runner (QUAR-05: one stable interface).

The runner boots a throwaway microVM per file and answers plain facts; it never judges. This client
turns the JSON into `ProbeFacts`. Every failure that is not a contract answer is a `RunnerError`.
"""

from dataclasses import dataclass

import httpx


class RunnerError(Exception):
    """Base class for every sandbox runner access failure."""


class RunnerUnavailable(RunnerError):
    """The runner cannot give an answer right now; the caller waits and retries."""

    def __init__(self, why: str) -> None:
        super().__init__(f"sandbox runner unavailable ({why})")
        self.why = why


class RunnerRefused(RunnerError):
    """The runner answered but refused this path; about the file, not the host (D-58)."""

    def __init__(self, code: str) -> None:
        super().__init__(f"sandbox runner refused the file ({code})")
        self.code = code


@dataclass(frozen=True, slots=True)
class StreamFacts:
    index: int
    codec_type: str | None
    codec_name: str | None
    attached_pic: bool


@dataclass(frozen=True, slots=True)
class ProbeFacts:
    """What ffprobe saw inside the VM. The runner's own size is informational: the verifier
    judges with the size from its own stat."""

    status: str
    reason: str | None
    format_name: str | None
    duration: str | None
    streams: tuple[StreamFacts, ...]
    size_bytes: int
    ffmpeg: str | None

    @classmethod
    def from_json(cls, body: object) -> "ProbeFacts":
        """Accept the contract's shape and nothing else (ValueError); unknown keys are ignored."""
        if not isinstance(body, dict):
            raise ValueError("answer is not an object")  # noqa: TRY004 - the contract says ValueError
        status = body.get("status")
        if status not in ("ok", "probe_failed", "timeout"):
            raise ValueError("unknown status")
        size_bytes = body.get("size_bytes")
        if not _is_int(size_bytes) or size_bytes < 0:
            raise ValueError("bad size_bytes")
        fmt = body.get("format")
        if fmt is None:
            fmt = {}
        if not isinstance(fmt, dict):
            raise ValueError("bad format")  # noqa: TRY004 - the contract says ValueError
        raw_streams = body.get("streams", [])
        if not isinstance(raw_streams, list):
            raise ValueError("bad streams")  # noqa: TRY004 - the contract says ValueError
        return cls(
            status=status,
            reason=_opt_str(body.get("reason")),
            format_name=_opt_str(fmt.get("format_name")),
            duration=_opt_str(fmt.get("duration")),
            streams=tuple(_stream(raw) for raw in raw_streams),
            size_bytes=size_bytes,
            ffmpeg=_opt_str(body.get("ffmpeg")),
        )


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _opt_str(value: object) -> str | None:
    if value is None or isinstance(value, str):
        return value
    raise ValueError("expected a string or null")


def _stream(raw: object) -> StreamFacts:
    if not isinstance(raw, dict):
        raise ValueError("bad stream")  # noqa: TRY004 - the contract says ValueError
    index = raw.get("index")
    attached_pic = raw.get("attached_pic", False)
    if not _is_int(index) or not isinstance(attached_pic, bool):
        raise ValueError("bad stream")
    return StreamFacts(
        index=index,
        codec_type=_opt_str(raw.get("codec_type")),
        codec_name=_opt_str(raw.get("codec_name")),
        attached_pic=attached_pic,
    )


class RunnerClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 90.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            transport=transport,
            timeout=timeout,
            follow_redirects=False,
        )

    def __repr__(self) -> str:
        return f"RunnerClient(base_url={self._base_url!r})"

    async def _send(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            return await self._http.request(method, path, **kwargs)
        except httpx.TransportError as exc:
            raise RunnerUnavailable("unreachable") from exc

    async def probe(self, rel_path: str) -> ProbeFacts:
        """Probe one file, given relative to the quarantine root."""
        response = await self._send("POST", "/probe", json={"path": rel_path})
        return ProbeFacts.from_json(response.json())

    async def aclose(self) -> None:
        await self._http.aclose()
