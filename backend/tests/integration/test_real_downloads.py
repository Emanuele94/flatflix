"""The downloads list and cancel against the real pinned qBittorrent (DOWN-04, DOWN-05, SEC-05).

Only locally bencoded synthetic torrents with random info-hashes are added, so they are always
new. Each test deletes (with files) only the hash it added itself, in a `finally`; nothing else in
qBittorrent is read for deletion or touched. A test category is removed only when the test
created it.
"""

import httpx
import pytest

from app.config import Settings
from app.download.listing import download_id
from app.qbit.client import QbitClient
from tests.integration.conftest import credentials
from tests.integration.test_real_qbit import (
    PIECE_LENGTH,
    add_synthetic,
    synthetic_torrent,
    torrent_row,
    wait_until,
)

pytestmark = pytest.mark.integration

PLAIN_STATES = {
    "preparing",
    "downloading",
    "stalled",
    "ready",
    "problem",
    "rejected",
    "unsupported",
    "unavailable",
    "failed",
}
OTHER_CATEGORY = "FlatflixTestOther"  # letters only


def film_payload() -> tuple[bytes, str]:
    return synthetic_torrent([(["Movie.mkv"], 4 * PIECE_LENGTH)])


async def add_and_wait(
    real_settings: Settings, real_qbit: QbitClient, category: str
) -> tuple[str, dict]:
    payload, torrent_hash = film_payload()
    await add_synthetic(
        real_settings, payload, {"category": category, "stopCondition": "MetadataReceived"}
    )

    async def present():
        return await torrent_row(real_qbit, torrent_hash)

    row = await wait_until(present, 20)
    assert row is not None, "qBittorrent never listed the synthetic torrent"
    return torrent_hash, row


async def qbit_post(real_settings: Settings, path: str, data: dict) -> httpx.Response:
    user, password = credentials()
    async with httpx.AsyncClient(base_url=real_settings.qbittorrent_url) as http:
        login = await http.post("/api/v2/auth/login", data={"username": user, "password": password})
        assert login.status_code in (200, 204) and login.text.strip() != "Fails."
        return await http.post(path, data=data)


async def delete_with_files(real_settings: Settings, torrent_hash: str) -> None:
    """Delete only the torrent this test added, and only if it is still there."""
    await qbit_post(
        real_settings,
        "/api/v2/torrents/delete",
        {"hashes": torrent_hash, "deleteFiles": "true"},
    )


async def test_a_film_torrent_is_listed_with_the_fields_the_mapper_reads(
    real_settings: Settings, real_api: httpx.AsyncClient, real_qbit: QbitClient
) -> None:
    torrent_hash = ""
    try:
        torrent_hash, row = await add_and_wait(
            real_settings, real_qbit, real_settings.category_film
        )

        assert isinstance(row["state"], str)
        assert isinstance(row["progress"], int | float) and not isinstance(row["progress"], bool)
        assert isinstance(row["eta"], int)
        assert isinstance(row["completion_on"], int)
        assert isinstance(row["added_on"], int)
        assert isinstance(row["category"], str) and row["category"] == real_settings.category_film
        assert isinstance(row["tags"], str)
        assert isinstance(row["name"], str)

        expected_id = download_id(real_settings.secret_key.get_secret_value(), torrent_hash)
        response = await real_api.get("/api/downloads")
        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"items"}
        # The household's own downloads may be listed too: only this torrent's id is asserted.
        mine = [item for item in body["items"] if item["id"] == expected_id]
        assert len(mine) == 1
        item = mine[0]
        assert item["state"] in PLAIN_STATES
        assert item["type"] == "film"
        assert isinstance(item["progress"], int) and not isinstance(item["progress"], bool)
        assert 0 <= item["progress"] <= 100
    finally:
        if torrent_hash:
            await delete_with_files(real_settings, torrent_hash)


async def test_an_in_progress_torrent_is_cancelled_through_the_portal(
    real_settings: Settings, real_api: httpx.AsyncClient, real_qbit: QbitClient
) -> None:
    torrent_hash = ""
    try:
        torrent_hash, _ = await add_and_wait(real_settings, real_qbit, real_settings.category_film)
        item_id = download_id(real_settings.secret_key.get_secret_value(), torrent_hash)

        deleted = await real_api.delete(f"/api/downloads/{item_id}")
        assert deleted.status_code == 204

        async def gone():
            return await torrent_row(real_qbit, torrent_hash) is None

        assert await wait_until(gone, 10), "the cancelled torrent is still in qBittorrent"

        again = await real_api.delete(f"/api/downloads/{item_id}")
        assert again.status_code == 404
    finally:
        if torrent_hash:
            await delete_with_files(real_settings, torrent_hash)


async def test_a_torrent_outside_film_and_serietv_is_never_listed_or_cancelled(
    real_settings: Settings, real_api: httpx.AsyncClient, real_qbit: QbitClient
) -> None:
    existed_before = OTHER_CATEGORY in await real_qbit.categories()
    torrent_hash = ""
    try:
        torrent_hash, row = await add_and_wait(real_settings, real_qbit, OTHER_CATEGORY)
        assert row["category"] == OTHER_CATEGORY
        item_id = download_id(real_settings.secret_key.get_secret_value(), torrent_hash)

        listed = await real_api.get("/api/downloads")
        assert listed.status_code == 200
        assert item_id not in {item["id"] for item in listed.json()["items"]}

        deleted = await real_api.delete(f"/api/downloads/{item_id}")
        assert deleted.status_code == 404
        assert await torrent_row(real_qbit, torrent_hash) is not None
    finally:
        if torrent_hash:
            await delete_with_files(real_settings, torrent_hash)
        if not existed_before and OTHER_CATEGORY in await real_qbit.categories():
            await qbit_post(
                real_settings, "/api/v2/torrents/removeCategories", {"categories": OTHER_CATEGORY}
            )
