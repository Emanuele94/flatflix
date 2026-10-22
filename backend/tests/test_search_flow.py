"""Search happy path through the API: start, partial snapshots, filters, sort, key whitelist."""

import hashlib
import json

import httpx

from tests.fakeqbit import FakeQbit

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
