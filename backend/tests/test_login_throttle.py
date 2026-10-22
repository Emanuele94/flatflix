"""Brute-force limit on POST /api/login: 5 attempts per 15 minutes per IP (D-18, T-01-14)."""

import asyncio

import httpx
import pytest
from fastapi import FastAPI

import app.auth as auth_module
from app.auth import LoginThrottle
from tests.conftest import PORTAL_PASSWORD, PORTAL_USER

WRONG = {"username": PORTAL_USER, "password": "definitely not it"}
RIGHT = {"username": PORTAL_USER, "password": PORTAL_PASSWORD}


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(app: FastAPI) -> FakeClock:
    fake = FakeClock()
    app.state.login_throttle = LoginThrottle(max_attempts=5, window_seconds=900, clock=fake)
    return fake


@pytest.fixture
def verify_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Spy on the argon2 check so a throttled request can be shown to skip it."""
    calls: list[str] = []
    real = auth_module._verify_hash

    def spy(stored_hash: str, password: str) -> bool:
        calls.append(password)
        return real(stored_hash, password)

    monkeypatch.setattr(auth_module, "_verify_hash", spy)
    return calls


async def test_sixth_attempt_is_429_with_retry_after_and_skips_argon2(
    api: httpx.AsyncClient, clock: FakeClock, verify_calls: list[str]
) -> None:
    for _ in range(5):
        assert (await api.post("/api/login", json=WRONG)).status_code == 401
    checked_before = len(verify_calls)

    response = await api.post("/api/login", json=WRONG)

    assert response.status_code == 429
    assert response.json() == {"detail": "too_many_attempts"}
    retry_after = int(response.headers["retry-after"])
    assert 1 <= retry_after <= 900
    assert len(verify_calls) == checked_before, "a throttled attempt must not reach argon2"


async def test_correct_password_is_refused_while_throttled(
    api: httpx.AsyncClient, clock: FakeClock
) -> None:
    for _ in range(5):
        await api.post("/api/login", json=WRONG)

    response = await api.post("/api/login", json=RIGHT)

    assert response.status_code == 429
    assert "set-cookie" not in response.headers


async def test_allowed_again_after_the_window(api: httpx.AsyncClient, clock: FakeClock) -> None:
    for _ in range(6):
        await api.post("/api/login", json=WRONG)

    clock.advance(901)
    response = await api.post("/api/login", json=WRONG)

    assert response.status_code == 401


async def test_successful_login_clears_the_counter(
    api: httpx.AsyncClient, clock: FakeClock
) -> None:
    for _ in range(4):
        assert (await api.post("/api/login", json=WRONG)).status_code == 401
    assert (await api.post("/api/login", json=RIGHT)).status_code == 204

    for _ in range(5):
        assert (await api.post("/api/login", json=WRONG)).status_code == 401
    assert (await api.post("/api/login", json=WRONG)).status_code == 429


async def test_another_client_ip_is_unaffected(
    app: FastAPI, api: httpx.AsyncClient, clock: FakeClock
) -> None:
    for _ in range(6):
        await api.post("/api/login", json=WRONG)
    other = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("203.0.113.9", 4000)),
        base_url="http://portal.test",
    )
    async with other:
        response = await other.post("/api/login", json=WRONG)

    assert response.status_code == 401


async def test_ten_concurrent_wrong_logins_let_through_at_most_five(
    api: httpx.AsyncClient, clock: FakeClock, verify_calls: list[str]
) -> None:
    responses = await asyncio.gather(*(api.post("/api/login", json=WRONG) for _ in range(10)))

    codes = sorted(r.status_code for r in responses)
    assert codes.count(401) <= 5
    assert codes.count(401) + codes.count(429) == 10
    assert len(verify_calls) <= 5


def test_throttle_unit_slots_and_retry_seconds() -> None:
    now = [0.0]
    throttle = LoginThrottle(max_attempts=2, window_seconds=100, clock=lambda: now[0])

    assert throttle.try_acquire("a") is None
    now[0] = 10
    assert throttle.try_acquire("a") is None
    wait = throttle.try_acquire("a")
    assert wait == pytest.approx(90)
    assert throttle.try_acquire("b") is None
    throttle.reset("a")
    assert throttle.try_acquire("a") is None


# -- the ceiling across all addresses (WR-07) ----------------------------------------------


def test_guesses_spread_over_many_addresses_hit_the_global_ceiling() -> None:
    now = [0.0]
    throttle = LoginThrottle(
        max_attempts=5, window_seconds=100, clock=lambda: now[0], global_max_attempts=8
    )

    allowed = [throttle.try_acquire(f"client-{n}") is None for n in range(12)]

    assert allowed == [True] * 8 + [False] * 4
    wait = throttle.try_acquire("client-new")
    assert wait == pytest.approx(100)
    now[0] = 101
    assert throttle.try_acquire("client-new") is None  # the window passed


def test_the_global_ceiling_bounds_the_state_it_keeps() -> None:
    throttle = LoginThrottle(max_attempts=5, window_seconds=100, global_max_attempts=8)

    for n in range(1000):
        throttle.try_acquire(f"spoofed-{n}")

    assert len(throttle._attempts) <= 8
    assert len(throttle._all) <= 8


def test_a_correct_login_gives_its_slots_back_to_the_global_ceiling() -> None:
    throttle = LoginThrottle(max_attempts=5, window_seconds=100, global_max_attempts=3)
    for _ in range(3):
        assert throttle.try_acquire("household") is None
    assert throttle.try_acquire("other") is not None  # ceiling reached

    throttle.reset("household")  # the right password was typed

    assert throttle.try_acquire("other") is None


def test_the_per_address_limit_still_applies_below_the_ceiling() -> None:
    throttle = LoginThrottle(max_attempts=2, window_seconds=100, global_max_attempts=50)
    assert throttle.try_acquire("a") is None
    assert throttle.try_acquire("a") is None
    assert throttle.try_acquire("a") is not None
    assert throttle.try_acquire("b") is None


async def test_the_app_wires_the_global_ceiling_from_the_settings(
    app: FastAPI, api: httpx.AsyncClient
) -> None:
    assert (
        app.state.login_throttle.global_max_attempts == app.state.settings.login_global_max_attempts
    )
    assert app.state.settings.login_global_max_attempts > app.state.settings.login_max_attempts
