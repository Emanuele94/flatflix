"""Client address behind the reverse proxy, trusting only the proxy itself (WR-02).

Caddy sets `X-Forwarded-For` to the address it saw. The backend is also on the `qbit` network,
next to the container that runs search plugins and parses untrusted torrents; that container can
call the backend directly and send any `X-Forwarded-For` it likes. Trusting the header from every
peer (`uvicorn --forwarded-allow-ips "*"`) would let it pick a fresh throttle key per login guess.

This middleware replaces uvicorn's proxy handling. The header is honored only when the TCP peer
is one of the configured proxy hosts, looked up through the compose network's DNS (`web` by
default). Any other peer keeps its own address, so a spoofing container is throttled as itself.
Names that do not resolve trust nobody.
"""

import ipaddress
import logging
import time
from collections.abc import Awaitable, Callable, Sequence

from starlette.types import ASGIApp, Receive, Scope, Send

from app import netutil

logger = logging.getLogger(__name__)

Resolver = Callable[[str], Awaitable[list[str]]]

# How long a resolved proxy address is believed, and how soon an unknown peer may trigger a new
# lookup (a recreated proxy container gets a new address; a flood of spoofed peers must not turn
# into a flood of DNS queries).
RESOLVE_TTL_SECONDS = 30.0
RESOLVE_MIN_INTERVAL_SECONDS = 2.0


def _normalize(address: str) -> str | None:
    try:
        return str(ipaddress.ip_address(address.split("%", 1)[0].strip()))
    except ValueError:
        return None


class TrustedProxyHeaders:
    """ASGI middleware: `scope["client"]` becomes the proxy's `X-Forwarded-For` client."""

    def __init__(
        self,
        app: ASGIApp,
        hosts: Sequence[str],
        *,
        resolver: Resolver | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.app = app
        self._hosts = tuple(hosts)
        self._resolver = resolver  # None: app.netutil.resolve_host, looked up at call time
        self._clock = clock
        self._trusted: frozenset[str] = frozenset()
        self._resolved_at: float | None = None

    async def _refresh(self) -> None:
        trusted: set[str] = set()
        for host in self._hosts:
            try:
                addresses = await (self._resolver or netutil.resolve_host)(host)
            except OSError:
                continue  # not resolvable (yet): trust nobody for this name
            trusted.update(a for a in map(_normalize, addresses) if a is not None)
        self._trusted = frozenset(trusted)
        self._resolved_at = self._clock()

    async def _is_trusted(self, peer: str) -> bool:
        now = self._clock()
        age = None if self._resolved_at is None else now - self._resolved_at
        if age is None or age > RESOLVE_TTL_SECONDS:
            await self._refresh()
        elif peer not in self._trusted and age > RESOLVE_MIN_INTERVAL_SECONDS:
            await self._refresh()  # maybe the proxy was recreated with a new address
        return peer in self._trusted

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket") and self._hosts:
            client = scope.get("client")
            peer = _normalize(client[0]) if client else None
            if peer is not None and await self._is_trusted(peer):
                forwarded = self._forwarded_client(scope)
                if forwarded is not None:
                    scope = dict(scope)
                    scope["client"] = (forwarded, 0)
        await self.app(scope, receive, send)

    @staticmethod
    def _forwarded_client(scope: Scope) -> str | None:
        """The right-most `X-Forwarded-For` entry: the one the trusted proxy itself appended."""
        values = [v for k, v in scope.get("headers", ()) if k == b"x-forwarded-for"]
        if not values:
            return None
        entries = b",".join(values).decode("latin-1").split(",")
        return _normalize(entries[-1])
