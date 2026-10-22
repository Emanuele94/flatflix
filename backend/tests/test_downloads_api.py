"""The downloads list through the API against FakeQbit (DOWN-04, DOWN-06).

Assertions are about responses and the fake's state; the pure rules live in
test_download_listing.py.
"""

import asyncio
import logging
import re
import time

import httpx
import pytest

from app.download.listing import download_id
from tests.conftest import PORTAL_SECRET_KEY, QBIT_PASS
from tests.fakeqbit import FakeQbit

# The download rig (fake clock, cached result, pipeline) is shared with the pipeline tests.
from tests.test_download_pipeline import BTIH, Rig, clock, rig  # noqa: F401

HASH = "a" * 40
ITEM_KEYS = {"id", "name", "type", "state", "progress", "eta_seconds", "action"}
DAY = 86400


async def test_a_film_torrent_is_listed_with_the_plain_contract(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit
) -> None:
    fake_qbit.add_torrent_row(HASH, category="Film", started=True)

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
    fake_qbit.add_torrent_row("b" * 40, category="Other", started=True)

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


async def test_a_torrent_the_admin_added_by_hand_is_listed(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit
) -> None:
    fake_qbit.add_torrent_row(
        "c" * 40,
        name="Show S01E01 1080p",
        category="SerieTV",
        state="stalledUP",
        progress=1.0,
        completion_on=int(time.time()) - 3600,
    )

    response = await user_api.get("/api/downloads")

    (item,) = response.json()["items"]
    assert item["type"] == "serie"
    assert item["state"] == "ready"
    assert item["progress"] == 100
    assert item["action"] == "remove"
    assert item["name"] == "Show S01E01 1080p"


async def test_a_sub_category_is_not_listed_while_its_parent_is(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit
) -> None:
    fake_qbit.add_torrent_row("d" * 40, category="Film/Extra", started=True)
    fake_qbit.add_torrent_row("e" * 40, category="Film", started=True)

    response = await user_api.get("/api/downloads")

    assert [item["id"] for item in response.json()["items"]] == [
        download_id(PORTAL_SECRET_KEY, "e" * 40)
    ]


async def test_old_finished_downloads_leave_the_list_but_old_active_ones_stay(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit
) -> None:
    now = int(time.time())
    fake_qbit.add_torrent_row(
        "1" * 40, state="uploading", progress=1.0, completion_on=now - 8 * DAY
    )
    fake_qbit.add_torrent_row("2" * 40, started=True, added_on=now - 30 * DAY)

    response = await user_api.get("/api/downloads")

    (item,) = response.json()["items"]
    assert item["id"] == download_id(PORTAL_SECRET_KEY, "2" * 40)
    assert item["state"] == "downloading"
    # The torrent itself is never touched by the window.
    assert "1" * 40 in fake_qbit.torrents
    assert fake_qbit.deleted == []


async def test_an_outage_answers_502_and_keeps_the_session(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit
) -> None:
    fake_qbit.unreachable = True

    response = await user_api.get("/api/downloads")

    assert response.status_code == 502
    assert response.json() == {"detail": "qbit_unreachable"}
    assert (await user_api.get("/api/session")).status_code == 200


async def test_a_refused_login_answers_502_never_401(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit, caplog: pytest.LogCaptureFixture
) -> None:
    fake_qbit.refuse_logins = True
    fake_qbit.expire_sessions()

    with caplog.at_level(logging.WARNING):
        response = await user_api.get("/api/downloads")

    assert response.status_code == 502
    assert response.json() == {"detail": "qbit_refused"}
    assert (await user_api.get("/api/session")).status_code == 200
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("QbitAuthError" in message for message in warnings)
    assert all(QBIT_PASS not in message for message in warnings)


async def test_a_rejected_download_tap_is_listed_with_its_reason_and_name(rig: Rig) -> None:  # noqa: F811
    rig.cache()
    rig.fake.set_metadata(BTIH, [("Movie/setup.exe", 5000), ("Movie/readme.txt", 10)])

    posted = await rig.post()
    job_id = posted.json()["job_id"]
    await asyncio.wait_for(rig.app.state.jobs.task(job_id), 5)
    response = await rig.api.get("/api/downloads")

    assert posted.json()["status"] == "rejected"
    (item,) = response.json()["items"]
    assert item == {
        "id": job_id,
        "name": "Sintel",
        "type": "film",
        "state": "rejected",
        "progress": 0,
        "eta_seconds": None,
        "action": None,
    }
    assert BTIH not in response.text


async def test_a_failed_row_disappears_after_failed_visible_hours(rig: Rig) -> None:  # noqa: F811
    rig.cache()
    rig.fake.set_metadata(BTIH, [("Movie/setup.exe", 5000), ("Movie/readme.txt", 10)])
    job_id = (await rig.post()).json()["job_id"]
    await asyncio.wait_for(rig.app.state.jobs.task(job_id), 5)
    job = rig.app.state.jobs.get(job_id)
    assert job.finished_at is not None

    job.finished_at = time.time() - 24 * 3600
    gone = await rig.api.get("/api/downloads")
    job.finished_at = time.time() - 24 * 3600 + 60
    shown = await rig.api.get("/api/downloads")

    assert gone.json() == {"items": []}
    assert [item["id"] for item in shown.json()["items"]] == [job_id]
