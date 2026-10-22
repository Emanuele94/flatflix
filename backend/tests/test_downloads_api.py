"""The downloads list through the API against FakeQbit (DOWN-04, DOWN-06).

Assertions are about responses and the fake's state; the pure rules live in
test_download_listing.py.
"""

import re
import time

import httpx

from app.download.listing import download_id
from tests.conftest import PORTAL_SECRET_KEY
from tests.fakeqbit import FakeQbit, FakeTorrent

HASH = "a" * 40
ITEM_KEYS = {"id", "name", "type", "state", "progress", "eta_seconds", "action"}


def place(fake: FakeQbit, torrent_hash: str, category: str, started: bool = True) -> None:
    fake.torrents[torrent_hash] = FakeTorrent(
        hash=torrent_hash,
        url="",
        category=category,
        tags=[],
        added_on=time.time(),
        started=started,
    )


async def test_a_film_torrent_is_listed_with_the_plain_contract(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit
) -> None:
    place(fake_qbit, HASH, "Film")

    response = await user_api.get("/api/downloads")

    assert response.status_code == 200
    (item,) = response.json()["items"]
    assert set(item) == ITEM_KEYS
    assert item["id"] == download_id(PORTAL_SECRET_KEY, HASH)
    assert re.fullmatch(r"[0-9a-f]{16}", item["id"])
    assert item["type"] == "film"
    assert item["state"] == "downloading"
    assert item["name"] is None  # the fake names a row by its hash
    assert item["action"] == "cancel"
    assert HASH not in response.text


async def test_a_torrent_in_another_category_is_not_listed(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit
) -> None:
    place(fake_qbit, "b" * 40, "Other")

    response = await user_api.get("/api/downloads")

    assert response.status_code == 200
    assert response.json() == {"items": []}


async def test_no_torrent_gives_an_empty_list(user_api: httpx.AsyncClient) -> None:
    response = await user_api.get("/api/downloads")

    assert response.status_code == 200
    assert response.json() == {"items": []}


async def test_the_list_needs_a_session(api: httpx.AsyncClient) -> None:
    response = await api.get("/api/downloads")

    assert response.status_code == 401
