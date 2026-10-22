"""The client address behind Caddy: X-Forwarded-For is believed from the proxy only (WR-02)."""

import httpx
import pytest
from fastapi import FastAPI

from app.auth import LoginThrottle
from app.proxy import TrustedProxyHeaders
from tests.conftest import PORTAL_USER

PROXY = "203.0.113.10"  # documentation addresses only
OTHER = "203.0.113.77"
REAL_CLIENT = "198.51.100.23"
WRONG = {"username": PORTAL_USER, "password": "definitely not it"}


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def make(resolver, clock=None):
    seen: list[tuple] = []

    async def inner(scope, receive, send):
        seen.append(scope["client"])

    kwargs = {"clock": clock} if clock else {}
    return TrustedProxyHeaders(inner, ["web"], resolver=resolver, **kwargs), seen


async def call(middleware, peer: str | None, *headers: bytes) -> None:
    scope = {
        "type": "http",
        "client": (peer, 5000) if peer else None,
        "headers": [(b"x-forwarded-for", h) for h in headers],
    }
    await middleware(scope, None, None)


async def test_the_proxy_peer_gets_its_forwarded_client() -> None:
    async def resolver(host: str) -> list[str]:
        assert host == "web"
        return [PROXY]

    middleware, seen = make(resolver)
    await call(middleware, PROXY, REAL_CLIENT.encode())

    assert seen == [(REAL_CLIENT, 0)]


async def test_only_the_entry_the_proxy_appended_is_used() -> None:
    async def resolver(host: str) -> list[str]:
        return [PROXY]

    middleware, seen = make(resolver)
    # A client-supplied first entry must not win over the one the proxy added last.
    await call(middleware, PROXY, f"{OTHER}, {REAL_CLIENT}".encode())

    assert seen == [(REAL_CLIENT, 0)]


async def test_another_peer_cannot_choose_its_address() -> None:
    async def resolver(host: str) -> list[str]:
        return [PROXY]

    middleware, seen = make(resolver)
    await call(middleware, OTHER, REAL_CLIENT.encode())

    assert seen == [(OTHER, 5000)]


@pytest.mark.parametrize("header", [b"", b"not-an-address", b"999.1.1.1"])
async def test_a_missing_or_malformed_header_keeps_the_peer(header: bytes) -> None:
    async def resolver(host: str) -> list[str]:
        return [PROXY]

    middleware, seen = make(resolver)
    await call(middleware, PROXY, *([header] if header else []))

    assert seen == [(PROXY, 5000)]


async def test_a_proxy_name_that_does_not_resolve_trusts_nobody() -> None:
    async def resolver(host: str) -> list[str]:
        raise OSError("no such host")

    middleware, seen = make(resolver)
    await call(middleware, PROXY, REAL_CLIENT.encode())

    assert seen == [(PROXY, 5000)]


async def test_a_recreated_proxy_with_a_new_address_is_trusted_after_a_lookup() -> None:
    answers = [[PROXY]]

    async def resolver(host: str) -> list[str]:
        return answers[-1]

    clock = Clock()
    middleware, seen = make(resolver, clock)
    await call(middleware, PROXY, REAL_CLIENT.encode())
    answers.append([OTHER])  # the container came back under another address
    clock.now += 5
    await call(middleware, OTHER, REAL_CLIENT.encode())

    assert seen == [(REAL_CLIENT, 0), (REAL_CLIENT, 0)]


async def test_unknown_peers_do_not_cause_a_lookup_per_request() -> None:
    lookups: list[str] = []

    async def resolver(host: str) -> list[str]:
        lookups.append(host)
        return [PROXY]

    middleware, _ = make(resolver, Clock())
    for _ in range(50):
        await call(middleware, OTHER, REAL_CLIENT.encode())

    assert len(lookups) == 1


# -- through the real application ---------------------------------------------------------


def client_for(app: FastAPI, peer: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=(peer, 4000)),
        base_url="http://portal.test",
    )


async def test_a_container_that_spoofs_forwarded_for_is_throttled_as_itself(
    app: FastAPI, api: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def resolver(host: str) -> list[str]:
        return [PROXY]  # the proxy is some other address than the caller

    monkeypatch.setattr("app.netutil.resolve_host", resolver)
    app.state.login_throttle = LoginThrottle(max_attempts=5, window_seconds=900)

    async with client_for(app, OTHER) as spoofer:
        codes = [
            (
                await spoofer.post(
                    "/api/login", json=WRONG, headers={"X-Forwarded-For": f"198.51.100.{n}"}
                )
            ).status_code
            for n in range(1, 8)
        ]

    assert codes == [401] * 5 + [429] * 2


async def test_behind_the_proxy_every_forwarded_client_has_its_own_counter(
    app: FastAPI, api: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def resolver(host: str) -> list[str]:
        return [PROXY]

    monkeypatch.setattr("app.netutil.resolve_host", resolver)
    app.state.login_throttle = LoginThrottle(max_attempts=5, window_seconds=900)

    async with client_for(app, PROXY) as proxy:
        for _ in range(6):
            await proxy.post("/api/login", json=WRONG, headers={"X-Forwarded-For": OTHER})
        blocked = await proxy.post("/api/login", json=WRONG, headers={"X-Forwarded-For": OTHER})
        free = await proxy.post("/api/login", json=WRONG, headers={"X-Forwarded-For": REAL_CLIENT})

    assert blocked.status_code == 429
    assert free.status_code == 401
