"""Cancel and remove through the API against FakeQbit (DOWN-05, DOWN-06, D-32..D-35).

The browser names a download by its opaque id only; these tests watch what the backend sent to
qBittorrent (`fake.deleted`) and what the list shows afterwards.
"""

import asyncio
import time

import httpx
from fastapi import FastAPI

from app.download.jobs import Job, JobState
from app.download.listing import download_id
from tests.conftest import PORTAL_SECRET_KEY
from tests.fakeqbit import FakeQbit

# The download rig (fake clock, cached result, pipeline) is shared with the pipeline tests.
from tests.test_download_pipeline import (  # noqa: F401
    BTIH,
    DELETE,
    PAGE_URL,
    RESULT_ID,
    SINTEL_FILES,
    Rig,
    clock,
    rig,
)

HASH = "a" * 40


async def test_cancelling_an_in_progress_download_deletes_the_torrent_and_its_files(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit
) -> None:
    fake_qbit.add_torrent_row(HASH, category="Film", state="downloading", progress=0.4)
    (item,) = (await user_api.get("/api/downloads")).json()["items"]

    response = await user_api.delete(f"/api/downloads/{item['id']}")

    assert response.status_code == 204
    assert fake_qbit.deleted == [(HASH, True)]
    assert (await user_api.get("/api/downloads")).json() == {"items": []}


# -- cancelling a Preparing download (research Pitfalls 1 and 2) ----------------------------


def slow_rig(rig: Rig) -> None:  # noqa: F811
    """A POST answers `preparing` after 50 ms while the job keeps waiting on the fake clock."""
    rig.app.state.settings = rig.app.state.settings.model_copy(
        update={"download_wait_seconds": 0.05}
    )

    async def slow_sleep(seconds: float) -> None:
        rig.clock.now += seconds
        await asyncio.sleep(0.01)

    rig.use_sleep(slow_sleep)


async def settle(rig: Rig, seconds: float = 0.1) -> None:  # noqa: F811
    """Let background tasks run on the real clock for a moment."""
    await asyncio.sleep(seconds)


async def test_cancelling_a_preparing_download_leaves_no_ghost_row(rig: Rig) -> None:  # noqa: F811
    slow_rig(rig)
    rig.cache()  # a magnet that never gets its metadata
    posted = await rig.post()
    job_id = posted.json()["job_id"]
    jobs = rig.app.state.jobs
    seen_at_delete: list[tuple[bool, JobState]] = []
    real_delete = rig.fake._torrents_delete

    def spy(request: httpx.Request) -> httpx.Response:
        seen_at_delete.append((jobs.task(job_id).done(), jobs.get(job_id).state))
        return real_delete(request)

    rig.fake.register("POST", DELETE, spy)
    (item,) = (await rig.api.get("/api/downloads")).json()["items"]
    assert item["state"] == "preparing"

    response = await rig.api.delete(f"/api/downloads/{item['id']}")

    assert posted.json()["status"] == "preparing"
    assert response.status_code == 204
    assert seen_at_delete == [(True, JobState.CANCELLED)]
    assert rig.fake.deleted == [(BTIH, True)]
    rig.clock.now += rig.app.state.settings.metadata_timeout + 60
    await settle(rig)
    assert (await rig.api.get("/api/downloads")).json() == {"items": []}
    assert (await rig.api.get(f"/api/download/{job_id}")).json() == {
        "status": "cancelled",
        "job_id": job_id,
    }
    assert rig.fake.deleted == [(BTIH, True)]


async def test_a_cancelled_result_can_be_downloaded_again_at_once(rig: Rig) -> None:  # noqa: F811
    rig.cache()
    rig.fake.set_metadata(BTIH, SINTEL_FILES)
    first = (await rig.post()).json()
    assert first["status"] == "started"
    (item,) = (await rig.api.get("/api/downloads")).json()["items"]

    assert (await rig.api.delete(f"/api/downloads/{item['id']}")).status_code == 204
    second = await rig.api.post("/api/download", json={"result_id": RESULT_ID, "type": "film"})

    assert second.json()["status"] == "started"
    assert second.json()["job_id"] != first["job_id"]
    assert len(rig.adds()) == 2
    assert BTIH in rig.fake.torrents


async def test_a_torrent_less_preparing_job_is_cancelled_and_a_late_torrent_is_swept(
    rig: Rig,  # noqa: F811
) -> None:
    slow_rig(rig)
    rig.cache(url=PAGE_URL, engine="limetorrents")
    page_hash = FakeQbit.hash_for(PAGE_URL)
    rig.fake.downloader_delay_calls = 10**6  # the torrent does not show up yet
    rig.fake.set_metadata(page_hash, SINTEL_FILES)
    posted = (await rig.post()).json()
    job_id = posted["job_id"]
    assert posted["status"] == "preparing"
    (item,) = (await rig.api.get("/api/downloads")).json()["items"]
    assert item["id"] == job_id
    assert (item["state"], item["action"]) == ("preparing", "cancel")

    response = await rig.api.delete(f"/api/downloads/{job_id}")

    assert response.status_code == 204
    assert rig.app.state.jobs.get(job_id).state is JobState.CANCELLED
    assert (await rig.api.get("/api/downloads")).json() == {"items": []}
    assert rig.fake.deleted == []
    # The torrent shows up later under the job's tag: it is never listed and is swept away.
    rig.fake._pending_downloads[0][0] = 0
    for _ in range(50):
        if rig.fake.deleted:
            break
        await settle(rig, 0.02)
    assert rig.fake.deleted == [(page_hash, True)]
    assert (await rig.api.get("/api/downloads")).json() == {"items": []}
    # After created_at + METADATA_TIMEOUT the sweep has ended: it asks qBittorrent no more.
    rig.clock.now += rig.app.state.settings.metadata_timeout + 60
    await settle(rig)
    lookups = len(rig.fake.calls_to("/api/v2/torrents/info"))
    await settle(rig)
    assert len(rig.fake.calls_to("/api/v2/torrents/info")) == lookups
    assert (await rig.api.delete(f"/api/downloads/{job_id}")).status_code == 404


async def test_a_torrent_that_a_cancelled_job_added_before_the_cancel_is_deleted_at_once(
    rig: Rig,  # noqa: F811
) -> None:
    slow_rig(rig)
    rig.cache(url=PAGE_URL, engine="limetorrents")
    page_hash = FakeQbit.hash_for(PAGE_URL)
    rig.fake.downloader_delay_calls = 10**6
    job_id = (await rig.post()).json()["job_id"]
    rig.fake._pending_downloads[0][0] = 0  # it appears with the very next lookup

    response = await rig.api.delete(f"/api/downloads/{job_id}")

    assert response.status_code == 204
    assert rig.fake.deleted == [(page_hash, True)]


async def test_deleting_the_id_of_a_job_that_already_ended_answers_404(rig: Rig) -> None:  # noqa: F811
    rig.cache()
    rig.fake.set_metadata(BTIH, [("Movie/setup.exe", 5000), ("Movie/readme.txt", 10)])
    posted = (await rig.post()).json()
    assert posted["status"] == "rejected"

    response = await rig.api.delete(f"/api/downloads/{posted['job_id']}")

    assert response.status_code == 404
    assert response.json() == {"detail": "download_not_found"}


async def test_shutdown_stops_a_running_sweep_without_errors(rig: Rig) -> None:  # noqa: F811
    slow_rig(rig)
    rig.cache(url=PAGE_URL, engine="limetorrents")
    rig.fake.downloader_delay_calls = 10**6
    job_id = (await rig.post()).json()["job_id"]
    assert (await rig.api.delete(f"/api/downloads/{job_id}")).status_code == 204
    sweeps = [t for t in asyncio.all_tasks() if t.get_name().startswith("cancel-sweep-")]
    assert sweeps and not any(t.done() for t in sweeps)

    await rig.app.state.jobs.shutdown()

    assert all(t.done() for t in sweeps)
    assert not any(t.exception() for t in sweeps if not t.cancelled())


async def test_a_torrent_of_a_cancelled_job_is_not_listed(
    user_api: httpx.AsyncClient,
    fake_qbit: FakeQbit,
    app: FastAPI,
) -> None:
    job = Job("0123456789abcdef", None, "film", JobState.CANCELLED, None, time.time())
    app.state.jobs._jobs[job.job_id] = job
    fake_qbit.add_torrent_row(
        HASH, category="Film", tags=("fx", "fx-pending", f"fx-job-{job.job_id}"), state="stoppedDL"
    )

    response = await user_api.get("/api/downloads")

    assert response.json() == {"items": []}
    assert download_id(PORTAL_SECRET_KEY, HASH) not in response.text
