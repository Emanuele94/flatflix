"""SEC-01 and PUI-02: nothing the browser must not see is in any response.

The app runs against a FakeQbit seeded with canary values. Every API route is called, once
without a session and once with one, and a full search -> poll -> download -> job poll flow is
run. No response body or header may contain a canary, a save path, a magnet link, a qBittorrent
session cookie name or a category key. A failing assertion names the marker, never a value.
"""

import hashlib
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import httpx
import pytest
from fastapi import FastAPI
from fastapi.routing import iter_route_contexts
from pydantic import SecretStr

from app.config import Settings
from app.main import create_app
from app.qbit.client import QbitClient
from tests.conftest import (
    PORTAL_PASS_HASH,
    PORTAL_PASSWORD,
    PORTAL_USER,
    log_in,
    wait_for_bootstrap,
)
from tests.fakeqbit import FakeQbit

MB = 1024 * 1024
CANARY_QBIT_USER = "canary-qbit-user"
CANARY_QBIT_PASS = "LEAK-CANARY-qbit-pass-0001"
CANARY_SECRET_KEY = "LEAK-CANARY-secret-key-0000000000000001"
CANARY_QBIT_HOST = "qbit-canary.internal"
CANARY_FILM_CATEGORY = "CanaryFilmCat"
CANARY_TV_CATEGORY = "CanarySerieCat"
CANARY_DATA_PATH = "/canarydata"
CANARY_FILM_PATH = "/canarydata/quarantine/CanaryFilm"
CANARY_TV_PATH = "/canarydata/quarantine/CanarySerie"
CANARY_INCOMPLETE_PATH = "/canarydata/incomplete"

BTIH = hashlib.sha1(b"leak-canary-film").hexdigest()

# Marker name -> text that must not appear anywhere in a response (case-sensitive).
FORBIDDEN: dict[str, str] = {
    "qbit password": CANARY_QBIT_PASS,
    "secret key": CANARY_SECRET_KEY,
    "qbit host": CANARY_QBIT_HOST,
    "film category name": CANARY_FILM_CATEGORY,
    "serie category name": CANARY_TV_CATEGORY,
    "password hash": "$argon2",
    "media path": "/media/",
    "incomplete path": "/incomplete",
    "data path": CANARY_DATA_PATH,
    "quarantine path": "/quarantine",
    "magnet link": "magnet:",
    "qbit session cookie": "QBT_SID",
    "save_path key": "save_path",
    "content_path key": "content_path",
    "fileUrl key": "fileUrl",
    "descrLink key": "descrLink",
    "category key": '"category"',
    "plugin url": ".example",
    "info hash": BTIH,
}

MAGNET = f"magnet:?xt=urn:btih:{BTIH}&dn=Sintel"
FILM_FILES = [
    ("Sintel/Sintel.mp4", 129241752),
    ("Sintel/poster.jpg", 46115),
    ("Sintel/subs/Sintel.it.srt", 1250),
    ("Sintel/setup.exe", 1000),
]


@dataclass
class Seen:
    """Every response of a test, with the request that produced it."""

    responses: list[tuple[str, httpx.Response]] = field(default_factory=list)

    def record(self, label: str, response: httpx.Response) -> httpx.Response:
        self.responses.append((label, response))
        return response

    def leaks(self) -> list[tuple[str, str]]:
        found = []
        for label, response in self.responses:
            haystack = (
                response.text + "\n" + "\n".join(f"{k}: {v}" for k, v in response.headers.items())
            )
            for marker, text in FORBIDDEN.items():
                if text in haystack:
                    found.append((label, marker))
        return found


def canary_settings() -> Settings:
    return Settings(
        qbittorrent_url=f"http://{CANARY_QBIT_HOST}:8088",
        qbittorrent_user=CANARY_QBIT_USER,
        qbittorrent_pass=SecretStr(CANARY_QBIT_PASS),
        app_user=PORTAL_USER,
        app_pass_hash=SecretStr(PORTAL_PASS_HASH),
        secret_key=SecretStr(CANARY_SECRET_KEY),
        category_film=CANARY_FILM_CATEGORY,
        category_tv=CANARY_TV_CATEGORY,
        data_path=CANARY_DATA_PATH,
        save_path_film=CANARY_FILM_PATH,
        save_path_tv=CANARY_TV_PATH,
        incomplete_path=CANARY_INCOMPLETE_PATH,
    )


def search_row(name: str, seeders: int) -> dict:
    """A qBittorrent search row whose fileUrl is a magnet and descrLink a plugin URL."""
    return {
        "descrLink": f"https://limetorrents.example/desc/{BTIH}",
        "engineName": "limetorrents",
        "fileName": name,
        "fileSize": 1500 * MB,
        "fileUrl": MAGNET,
        "nbLeechers": 2,
        "nbSeeders": seeders,
        "pubDate": 1761083074,
        "siteUrl": "https://limetorrents.example",
    }


@pytest.fixture
def canary_app() -> tuple[FastAPI, FakeQbit]:
    settings = canary_settings()
    fake = FakeQbit(CANARY_QBIT_USER, CANARY_QBIT_PASS)
    fake.script_search([[search_row("Sintel 1080p", 40)]])
    fake.set_metadata(BTIH, FILM_FILES)
    client = QbitClient(
        settings.qbittorrent_url,
        settings.qbittorrent_user,
        settings.qbittorrent_pass,
        transport=fake.transport,
    )
    return create_app(settings, client), fake


@pytest.fixture
async def client(canary_app: tuple[FastAPI, FakeQbit]) -> AsyncIterator[httpx.AsyncClient]:
    app, _ = canary_app
    async with app.router.lifespan_context(app):
        await wait_for_bootstrap(app)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://portal.test") as http:
            yield http


def sweep_targets(app: FastAPI) -> list[tuple[str, str]]:
    """(method, path with dummy params) of every API route, logout last (it ends the session).

    Routes: login, logout, session, health, search x2, download x2, downloads list.
    """
    targets = []
    for context in iter_route_contexts(app.routes):
        path = re.sub(r"\{[^}]+\}", "x", context.path)
        for method in sorted(context.methods - {"HEAD", "OPTIONS"}):
            targets.append((method, path))
    assert len(targets) >= 8, targets  # login, logout, session, health, search x2, download x2
    return sorted(targets, key=lambda target: target == ("POST", "/api/logout"))


async def test_the_canary_detector_catches_a_planted_leak() -> None:
    seen = Seen()
    seen.record(
        "planted", httpx.Response(200, json={"path": CANARY_FILM_PATH}, headers={"x-test": "a"})
    )
    seen.record("planted header", httpx.Response(200, headers={"x-test": CANARY_QBIT_PASS}))

    assert seen.leaks() == [("planted", "media path"), ("planted header", "qbit password")]


async def test_no_response_carries_a_secret_path_magnet_or_category(
    canary_app: tuple[FastAPI, FakeQbit], client: httpx.AsyncClient
) -> None:
    app, fake = canary_app
    seen = Seen()

    # Without a session: every route, a wrong login, health.
    for method, path in sweep_targets(app):
        seen.record(f"anon {method} {path}", await client.request(method, path, json={}))
    seen.record(
        "wrong login",
        await client.post("/api/login", json={"username": PORTAL_USER, "password": "nope-nope"}),
    )

    # With a session: the full household flow.
    seen.record(
        "login",
        await client.post(
            "/api/login", json={"username": PORTAL_USER, "password": PORTAL_PASSWORD}
        ),
    )
    started = seen.record(
        "search start", await client.post("/api/search", json={"q": "sintel", "type": "film"})
    )
    assert started.status_code == 200
    search_id = started.json()["search_id"]

    rows: list[dict] = []
    for _ in range(10):
        snapshot = seen.record("search poll", await client.get(f"/api/search/{search_id}"))
        assert snapshot.status_code == 200
        rows = snapshot.json()["results"]
        if snapshot.json()["done"]:
            break
    assert rows, "the seeded result never reached the snapshot"

    download = seen.record(
        "download",
        await client.post(
            "/api/download", json={"result_id": rows[0]["result_id"], "type": "film"}
        ),
    )
    assert download.status_code == 200
    assert download.json()["status"] == "started"
    job = seen.record("job poll", await client.get(f"/api/download/{download.json()['job_id']}"))
    assert job.status_code == 200
    listing = seen.record("downloads list", await client.get("/api/downloads"))
    assert listing.status_code == 200
    assert listing.json()["items"], "the canary torrent never reached the downloads list"
    # Cancelling it: the opaque id is the only thing the browser sends; the answer is an empty 204.
    cancel = seen.record(
        "downloads cancel",
        await client.delete(f"/api/downloads/{listing.json()['items'][0]['id']}"),
    )
    assert cancel.status_code == 204
    assert fake.deleted, "the cancel never reached qBittorrent"

    # The fake really received the torrent in the canary category: the data was in play.
    (add,) = fake.calls_to("/api/v2/torrents/add")
    assert add.form["category"] == CANARY_FILM_CATEGORY

    # With a session: every route with dummy parameters and an empty or minimal body.
    for method, path in sweep_targets(app):
        seen.record(f"auth {method} {path}", await client.request(method, path, json={}))

    assert len(seen.responses) > 20
    assert seen.leaks() == []


async def test_error_bodies_do_not_echo_the_request_or_internal_state(
    canary_app: tuple[FastAPI, FakeQbit], client: httpx.AsyncClient
) -> None:
    seen = Seen()
    await log_in(client)

    seen.record(
        "bad json",
        await client.post(
            "/api/search", content=b"{not json", headers={"content-type": "application/json"}
        ),
    )
    seen.record(
        "unknown field",
        await client.post(
            "/api/download", json={"result_id": "0123456789abcdef", "type": "film", "url": "x"}
        ),
    )
    seen.record(
        "expired result",
        await client.post("/api/download", json={"result_id": "0123456789abcdef", "type": "film"}),
    )
    seen.record("unknown job", await client.get("/api/download/0000000000000000"))
    seen.record("unknown search", await client.get("/api/search/nope"))

    assert seen.responses[1][1].status_code == 422
    assert seen.leaks() == []
