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


# -- cancel and remove (DOWN-05, D-32..D-35) ------------------------------------------------

# (raw state, progress, files go?). The list must offer Cancel exactly where the files go.
CANCEL_TABLE = [
    ("stalledUP", 1.0, False),
    ("stoppedUP", 1.0, False),
    ("moving", 1.0, False),
    ("checkingUP", 1.0, False),
    ("missingFiles", 1.0, False),
    ("error", 1.0, False),
    ("error", 0.3, True),
    ("stalledDL", 0.2, True),
    ("stoppedDL", 0.5, True),
    ("metaDL", 0.0, True),
    ("downloading", 0.4, True),
    ("weird", 0.1, False),
]


@pytest.mark.parametrize(("state", "progress", "deletes"), CANCEL_TABLE)
async def test_the_list_action_and_the_delete_agree_on_what_happens_to_the_files(
    user_api: httpx.AsyncClient,
    fake_qbit: FakeQbit,
    state: str,
    progress: float,
    deletes: bool,
) -> None:
    # qBittorrent reports no completion time (-1) until a torrent first finishes.
    finished_at = int(time.time()) - 60 if progress >= 1 else -1
    fake_qbit.add_torrent_row(
        HASH, category="Film", state=state, progress=progress, completion_on=finished_at
    )
    (item,) = (await user_api.get("/api/downloads")).json()["items"]

    response = await user_api.delete(f"/api/downloads/{item['id']}")

    assert item["action"] == ("cancel" if deletes else "remove")
    assert response.status_code == 204
    assert fake_qbit.deleted == [(HASH, deletes)]
    assert response.content == b""


async def test_an_admin_added_torrent_without_tags_is_cancelled_and_no_tag_is_deleted(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit
) -> None:
    fake_qbit.add_torrent_row(HASH, category="SerieTV", state="stoppedDL", progress=0.5)

    (item,) = (await user_api.get("/api/downloads")).json()["items"]
    response = await user_api.delete(f"/api/downloads/{item['id']}")

    assert response.status_code == 204
    assert fake_qbit.deleted == [(HASH, True)]
    assert fake_qbit.calls_to("/api/v2/torrents/deleteTags") == []


@pytest.mark.parametrize("category", ["Other", "Film/Extra", "film", ""])
async def test_a_torrent_outside_film_and_serie_cannot_be_cancelled(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit, category: str
) -> None:
    fake_qbit.add_torrent_row(HASH, category=category, state="downloading", progress=0.4)
    wanted = download_id(PORTAL_SECRET_KEY, HASH)

    response = await user_api.delete(f"/api/downloads/{wanted}")

    assert response.status_code == 404
    assert response.json() == {"detail": "download_not_found"}
    assert fake_qbit.deleted == []
    assert HASH in fake_qbit.torrents


async def test_an_unknown_id_answers_404_and_deletes_nothing(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit
) -> None:
    fake_qbit.add_torrent_row(HASH, category="Film", state="downloading", progress=0.4)

    response = await user_api.delete("/api/downloads/0000000000000000")

    assert response.status_code == 404
    assert response.json() == {"detail": "download_not_found"}
    assert fake_qbit.deleted == []


@pytest.mark.parametrize("bad_id", ["x", "ABCDEF0123456789", "0123456789abcde", "all"])
async def test_a_malformed_id_answers_422(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit, bad_id: str
) -> None:
    fake_qbit.add_torrent_row(HASH, category="Film", state="downloading", progress=0.4)

    response = await user_api.delete(f"/api/downloads/{bad_id}")

    assert response.status_code == 422
    assert fake_qbit.deleted == []


async def test_a_second_delete_of_the_same_id_answers_404(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit
) -> None:
    fake_qbit.add_torrent_row(HASH, category="Film", state="downloading", progress=0.4)
    wanted = download_id(PORTAL_SECRET_KEY, HASH)

    first = await user_api.delete(f"/api/downloads/{wanted}")
    second = await user_api.delete(f"/api/downloads/{wanted}")

    assert (first.status_code, second.status_code) == (204, 404)
    assert fake_qbit.deleted == [(HASH, True)]


async def test_two_simultaneous_deletes_send_one_torrents_delete(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit
) -> None:
    fake_qbit.add_torrent_row(HASH, category="Film", state="downloading", progress=0.4)
    wanted = download_id(PORTAL_SECRET_KEY, HASH)

    responses = await asyncio.gather(
        user_api.delete(f"/api/downloads/{wanted}"), user_api.delete(f"/api/downloads/{wanted}")
    )

    assert sorted(r.status_code for r in responses) == [204, 404]
    assert fake_qbit.deleted == [(HASH, True)]
    assert len(fake_qbit.calls_to("/api/v2/torrents/delete")) == 1


async def test_a_delete_during_an_outage_answers_502_and_keeps_the_session(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit
) -> None:
    fake_qbit.unreachable = True

    response = await user_api.delete(f"/api/downloads/{download_id(PORTAL_SECRET_KEY, HASH)}")

    assert response.status_code == 502
    assert response.json() == {"detail": "qbit_unreachable"}
    assert (await user_api.get("/api/session")).status_code == 200


async def test_a_delete_with_refused_credentials_answers_502_qbit_refused(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit
) -> None:
    fake_qbit.refuse_logins = True
    fake_qbit.expire_sessions()

    response = await user_api.delete(f"/api/downloads/{download_id(PORTAL_SECRET_KEY, HASH)}")

    assert response.status_code == 502
    assert response.json() == {"detail": "qbit_refused"}
    assert (await user_api.get("/api/session")).status_code == 200


async def test_no_portal_route_answers_401_when_qbit_refuses_the_backend(
    rig: Rig,  # noqa: F811
) -> None:
    rig.cache()
    rig.fake.refuse_logins = True
    rig.fake.expire_sessions()
    wanted = download_id(PORTAL_SECRET_KEY, HASH)

    answers = {
        "list": await rig.api.get("/api/downloads"),
        "delete": await rig.api.delete(f"/api/downloads/{wanted}"),
        "search": await rig.api.post("/api/search", json={"q": "sintel", "type": "film"}),
        "download": await rig.post(),
    }

    assert {name: r.status_code for name, r in answers.items() if r.status_code == 401} == {}
    assert (await rig.api.get("/api/session")).status_code == 200


async def test_delete_is_never_rate_limited(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit
) -> None:
    statuses = {(await user_api.delete(f"/api/downloads/{i:016x}")).status_code for i in range(30)}

    assert statuses == {404}


async def test_delete_needs_a_session(api: httpx.AsyncClient) -> None:
    response = await api.delete("/api/downloads/0123456789abcdef")

    assert response.status_code == 401
