"""Cancel and remove through the API against FakeQbit (DOWN-05, DOWN-06, D-32..D-35).

The browser names a download by its opaque id only; these tests watch what the backend sent to
qBittorrent (`fake.deleted`) and what the list shows afterwards.
"""

import asyncio
import os
import time
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from app.config import Settings
from app.download.jobs import Job, JobRegistry, JobState
from app.download.listing import download_id
from app.download.pipeline import DownloadPipeline
from app.qbit.client import QbitClient, QbitError
from app.quarantine.guard import HandoffGuard
from app.quarantine.outcomes import Outcome, OutcomeStore
from app.quarantine.runner_client import RunnerClient
from app.quarantine.verifier import Verifier
from app.search.service import SearchService
from tests.conftest import PORTAL_SECRET_KEY, QBIT_PASS, QBIT_USER
from tests.fakeqbit import FakeQbit
from tests.fakerunner import film_facts

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

# The verifier rig (sparse files, fake runner) is shared for the cancel-during-probe case.
from tests.test_quarantine_verifier import GB, TrackingRunner, make_settings, put_file
from tests.test_quarantine_verifier import Rig as VerifierRig

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


async def test_a_download_that_finishes_while_the_job_is_being_stopped_keeps_its_files(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit, app: FastAPI
) -> None:
    # The tap reads the row at 99 %, then stopping the job takes a moment and the torrent finishes.
    # The delete must decide on the row as it is right before it goes out, not on the first read.
    torrent = fake_qbit.add_torrent_row(HASH, category="Film", state="downloading", progress=0.99)
    (item,) = (await user_api.get("/api/downloads")).json()["items"]
    assert item["action"] == "cancel"
    registry = app.state.jobs
    real_cancel_for = registry.cancel_for

    async def finishing_cancel_for(**kwargs: object) -> object:
        torrent.state, torrent.progress, torrent.completion_on = "stalledUP", 1.0, int(time.time())
        return await real_cancel_for(**kwargs)

    registry.cancel_for = finishing_cancel_for

    response = await user_api.delete(f"/api/downloads/{item['id']}")

    assert response.status_code == 204
    assert fake_qbit.deleted == [(HASH, False)]


async def test_a_failed_re_read_before_the_delete_never_deletes_files_and_starts_a_sweep(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit, app: FastAPI
) -> None:
    fake_qbit.add_torrent_row(
        HASH, category="Film", tags=("fx", "fx-job-0123456789abcdef"), state="downloading",
        progress=0.4,
    )  # fmt: skip
    app.state.jobs._jobs["0123456789abcdef"] = Job(
        "0123456789abcdef", None, "film", JobState.PREPARING, HASH, time.time()
    )
    (item,) = (await user_api.get("/api/downloads")).json()["items"]
    lookups = iter([httpx.Response(500, text="boom")])
    real_info = fake_qbit._torrents_info

    def flaky_info(request: httpx.Request) -> httpx.Response:
        if "hashes" in request.url.params:
            return next(lookups)
        return real_info(request)

    fake_qbit.register("GET", "/api/v2/torrents/info", flaky_info)

    response = await user_api.delete(f"/api/downloads/{item['id']}")

    assert response.status_code == 502
    assert fake_qbit.deleted == []
    sweeps = [t for t in asyncio.all_tasks() if t.get_name().startswith("cancel-sweep-")]
    assert sweeps
    await app.state.jobs.shutdown()


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


async def test_a_failed_first_sweep_still_leaves_a_sweep_that_deletes_the_torrent(
    rig: Rig,  # noqa: F811
) -> None:
    slow_rig(rig)
    rig.cache(url=PAGE_URL, engine="limetorrents")
    page_hash = FakeQbit.hash_for(PAGE_URL)
    rig.fake.downloader_delay_calls = 10**6
    job_id = (await rig.post()).json()["job_id"]
    real_info = rig.fake._torrents_info
    failures = [httpx.Response(500, text="boom")]

    def flaky_info(request: httpx.Request) -> httpx.Response:
        if "tag" in request.url.params and failures:
            return failures.pop()
        return real_info(request)

    rig.fake.register("GET", "/api/v2/torrents/info", flaky_info)

    response = await rig.api.delete(f"/api/downloads/{job_id}")

    # The job is cancelled for good, so the tap must not look like a failure to retry (a retry
    # would answer 404), and the sweep that was started afterwards removes the late torrent.
    assert response.status_code == 204
    assert rig.app.state.jobs.get(job_id).state is JobState.CANCELLED
    rig.fake._pending_downloads[0][0] = 0
    for _ in range(50):
        if rig.fake.deleted:
            break
        await settle(rig, 0.02)
    assert rig.fake.deleted == [(page_hash, True)]


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


# -- Phase 2.1: Cancel and Remove under the quarantine layout (D-47, D-49, D-53, D-79) ------------

DAY = 86400


def quarantine_path(settings: Settings, category: str = "Film") -> str:
    return f"{settings.quarantine_root}/{category}"


async def delete_item(user_api: httpx.AsyncClient) -> tuple[dict, httpx.Response]:
    (item,) = (await user_api.get("/api/downloads")).json()["items"]
    return item, await user_api.delete(f"/api/downloads/{item['id']}")


async def test_cancel_on_a_checking_torrent_deletes_the_quarantine_files(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit, settings: Settings, app: FastAPI
) -> None:
    fake_qbit.add_torrent_row(
        HASH, category="Film", state="stalledUP", progress=1.0, completion_on=int(time.time()) - 60,
        save_path=quarantine_path(settings),
    )  # fmt: skip
    wanted = download_id(PORTAL_SECRET_KEY, HASH)

    outcome = await app.state.pipeline.cancel(wanted)

    assert outcome is not None
    assert (outcome.action, outcome.deleted_files) == ("cancel", True)
    assert fake_qbit.deleted == [(HASH, True)]


async def test_the_checking_row_says_cancel_and_delete_answers_204_with_files_deleted(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit, settings: Settings
) -> None:
    fake_qbit.add_torrent_row(
        HASH, category="Film", state="stalledUP", progress=1.0, completion_on=int(time.time()) - 60,
        save_path=quarantine_path(settings),
    )  # fmt: skip

    item, response = await delete_item(user_api)

    assert (item["state"], item["action"]) == ("checking", "cancel")
    assert response.status_code == 204
    assert fake_qbit.deleted == [(HASH, True)]


async def test_cancel_on_a_problem_row_deletes_the_quarantine_files(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit, settings: Settings
) -> None:
    fake_qbit.add_torrent_row(
        HASH, category="Film", state="stalledUP", progress=1.0,
        completion_on=int(time.time()) - 7 * 3600, save_path=quarantine_path(settings),
    )  # fmt: skip

    item, response = await delete_item(user_api)

    assert (item["state"], item["action"]) == ("problem", "cancel")
    assert response.status_code == 204
    assert fake_qbit.deleted == [(HASH, True)]


async def test_cancel_on_a_download_in_progress_under_quarantine_deletes_its_files(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit, settings: Settings
) -> None:
    fake_qbit.add_torrent_row(
        HASH, category="Film", state="downloading", progress=0.4,
        save_path=quarantine_path(settings),
    )  # fmt: skip

    item, response = await delete_item(user_api)

    assert item["action"] == "cancel"
    assert response.status_code == 204
    assert fake_qbit.deleted == [(HASH, True)]


async def test_remove_on_a_verified_row_deletes_only_the_quarantine_name_and_keeps_the_film(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit, settings: Settings, tmp_path: Path
) -> None:
    # The film is hardlinked into media; qBittorrent's delete removes the quarantine name only.
    quarantined = put_file(tmp_path / "quarantine" / "Film" / "Movie" / "movie.mkv", 1024)
    linked = tmp_path / "media" / "Film" / "Movie" / "movie.mkv"
    linked.parent.mkdir(parents=True)
    os.link(quarantined, linked)
    now = int(time.time())
    fake_qbit.add_torrent_row(
        HASH, category="Film", state="stalledUP", progress=1.0, completion_on=now - 60,
        tags=(f"fx-ok-{now}",), save_path=quarantine_path(settings),
    )  # fmt: skip
    real_delete = fake_qbit._torrents_delete

    def delete_the_quarantine_name(request: httpx.Request) -> httpx.Response:
        if "deleteFiles=true" in request.content.decode():
            quarantined.unlink()
        return real_delete(request)

    fake_qbit.register("POST", "/api/v2/torrents/delete", delete_the_quarantine_name)

    item, response = await delete_item(user_api)

    assert (item["state"], item["action"]) == ("ready", "remove")
    assert response.status_code == 204
    assert fake_qbit.deleted == [(HASH, True)]
    assert linked.exists() and not quarantined.exists()


@pytest.mark.parametrize(
    ("state", "progress", "deletes"),
    [("stalledUP", 1.0, False), ("missingFiles", 1.0, False), ("downloading", 0.4, True)],
)
async def test_a_legacy_torrent_outside_quarantine_keeps_the_phase_two_rule(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit, state: str, progress: float, deletes: bool
) -> None:
    fake_qbit.add_torrent_row(
        HASH, category="Film", state=state, progress=progress,
        completion_on=int(time.time()) - 60 if progress >= 1 else -1,
        save_path="/data/media/Film",
    )  # fmt: skip

    item, response = await delete_item(user_api)

    assert item["action"] == ("cancel" if deletes else "remove")
    assert response.status_code == 204
    assert fake_qbit.deleted == [(HASH, deletes)]


# (raw state, progress, verified tag, save path kind): the button must name what DELETE does.
ROWS = [
    ("stalledUP", 1.0, False, "quarantine"),
    ("stalledUP", 1.0, True, "quarantine"),
    ("downloading", 0.4, False, "quarantine"),
    ("stalledDL", 0.2, False, "quarantine"),
    ("metaDL", 0.0, False, "quarantine"),
    ("stoppedUP", 1.0, True, "quarantine"),
    ("stalledUP", 1.0, False, "legacy"),
    ("missingFiles", 1.0, False, "legacy"),
    ("downloading", 0.4, False, "legacy"),
    ("stalledDL", 0.2, False, "legacy"),
]


@pytest.mark.parametrize(("state", "progress", "verified", "where"), ROWS)
async def test_every_rows_action_equals_what_delete_then_does(
    user_api: httpx.AsyncClient,
    fake_qbit: FakeQbit,
    settings: Settings,
    state: str,
    progress: float,
    verified: bool,
    where: str,
) -> None:
    now = int(time.time())
    fake_qbit.add_torrent_row(
        HASH, category="Film", state=state, progress=progress,
        completion_on=now - 60 if progress >= 1 else -1,
        tags=(f"fx-ok-{now}",) if verified else (),
        save_path=quarantine_path(settings) if where == "quarantine" else "/data/media/Film",
    )  # fmt: skip

    item, response = await delete_item(user_api)

    assert response.status_code == 204
    ((_, files_deleted),) = fake_qbit.deleted
    if where == "quarantine":
        assert files_deleted is True  # only the quarantine name goes; a verified film is linked
        assert item["action"] == ("remove" if verified else "cancel")
    else:
        assert files_deleted is (item["action"] == "cancel")


def install_store(app: FastAPI, root: Path) -> OutcomeStore:
    """Point the list and the pipeline at a temporary outcome folder (the real one is /data)."""
    state = app.state
    state.outcomes = OutcomeStore(root)
    state.pipeline = DownloadPipeline(
        state.qbit,
        state.settings,
        state.search,
        state.jobs,
        guard=state.guard,
        outcomes=state.outcomes,
    )
    return state.outcomes


async def test_removing_a_ready_outcome_row_deletes_its_sidecar_only(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit, app: FastAPI, tmp_path: Path
) -> None:
    store = install_store(app, tmp_path / "rejected")
    outcome_id = download_id(PORTAL_SECRET_KEY, "9" * 40)
    store.write(Outcome(outcome_id, "Dune", "film", "ready", 1, time.time() - DAY))

    item, response = await delete_item(user_api)

    assert (item["id"], item["state"], item["action"]) == (outcome_id, "ready", "remove")
    assert response.status_code == 204
    assert store.get(outcome_id) is None
    assert (await user_api.get("/api/downloads")).json() == {"items": []}
    assert fake_qbit.deleted == []


async def test_a_check_failed_outcome_row_has_no_action_and_delete_answers_404(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit, app: FastAPI, tmp_path: Path
) -> None:
    store = install_store(app, tmp_path / "rejected")
    outcome_id = download_id(PORTAL_SECRET_KEY, "9" * 40)
    store.write(Outcome(outcome_id, "Dune", "film", "rejected", 0, time.time() - 60))

    response = await user_api.delete(f"/api/downloads/{outcome_id}")

    assert response.status_code == 404
    assert response.json() == {"detail": "download_not_found"}
    assert store.get(outcome_id) is not None
    assert fake_qbit.deleted == []


# -- a Cancel during a probe always wins (RESEARCH Pitfall 10, T-02.1-30) -------------------------


@pytest.fixture
async def vrig(tmp_path: Path) -> AsyncIterator[VerifierRig]:
    settings = make_settings(tmp_path)
    fake = FakeQbit(QBIT_USER, QBIT_PASS)
    runner = TrackingRunner()
    qbit = QbitClient(
        settings.qbittorrent_url,
        settings.qbittorrent_user,
        settings.qbittorrent_pass,
        transport=fake.transport,
    )
    runner_client = RunnerClient(settings.sandbox_url, transport=runner.transport)
    guard = HandoffGuard()
    verifier = Verifier(qbit, runner_client, settings, guard=guard, clock=lambda: 1_700_000_000.0)
    yield VerifierRig(settings, fake, runner, verifier, qbit, runner_client, guard)
    await qbit.aclose()
    await runner_client.aclose()


async def test_a_cancel_during_the_probe_wins_and_the_verifier_links_nothing(
    vrig: VerifierRig,
) -> None:
    vrig.add_finished("a" * 40, "Movie", [("Movie/movie.mkv", 4 * GB)])
    vrig.runner.script("Film/Movie/movie.mkv", film_facts(duration=6000.0))
    vrig.runner.hold = asyncio.Event()
    pipeline = DownloadPipeline(
        vrig.qbit,
        vrig.settings,
        SearchService(vrig.qbit, vrig.settings),
        JobRegistry(),
        guard=vrig.guard,
    )
    seen_at_delete: list[tuple[bool, bool]] = []
    real_delete = vrig.fake._torrents_delete

    def spy(request: httpx.Request) -> httpx.Response:
        # The flag is up and the torrent's lock is held when the delete goes out.
        seen_at_delete.append(
            (vrig.guard.cancel_requested("a" * 40), vrig.guard.lock("a" * 40).locked())
        )
        return real_delete(request)

    vrig.fake.register("POST", "/api/v2/torrents/delete", spy)
    check = asyncio.create_task(vrig.verifier.run_once())
    await asyncio.wait_for(vrig.runner.started.wait(), 5)

    outcome = await pipeline.cancel(
        download_id(vrig.settings.secret_key.get_secret_value(), "a" * 40)
    )
    vrig.runner.hold.set()
    await asyncio.wait_for(check, 5)

    assert outcome is not None and outcome.action == "cancel"
    assert seen_at_delete == [(True, True)]
    assert not vrig.guard.cancel_requested("a" * 40)  # over: a re-added torrent is checked again
    assert vrig.fake.deleted == [("a" * 40, True)]
    assert vrig.media_files() == []
    assert vrig.tag_calls() == []
    assert vrig.fake.torrents == {}


async def test_a_failed_delete_lowers_the_flag_so_the_torrent_can_still_be_checked(
    vrig: VerifierRig,
) -> None:
    vrig.add_finished("a" * 40, "Movie", [("Movie/movie.mkv", 4 * GB)])
    vrig.runner.script("Film/Movie/movie.mkv", film_facts(duration=6000.0))
    vrig.fake.register("POST", "/api/v2/torrents/delete", lambda request: httpx.Response(500))
    pipeline = DownloadPipeline(
        vrig.qbit,
        vrig.settings,
        SearchService(vrig.qbit, vrig.settings),
        JobRegistry(),
        guard=vrig.guard,
    )

    with pytest.raises(QbitError):
        await pipeline.cancel(download_id(vrig.settings.secret_key.get_secret_value(), "a" * 40))
    await vrig.verifier.run_once()

    assert not vrig.guard.cancel_requested("a" * 40)
    assert vrig.media_files() == ["Film/Movie/movie.mkv"]  # nothing was lost: it is verified


async def test_a_torrent_added_again_after_a_cancel_is_checked(vrig: VerifierRig) -> None:
    vrig.add_finished("a" * 40, "Movie", [("Movie/movie.mkv", 4 * GB)])
    vrig.runner.script("Film/Movie/movie.mkv", film_facts(duration=6000.0))
    pipeline = DownloadPipeline(
        vrig.qbit,
        vrig.settings,
        SearchService(vrig.qbit, vrig.settings),
        JobRegistry(),
        guard=vrig.guard,
    )
    await pipeline.cancel(download_id(vrig.settings.secret_key.get_secret_value(), "a" * 40))

    vrig.add_finished("a" * 40, "Movie", [("Movie/movie.mkv", 4 * GB)])  # the same hash again
    await vrig.verifier.run_once()

    assert vrig.media_files() == ["Film/Movie/movie.mkv"]
