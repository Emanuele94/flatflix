"""Rate limits on the two routes that start work in qBittorrent (SEC-05, D-38).

10 searches and 20 download starts per minute per address; polls and reads are never limited.
A fake clock makes the window boundaries exact.
"""

import httpx
import pytest
from fastapi import FastAPI

from app.auth import LoginThrottle
from app.config import Settings
from tests.conftest import log_in

SEARCH_BODY = {"q": "big buck bunny", "type": "film"}
SEARCH_LIMIT = 10


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def search_clock(app: FastAPI, settings: Settings) -> FakeClock:
    fake = FakeClock()
    app.state.search_throttle = LoginThrottle(
        max_attempts=settings.search_rate_per_minute, window_seconds=60, clock=fake
    )
    return fake


async def post_search(client: httpx.AsyncClient, body: dict | None = None) -> httpx.Response:
    return await client.post("/api/search", json=SEARCH_BODY if body is None else body)


async def fill_search_window(client: httpx.AsyncClient) -> None:
    for _ in range(SEARCH_LIMIT):
        assert (await post_search(client)).status_code != 429


async def test_eleventh_search_in_a_minute_is_429_with_integer_retry_after(
    user_api: httpx.AsyncClient, search_clock: FakeClock
) -> None:
    for _ in range(SEARCH_LIMIT):
        assert (await post_search(user_api)).status_code == 200

    response = await post_search(user_api)

    assert response.status_code == 429
    assert response.json() == {"detail": "too_many_requests"}
    assert response.headers["retry-after"].isdigit()
    assert 1 <= int(response.headers["retry-after"]) <= 60


async def test_search_defaults_come_from_settings(app: FastAPI, settings: Settings) -> None:
    assert settings.search_rate_per_minute == SEARCH_LIMIT
    assert app.state.search_throttle.max_attempts == SEARCH_LIMIT
    assert app.state.search_throttle.window_seconds == 60
    assert app.state.search_throttle.global_max_attempts is None


async def test_polling_a_search_is_never_limited(
    user_api: httpx.AsyncClient, search_clock: FakeClock
) -> None:
    started = await post_search(user_api)
    search_id = started.json()["search_id"]

    for _ in range(60):
        assert (await user_api.get(f"/api/search/{search_id}")).status_code == 200


async def test_a_slot_frees_exactly_sixty_seconds_after_it_was_taken(
    user_api: httpx.AsyncClient, search_clock: FakeClock
) -> None:
    await fill_search_window(user_api)

    search_clock.advance(59.9)
    assert (await post_search(user_api)).status_code == 429

    search_clock.advance(0.1)
    assert (await post_search(user_api)).status_code == 200


async def test_retry_after_rounds_up_to_whole_seconds(
    user_api: httpx.AsyncClient, search_clock: FakeClock
) -> None:
    await fill_search_window(user_api)

    search_clock.advance(0.5)
    response = await post_search(user_api)

    assert response.status_code == 429
    assert response.headers["retry-after"] == "60"


async def test_anonymous_and_malformed_requests_never_use_a_slot(
    app: FastAPI, api: httpx.AsyncClient, search_clock: FakeClock
) -> None:
    for _ in range(12):
        response = await post_search(api)
        assert response.status_code == 401
    await log_in(api)
    for _ in range(12):
        response = await post_search(api, {"q": "x", "type": "film"})
        assert response.status_code == 422
        response = await post_search(api, {"q": "sintel", "type": "movies"})
        assert response.status_code == 422

    for _ in range(SEARCH_LIMIT):
        assert (await post_search(api)).status_code == 200
    assert (await post_search(api)).status_code == 429
