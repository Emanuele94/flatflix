"""Rate limits on the two routes that start work in qBittorrent (SEC-05, D-38).

10 searches and 20 download starts per minute per address; polls and reads are never limited.
A fake clock makes the window boundaries exact.
"""

import asyncio

import httpx
import pytest
from fastapi import FastAPI

import app.auth as auth_module
from app.config import Settings
from app.throttle import THROTTLE_WINDOW_SECONDS, SlidingWindowThrottle
from tests.conftest import log_in

SEARCH_BODY = {"q": "big buck bunny", "type": "film"}
SEARCH_LIMIT = 10
DOWNLOAD_LIMIT = 20
# Well formed, but no search cached it: the pipeline answers 410 search_expired after the throttle.
DOWNLOAD_BODY = {"result_id": "a1b2c3d4e5f60718", "type": "film"}


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
    app.state.search_throttle = SlidingWindowThrottle(
        max_attempts=settings.search_rate_per_minute,
        window_seconds=THROTTLE_WINDOW_SECONDS,
        clock=fake,
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
    assert app.state.search_throttle.window_seconds == THROTTLE_WINDOW_SECONDS == 60
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


# -- POST /api/download ---------------------------------------------------------------------------


@pytest.fixture
def download_clock(app: FastAPI, settings: Settings) -> FakeClock:
    fake = FakeClock()
    app.state.download_throttle = SlidingWindowThrottle(
        max_attempts=settings.download_rate_per_minute,
        window_seconds=THROTTLE_WINDOW_SECONDS,
        clock=fake,
    )
    return fake


async def post_download(client: httpx.AsyncClient) -> httpx.Response:
    return await client.post("/api/download", json=DOWNLOAD_BODY)


async def test_twenty_first_download_in_a_minute_is_429_with_retry_after(
    user_api: httpx.AsyncClient, download_clock: FakeClock
) -> None:
    for _ in range(DOWNLOAD_LIMIT):
        response = await post_download(user_api)
        assert response.status_code == 410
        assert response.json() == {"detail": "search_expired"}

    response = await post_download(user_api)

    assert response.status_code == 429
    assert response.json() == {"detail": "too_many_requests"}
    assert response.headers["retry-after"] == "60"


async def test_download_defaults_come_from_settings(app: FastAPI, settings: Settings) -> None:
    assert settings.download_rate_per_minute == DOWNLOAD_LIMIT
    assert app.state.download_throttle.max_attempts == DOWNLOAD_LIMIT
    assert app.state.download_throttle.window_seconds == THROTTLE_WINDOW_SECONDS
    assert app.state.download_throttle.global_max_attempts is None


async def test_a_download_slot_frees_exactly_sixty_seconds_after_it_was_taken(
    user_api: httpx.AsyncClient, download_clock: FakeClock
) -> None:
    for _ in range(DOWNLOAD_LIMIT):
        await post_download(user_api)

    download_clock.advance(59.9)
    assert (await post_download(user_api)).status_code == 429

    download_clock.advance(0.1)
    assert (await post_download(user_api)).status_code == 410


async def test_twenty_five_concurrent_downloads_give_exactly_twenty_passes(
    user_api: httpx.AsyncClient, download_clock: FakeClock
) -> None:
    responses = await asyncio.gather(*(post_download(user_api) for _ in range(25)))

    codes = sorted(response.status_code for response in responses)
    assert codes == [410] * DOWNLOAD_LIMIT + [429] * 5


async def test_not_ready_downloads_consume_nothing(
    app: FastAPI, user_api: httpx.AsyncClient, download_clock: FakeClock
) -> None:
    app.state.readiness.state = "starting"
    for _ in range(25):
        response = await post_download(user_api)
        assert response.status_code == 503
        assert response.json() == {"detail": "not_ready"}
    app.state.readiness.mark_ready()

    for _ in range(DOWNLOAD_LIMIT):
        assert (await post_download(user_api)).status_code == 410
    assert (await post_download(user_api)).status_code == 429


async def test_anonymous_and_malformed_downloads_never_use_a_slot(
    api: httpx.AsyncClient, download_clock: FakeClock
) -> None:
    for _ in range(25):
        assert (await post_download(api)).status_code == 401
    await log_in(api)
    for _ in range(25):
        malformed = await api.post("/api/download", json={"result_id": "nope", "type": "film"})
        assert malformed.status_code == 422

    for _ in range(DOWNLOAD_LIMIT):
        assert (await post_download(api)).status_code == 410


async def test_polling_a_job_and_listing_downloads_are_never_limited(
    user_api: httpx.AsyncClient, download_clock: FakeClock
) -> None:
    for _ in range(50):
        assert (await user_api.get("/api/download/0123456789abcdef")).status_code == 404
        assert (await user_api.get("/api/downloads")).status_code == 200


async def test_search_and_download_limits_are_separate(
    user_api: httpx.AsyncClient, search_clock: FakeClock, download_clock: FakeClock
) -> None:
    await fill_search_window(user_api)
    assert (await post_search(user_api)).status_code == 429

    assert (await post_download(user_api)).status_code == 410


async def test_the_session_probe_is_never_limited(
    user_api: httpx.AsyncClient, search_clock: FakeClock
) -> None:
    await fill_search_window(user_api)

    for _ in range(30):
        assert (await user_api.get("/api/session")).status_code == 200


# -- SlidingWindowThrottle ------------------------------------------------------------------------


def test_addresses_are_independent_and_there_is_no_global_ceiling_by_default() -> None:
    clock = FakeClock()
    throttle = SlidingWindowThrottle(max_attempts=2, window_seconds=60, clock=clock)

    assert throttle.try_acquire("203.0.113.7") is None
    assert throttle.try_acquire("203.0.113.7") is None
    assert throttle.try_acquire("203.0.113.7") == pytest.approx(60)
    # Another address is untouched, and many addresses together never trip a global limit.
    for last in range(8, 40):
        assert throttle.try_acquire(f"203.0.113.{last}") is None


def test_reset_forgets_one_address_only() -> None:
    clock = FakeClock()
    throttle = SlidingWindowThrottle(max_attempts=1, window_seconds=60, clock=clock)
    throttle.try_acquire("203.0.113.7")
    throttle.try_acquire("203.0.113.8")

    throttle.reset("203.0.113.7")

    assert throttle.try_acquire("203.0.113.7") is None
    assert throttle.try_acquire("203.0.113.8") is not None


def test_the_login_throttle_is_the_generic_class_under_its_old_name() -> None:
    assert auth_module.LoginThrottle is SlidingWindowThrottle
