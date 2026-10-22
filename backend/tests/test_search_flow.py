"""Search happy path through the API: start, partial snapshots, filters, sort, key whitelist."""

import asyncio
import hashlib
import json

import httpx
import pytest
from fastapi import FastAPI

from app.config import Settings
from app.main import create_app
from app.qbit.client import QbitClient
from app.search.filters import DEFAULT_SUSPICIOUS_TERMS
from app.search.service import SearchService
from tests.conftest import log_in
from tests.fakeqbit import FakeQbit, FakeSearch

MB = 1024 * 1024
RESULT_KEYS = {"result_id", "name", "size_human", "seeders", "leechers", "source", "quality"}
SNAPSHOT_KEYS = {"search_id", "done", "timed_out", "results"}


def row(
    name: str,
    seeders: int,
    size_mb: int = 1500,
    engine: str = "limetorrents",
    leechers: int = 1,
    btih: str | None = None,
) -> dict:
    """A search row shaped like qBittorrent 5.2.4 returns it (reserved .example hosts only)."""
    digest = btih or hashlib.sha1(f"{engine}|{name}".encode()).hexdigest()
    return {
        "descrLink": f"https://{engine}.example/desc/{digest}",
        "engineName": engine,
        "fileName": name,
        "fileSize": size_mb * MB,
        "fileUrl": f"magnet:?xt=urn:btih:{digest}&dn=x",
        "nbLeechers": leechers,
        "nbSeeders": seeders,
        "pubDate": 1761083074,
        "siteUrl": f"https://{engine}.example",
    }


async def start(client: httpx.AsyncClient, q: str = "big buck bunny", t: str = "film") -> str:
    response = await client.post("/api/search", json={"q": q, "type": t})
    assert response.status_code == 200, response.text
    assert set(response.json()) == {"search_id"}
    return response.json()["search_id"]


async def poll(client: httpx.AsyncClient, search_id: str) -> dict:
    response = await client.get(f"/api/search/{search_id}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == SNAPSHOT_KEYS
    return body


def search_start_calls(fake: FakeQbit) -> list:
    return fake.calls_to("/api/v2/search/start")


async def test_film_search_sends_movies_category_and_enabled_plugins(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit
) -> None:
    fake_qbit.script_search([[row("Big Buck Bunny 1080p", 40)]])

    await start(user_api, "big buck bunny", "film")

    (call,) = search_start_calls(fake_qbit)
    assert call.form == {"pattern": "big buck bunny", "category": "movies", "plugins": "enabled"}


async def test_serie_search_sends_tv_category_and_enabled_plugins(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit
) -> None:
    fake_qbit.script_search([[row("Show S01E01", 40, size_mb=300)]])

    await start(user_api, "show s01e01", "serie")

    (call,) = search_start_calls(fake_qbit)
    assert call.form == {"pattern": "show s01e01", "category": "tv", "plugins": "enabled"}


async def test_partial_results_arrive_while_running_then_done_when_stopped(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit
) -> None:
    first = row("Sintel 1080p", 12)
    second = row("Sintel 720p", 90, engine="piratebay")
    third = row("Sintel 4K", 30)
    fake_qbit.script_search([[first], [first, second, third]])
    search_id = await start(user_api, "sintel")

    partial = await poll(user_api, search_id)
    full = await poll(user_api, search_id)
    final = await poll(user_api, search_id)

    assert partial["done"] is False
    assert [r["name"] for r in partial["results"]] == ["Sintel 1080p"]
    assert full["done"] is False
    assert [r["name"] for r in full["results"]] == ["Sintel 720p", "Sintel 4K", "Sintel 1080p"]
    assert [r["seeders"] for r in full["results"]] == [90, 30, 12]
    assert final["done"] is True
    assert final["timed_out"] is False
    assert final["results"] == full["results"]


async def test_snapshots_hide_dead_tiny_and_suspicious_rows(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit
) -> None:
    fake_qbit.script_search(
        [
            [
                row("Good Movie 1080p", 25),
                row("Dead Movie", 4),
                row("Tiny Movie", 80, size_mb=499),
                row("Movie Keygen Crack", 200),
                row("Boundary Movie", 5, size_mb=500),
            ]
        ]
    )
    search_id = await start(user_api, "movie")

    body = await poll(user_api, search_id)

    assert [r["name"] for r in body["results"]] == ["Good Movie 1080p", "Boundary Movie"]


async def test_serie_search_uses_the_per_episode_size_floor(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit
) -> None:
    fake_qbit.script_search(
        [[row("Show S01E01", 40, size_mb=150), row("Show S01E02", 40, size_mb=99)]]
    )
    search_id = await start(user_api, "show", "serie")

    body = await poll(user_api, search_id)

    assert [r["name"] for r in body["results"]] == ["Show S01E01"]


async def test_result_rows_carry_exactly_the_whitelisted_keys(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit
) -> None:
    fake_qbit.script_search([[row("Sintel 1080p", 12), row("Sintel", 11, engine="piratebay")]])
    search_id = await start(user_api, "sintel")

    response = await user_api.get(f"/api/search/{search_id}")

    body = response.json()
    assert body["results"]
    for result in body["results"]:
        assert set(result) == RESULT_KEYS
    text = response.text
    for leaked in ("magnet:", ".example", "descrLink", "fileUrl", "siteUrl", "movies", "/media"):
        assert leaked not in text
    assert json.loads(text)["results"][0]["size_human"] == "1.5 GB"
    assert body["results"][0]["source"] == "limetorrents"


async def test_unknown_search_id_is_404(user_api: httpx.AsyncClient) -> None:
    response = await user_api.get("/api/search/does-not-exist")

    assert response.status_code == 404
    assert response.json() == {"detail": "search_not_found"}


# ---- Task 2: timeout, cleanup, limits, cache lifetime --------------------------------------

STOP = "/api/v2/search/stop"
DELETE = "/api/v2/search/delete"
RESULTS = "/api/v2/search/results"


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def service(
    app: FastAPI, api: httpx.AsyncClient, settings: Settings, clock: FakeClock
) -> SearchService:
    """The app's search service rebuilt with a clock the test controls."""
    app.state.search = SearchService(app.state.qbit, settings, clock=clock)
    return app.state.search


def ids(calls: list) -> list[str]:
    return [call.form["id"] for call in calls]


async def test_timeout_without_rows_stops_the_search_and_reports_timed_out(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit, service: SearchService, clock: FakeClock
) -> None:
    fake_qbit.script_search([[]], final_status="Running")
    search_id = await start(user_api, "nothing here")

    early = await poll(user_api, search_id)
    clock.now += 20.0
    on_the_line = await poll(user_api, search_id)
    clock.now += 0.5
    late = await poll(user_api, search_id)

    assert early["done"] is False
    assert on_the_line["done"] is False  # "past" the timeout, not "at" it
    assert late["done"] is True
    assert late["timed_out"] is True
    assert late["results"] == []
    assert len(fake_qbit.calls_to(STOP)) == 1
    assert len(fake_qbit.calls_to(DELETE)) == 1
    assert fake_qbit.searches == {}


async def test_timeout_with_rows_keeps_them_and_is_not_flagged_timed_out(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit, service: SearchService, clock: FakeClock
) -> None:
    fake_qbit.script_search([[row("Sintel 1080p", 30)]], final_status="Running")
    search_id = await start(user_api, "sintel")
    await poll(user_api, search_id)

    clock.now += 21
    late = await poll(user_api, search_id)

    assert late["done"] is True
    assert late["timed_out"] is False
    assert [r["name"] for r in late["results"]] == ["Sintel 1080p"]
    assert len(fake_qbit.calls_to(STOP)) == 1


async def test_rows_that_all_fail_the_filters_count_as_a_timeout(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit, service: SearchService, clock: FakeClock
) -> None:
    fake_qbit.script_search([[row("Tiny", 80, size_mb=10), row("Dead", 1)]], final_status="Running")
    search_id = await start(user_api, "tiny")

    clock.now += 21
    late = await poll(user_api, search_id)

    assert late["done"] is True
    assert late["timed_out"] is True
    assert late["results"] == []


async def test_a_finished_search_is_deleted_once_and_later_polls_do_not_call_qbittorrent(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit, service: SearchService
) -> None:
    fake_qbit.script_search([[row("Sintel 1080p", 30)]])
    search_id = await start(user_api, "sintel")
    await poll(user_api, search_id)
    final = await poll(user_api, search_id)
    assert final["done"] is True
    assert len(fake_qbit.calls_to(DELETE)) == 1
    assert fake_qbit.searches == {}
    calls_before = len(fake_qbit.calls)

    again = await poll(user_api, search_id)
    third = await poll(user_api, search_id)

    assert again == final == third
    assert len(fake_qbit.calls) == calls_before
    assert len(fake_qbit.calls_to(DELETE)) == 1
    assert fake_qbit.calls_to(STOP) == []  # it ended on its own


async def test_two_polls_at_the_end_of_a_search_delete_it_only_once(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit, service: SearchService
) -> None:
    fake_qbit.script_search([[row("Sintel 1080p", 30)]])
    search_id = await start(user_api, "sintel")
    await poll(user_api, search_id)  # the last Running snapshot

    first, second = await asyncio.gather(
        user_api.get(f"/api/search/{search_id}"), user_api.get(f"/api/search/{search_id}")
    )

    assert first.json() == second.json()
    assert first.json()["done"] is True
    assert len(fake_qbit.calls_to(DELETE)) == 1


async def test_a_fourth_concurrent_search_stops_and_deletes_the_oldest(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit, service: SearchService
) -> None:
    fake_qbit.script_search([[row("Sintel 1080p", 30)]], final_status="Running")
    first = await start(user_api, "one")
    second = await start(user_api, "two")
    third = await start(user_api, "three")
    first_qbit_id = str(min(fake_qbit.searches))
    assert len(fake_qbit.searches) == 3
    await poll(user_api, first)  # rows seen before the eviction are kept

    fourth = await start(user_api, "four")

    assert first_qbit_id in ids(fake_qbit.calls_to(STOP))
    assert first_qbit_id in ids(fake_qbit.calls_to(DELETE))
    assert int(first_qbit_id) not in fake_qbit.searches
    assert len(fake_qbit.searches) == 3
    evicted = await poll(user_api, first)
    assert evicted["done"] is True
    assert [r["name"] for r in evicted["results"]] == ["Sintel 1080p"]
    for alive in (second, third, fourth):
        assert (await poll(user_api, alive))["done"] is False


async def test_conflict_from_search_start_cleans_tracked_searches_and_retries_once(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit, service: SearchService
) -> None:
    fake_qbit.script_search([[row("Sintel 1080p", 30)]], final_status="Running")
    fake_qbit.max_searches = 2
    await start(user_api, "one")
    await start(user_api, "two")
    old_ids = sorted(str(i) for i in fake_qbit.searches)

    await start(user_api, "three")

    assert len(fake_qbit.calls_to("/api/v2/search/start")) == 4  # two ok, 409, retry
    assert sorted(ids(fake_qbit.calls_to(STOP))) == old_ids
    assert sorted(ids(fake_qbit.calls_to(DELETE))) == old_ids
    assert len(fake_qbit.searches) == 1


async def test_conflict_caused_by_searches_left_over_from_a_crash_is_swept_then_retried(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit, service: SearchService
) -> None:
    fake_qbit.max_searches = 1
    fake_qbit.searches[1] = FakeSearch(1, [], "Stopped", stopped=True)  # untracked leftover

    await start(user_api, "sintel")

    assert 1 not in fake_qbit.searches
    assert len(fake_qbit.searches) == 1


async def test_a_conflict_that_survives_the_retry_is_a_503_search_unavailable(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit, service: SearchService
) -> None:
    fake_qbit.register(
        "POST", "/api/v2/search/start", lambda r: httpx.Response(409, text="Too many searches")
    )

    response = await user_api.post("/api/search", json={"q": "sintel", "type": "film"})

    assert response.status_code == 503
    assert response.json() == {"detail": "search_unavailable"}
    assert len(fake_qbit.calls_to("/api/v2/search/start")) == 2


async def test_qbittorrent_failing_during_a_poll_is_a_503_and_the_search_survives(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit, service: SearchService
) -> None:
    fake_qbit.script_search([[row("Sintel 1080p", 30)]])
    search_id = await start(user_api, "sintel")
    working = fake_qbit._routes[("GET", RESULTS)]
    fake_qbit.register("GET", RESULTS, lambda r: httpx.Response(500, text="boom"))

    broken = await user_api.get(f"/api/search/{search_id}")
    fake_qbit.register("GET", RESULTS, working)
    recovered = await poll(user_api, search_id)

    assert broken.status_code == 503
    assert broken.json() == {"detail": "search_unavailable"}
    assert [r["name"] for r in recovered["results"]] == ["Sintel 1080p"]


async def test_a_search_qbittorrent_no_longer_knows_ends_with_the_rows_already_seen(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit, service: SearchService
) -> None:
    fake_qbit.script_search([[row("Sintel 1080p", 30)]], final_status="Running")
    search_id = await start(user_api, "sintel")
    await poll(user_api, search_id)
    fake_qbit.searches.clear()  # qBittorrent restarted

    after = await poll(user_api, search_id)

    assert after["done"] is True
    assert after["timed_out"] is False
    assert [r["name"] for r in after["results"]] == ["Sintel 1080p"]


async def test_results_expire_with_the_cache_ttl(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit, service: SearchService, clock: FakeClock
) -> None:
    fake_qbit.script_search([[row("Sintel 1080p", 30)]])
    search_id = await start(user_api, "sintel")
    await poll(user_api, search_id)
    done = await poll(user_api, search_id)
    result_id = done["results"][0]["result_id"]
    assert done["done"] is True

    clock.now += 899
    assert service.get_result(result_id) is not None
    assert (await user_api.get(f"/api/search/{search_id}")).status_code == 200

    clock.now += 2  # 901 s after the search ended
    assert service.get_result(result_id) is None
    gone = await user_api.get(f"/api/search/{search_id}")
    assert gone.status_code == 404
    assert gone.json() == {"detail": "search_not_found"}


async def test_an_abandoned_running_search_is_stopped_and_deleted_after_the_ttl(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit, service: SearchService, clock: FakeClock
) -> None:
    fake_qbit.script_search([[row("Sintel 1080p", 30)]], final_status="Running")
    await start(user_api, "never polled")
    abandoned = str(min(fake_qbit.searches))

    clock.now += 901
    await start(user_api, "next")

    assert abandoned in ids(fake_qbit.calls_to(STOP))
    assert int(abandoned) not in fake_qbit.searches


async def test_get_result_hands_the_server_side_fields_to_the_download_step(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit, service: SearchService
) -> None:
    source = row("Sintel 1080p", 30, engine="piratebay", btih="a" * 40)
    fake_qbit.script_search([[source]])
    search_id = await start(user_api, "sintel", "serie")
    snapshot = await poll(user_api, search_id)

    cached = service.get_result(snapshot["results"][0]["result_id"])

    assert cached is not None
    assert cached.engine == "piratebay"
    assert cached.file_url == source["fileUrl"]
    assert cached.type == "serie"
    assert cached.name == "Sintel 1080p"
    assert service.get_result("0" * 16) is None


async def test_the_row_cap_keeps_the_best_seeded_rows(
    app: FastAPI, api: httpx.AsyncClient, fake_qbit: FakeQbit, settings: Settings
) -> None:
    capped = settings.model_copy(update={"max_results": 2})
    app.state.search = SearchService(app.state.qbit, capped)
    await log_in(api)
    fake_qbit.script_search([[row("A", 10), row("B", 90), row("C", 50)]])

    body = await poll(api, await start(api, "abc"))

    assert [r["name"] for r in body["results"]] == ["B", "C"]


async def test_suspicious_terms_come_from_the_environment_setting(
    app: FastAPI, api: httpx.AsyncClient, fake_qbit: FakeQbit, settings: Settings
) -> None:
    custom = settings.model_copy(update={"suspicious_terms": " Foo , BAR,, "})
    app.state.search = SearchService(app.state.qbit, custom)
    await log_in(api)
    fake_qbit.script_search(
        [[row("Movie FOO 1080p", 30), row("Movie bar", 30), row("Movie keygen", 30)]]
    )

    body = await poll(api, await start(api, "movie"))

    # The configured list replaces the built-in one, so "keygen" is no longer a hidden term.
    assert [r["name"] for r in body["results"]] == ["Movie keygen"]
    assert custom.suspicious_term_list == ("foo", "bar")


@pytest.mark.parametrize("empty", ["", "   ", " , ,"])
def test_an_empty_suspicious_terms_setting_means_the_built_in_list(
    settings: Settings, empty: str
) -> None:
    assert settings.model_copy(update={"suspicious_terms": empty}).suspicious_term_list == (
        DEFAULT_SUSPICIOUS_TERMS
    )


async def test_close_stops_and_deletes_every_active_search(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit, service: SearchService
) -> None:
    fake_qbit.script_search([[row("Sintel 1080p", 30)]], final_status="Running")
    await start(user_api, "one")
    await start(user_api, "two")
    assert len(fake_qbit.searches) == 2

    await service.close()

    assert fake_qbit.searches == {}
    assert len(fake_qbit.calls_to(STOP)) == 2


async def test_leaving_the_app_cleans_up_searches_before_the_qbittorrent_client_closes(
    settings: Settings, fake_qbit: FakeQbit
) -> None:
    client = QbitClient(
        settings.qbittorrent_url,
        settings.qbittorrent_user,
        settings.qbittorrent_pass,
        transport=fake_qbit.transport,
    )
    app = create_app(settings, client)
    fake_qbit.script_search([[row("Sintel 1080p", 30)]], final_status="Running")
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://portal.test") as web:
            await asyncio.sleep(0.05)
            await log_in(web)
            await start(web, "sintel")
            assert len(fake_qbit.searches) == 1

    assert fake_qbit.searches == {}


async def test_no_torrent_endpoint_is_ever_called_by_search_polling_timeout_or_cleanup(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit, service: SearchService, clock: FakeClock
) -> None:
    baseline = len(fake_qbit.calls)  # bootstrap legitimately touches torrents/categories
    fake_qbit.script_search([[row("Sintel 1080p", 30)]])
    finished = await start(user_api, "finishes")
    await poll(user_api, finished)
    await poll(user_api, finished)
    fake_qbit.script_search([[row("Sintel 4K", 30)]], final_status="Running")
    slow = await start(user_api, "times out")
    await poll(user_api, slow)
    clock.now += 21
    await poll(user_api, slow)
    for name in ("a1", "a2", "a3", "a4"):  # forces an eviction
        await start(user_api, name)
    await user_api.get("/api/search/unknown")
    await service.close()

    made = fake_qbit.calls[baseline:]
    assert made
    assert [call.path for call in made if call.path.startswith("/api/v2/torrents/")] == []
    assert [call.path for call in made if call.method == "POST"] != []
    allowed = {"/api/v2/search/start", STOP, DELETE}
    assert {call.path for call in made if call.method == "POST"} <= allowed
