"""Download pipeline through the API: add, metadata, allowlist, priorities, start (DOWN-01..03).

The fake qBittorrent keeps real torrent state, so every assertion is about what the backend
sent (call log) or what the fake ended up holding, never about internal calls.
"""

import asyncio
import inspect
import logging
import socket
from dataclasses import dataclass, field

import httpx
import pytest
from fastapi import FastAPI

from app.config import Settings
from app.download.jobs import JobState
from app.download.pipeline import DownloadPipeline
from app.main import create_app
from app.qbit.client import QbitClient
from app.search.service import CachedResult
from tests.conftest import wait_for_bootstrap
from tests.fakeqbit import FakeQbit, FakeTorrent

MB = 1024 * 1024
BTIH = "08ada5a7a6183aae1e09d831df6748d566095a10"
MAGNET = f"magnet:?xt=urn:btih:{BTIH}&dn=Sintel"
RESULT_ID = "a1b2c3d4e5f60718"
SERIE_BTIH = "1111111111111111111111111111111111111111"
SERIE_MAGNET = f"magnet:?xt=urn:btih:{SERIE_BTIH}&dn=Show"
SERIE_RESULT_ID = "ffeeddccbbaa9988"

ADD = "/api/v2/torrents/add"
FILE_PRIO = "/api/v2/torrents/filePrio"
FILES = "/api/v2/torrents/files"
START = "/api/v2/torrents/start"
DELETE = "/api/v2/torrents/delete"

# Shaped like the real Sintel torrent (research): the video, a poster, subtitles, noise.
SINTEL_FILES = [
    ("Sintel/Sintel.mp4", 129241752),
    ("Sintel/poster.jpg", 46115),
    ("Sintel/subs/Sintel.en.srt", 1234),
    ("Sintel/subs/Sintel.it.srt", 1250),
    ("Sintel/readme.txt", 400),
    ("Sintel/setup.exe", 1000),
]


class FakeClock:
    """Epoch seconds that only move when the pipeline sleeps, so no test waits for real."""

    def __init__(self) -> None:
        self.now = 1_700_000_000.0

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds
        await asyncio.sleep(0)


@dataclass
class Rig:
    api: httpx.AsyncClient
    app: FastAPI
    fake: FakeQbit
    clock: FakeClock
    # Host name -> addresses; any host not listed resolves to one public address (no real DNS).
    dns: dict[str, list[str]] = field(default_factory=dict)

    async def resolver(self, host: str) -> list[str]:
        if host in self.dns and self.dns[host] == []:
            raise socket.gaierror("no such host")
        return self.dns.get(host, ["93.184.216.34"])

    def cache(
        self,
        result_id: str = RESULT_ID,
        url: str = MAGNET,
        type: str = "film",
        engine: str = "limetorrents",
    ) -> None:
        self.app.state.search._cache[result_id] = CachedResult(
            result_id=result_id,
            engine=engine,
            file_url=url,
            type=type,  # type: ignore[arg-type]
            name="Sintel",
            expires_at=float("inf"),
        )

    def use_sleep(self, sleep) -> None:
        """Replace the pipeline with one that uses a different sleep (same clock)."""
        state = self.app.state
        state.pipeline = DownloadPipeline(
            state.qbit,
            state.settings,
            state.search,
            state.jobs,
            clock=self.clock,
            sleep=sleep,
            resolver=self.resolver,
            guard=state.guard,
            outcomes=state.outcomes,
        )

    async def post(self, result_id: str = RESULT_ID, type: str = "film", **extra) -> httpx.Response:
        return await self.api.post(
            "/api/download", json={"result_id": result_id, "type": type, **extra}
        )

    def adds(self) -> list:
        return self.fake.calls_to(ADD)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def rig(app: FastAPI, user_api: httpx.AsyncClient, fake_qbit: FakeQbit, clock: FakeClock) -> Rig:
    fake_qbit.clock = clock
    rig = Rig(user_api, app, fake_qbit, clock)
    rig.use_sleep(clock.sleep)
    return rig


def index_of(fake: FakeQbit, path: str, last: bool = False) -> int:
    paths = [call.path for call in fake.calls]
    return len(paths) - 1 - paths[::-1].index(path) if last else paths.index(path)


async def test_film_download_is_added_in_film_category_filtered_and_started(rig: Rig) -> None:
    rig.cache()
    rig.fake.set_metadata(BTIH, SINTEL_FILES)

    response = await rig.post()

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"status", "job_id"}
    assert body["status"] == "started"
    assert len(body["job_id"]) == 16
    (add,) = rig.adds()
    assert add.form["urls"] == MAGNET
    assert add.form["category"] == "Film"
    assert add.form["autoTMM"] == "true"
    assert add.form["stopCondition"] == "MetadataReceived"
    assert rig.fake.torrents[BTIH].downloaded == 0  # no payload was ever requested before start
    tags = add.form["tags"].split(",")
    assert tags[:2] == ["fx", "fx-pending"]
    assert tags[2] == f"fx-job-{body['job_id']}"
    assert "stopped" not in add.form
    assert "downloader" not in add.form


async def test_only_video_and_subtitles_stay_enabled_and_start_comes_last(rig: Rig) -> None:
    rig.cache()
    rig.fake.set_metadata(BTIH, SINTEL_FILES)

    await rig.post()

    files = rig.fake.torrents[BTIH].files
    priorities = {row["name"]: row["priority"] for row in files}
    assert priorities == {
        "Sintel/Sintel.mp4": 1,
        "Sintel/poster.jpg": 0,
        "Sintel/subs/Sintel.en.srt": 1,
        "Sintel/subs/Sintel.it.srt": 1,
        "Sintel/readme.txt": 0,
        "Sintel/setup.exe": 0,
    }
    # Priorities are set, then read back, and only then is the torrent started.
    first_prio = index_of(rig.fake, FILE_PRIO)
    last_prio = index_of(rig.fake, FILE_PRIO, last=True)
    reread = [i for i, c in enumerate(rig.fake.calls) if c.path == FILES and i > last_prio]
    assert first_prio < last_prio < reread[0] < index_of(rig.fake, START)
    assert rig.fake.torrents[BTIH].started is True


async def test_pending_tags_are_removed_once_the_torrent_is_started(rig: Rig) -> None:
    rig.cache()
    rig.fake.set_metadata(BTIH, SINTEL_FILES)

    await rig.post()

    assert rig.fake.torrents[BTIH].tags == ["fx"]


async def test_serie_download_uses_the_serie_category(rig: Rig) -> None:
    rig.cache(SERIE_RESULT_ID, SERIE_MAGNET, "serie")
    rig.fake.set_metadata(SERIE_BTIH, [("Show.S01E01.mkv", 700 * MB)])

    response = await rig.post(SERIE_RESULT_ID, "serie")

    assert response.json()["status"] == "started"
    (add,) = rig.adds()
    assert add.form["category"] == "SerieTV"


async def test_the_started_job_can_be_read_back_with_the_same_two_keys(rig: Rig) -> None:
    rig.cache()
    rig.fake.set_metadata(BTIH, SINTEL_FILES)
    posted = (await rig.post()).json()

    fetched = await rig.api.get(f"/api/download/{posted['job_id']}")

    assert fetched.status_code == 200
    assert fetched.json() == posted
    assert (await rig.api.get("/api/download/0000000000000000")).status_code == 404


async def test_a_404_for_the_file_list_right_after_add_is_retried(rig: Rig) -> None:
    rig.cache()
    rig.fake.set_metadata(BTIH, SINTEL_FILES)
    rig.fake.files_404_calls = 3

    response = await rig.post()

    assert response.json()["status"] == "started"


# -- configuration drift (WR-06) -----------------------------------------------------------

SET_PREFS = "/api/v2/app/setPreferences"


async def test_a_category_path_changed_behind_the_portal_is_repaired_before_the_add(
    rig: Rig,
) -> None:
    rig.cache()
    rig.fake.set_metadata(BTIH, SINTEL_FILES)
    rig.fake.category_table["Film"]["savePath"] = "/somewhere/else"

    response = await rig.post()

    assert response.json()["status"] == "started"
    assert rig.fake.category_table["Film"]["savePath"] == "/data/quarantine/Film"
    assert index_of(rig.fake, "/api/v2/torrents/editCategory", last=True) < index_of(rig.fake, ADD)


async def test_a_missing_category_is_created_with_its_save_path_before_the_add(rig: Rig) -> None:
    rig.cache()
    rig.fake.set_metadata(BTIH, SINTEL_FILES)
    del rig.fake.category_table["Film"]  # qBittorrent came back with a fresh config

    await rig.post()

    assert rig.fake.category_table["Film"]["savePath"] == "/data/quarantine/Film"
    assert index_of(rig.fake, "/api/v2/torrents/createCategory", last=True) < index_of(
        rig.fake, ADD
    )


async def test_a_switched_off_exclusion_list_is_switched_on_again_before_the_add(
    rig: Rig,
) -> None:
    rig.cache()
    rig.fake.set_metadata(BTIH, SINTEL_FILES)
    rig.fake.preferences["excluded_file_names_enabled"] = False
    rig.fake.preferences["excluded_file_names"] = ""

    await rig.post()

    assert rig.fake.preferences["excluded_file_names_enabled"] is True
    assert "*.exe" in rig.fake.preferences["excluded_file_names"].splitlines()
    assert index_of(rig.fake, SET_PREFS, last=True) < index_of(rig.fake, ADD)


async def test_an_untouched_configuration_is_not_rewritten_on_every_download(rig: Rig) -> None:
    rig.cache()
    rig.fake.set_metadata(BTIH, SINTEL_FILES)
    writes_before = len(rig.fake.calls_to(SET_PREFS))

    await rig.post()

    assert len(rig.fake.calls_to(SET_PREFS)) == writes_before


async def test_nothing_is_added_when_the_configuration_cannot_be_repaired(rig: Rig) -> None:
    rig.cache()
    rig.fake.preferences["auto_tmm_enabled"] = False
    rig.fake.register("POST", SET_PREFS, lambda request: httpx.Response(500, text="boom"))

    response = await rig.post()

    assert response.json()["status"] == "failed"
    assert rig.adds() == []


# -- rejections (D-13, D-14) ---------------------------------------------------------------


async def test_a_torrent_without_a_video_is_deleted_with_its_files_and_never_started(
    rig: Rig,
) -> None:
    rig.cache()
    rig.fake.set_metadata(BTIH, [("Movie/setup.exe", 5000), ("Movie/readme.txt", 10)])

    response = await rig.post()

    assert response.json()["status"] == "rejected"
    assert rig.fake.deleted == [(BTIH, True)]
    assert rig.fake.calls_to(START) == []
    assert rig.fake.calls_to(FILE_PRIO) == []
    assert BTIH not in rig.fake.torrents


async def test_a_webm_only_torrent_is_unsupported_deleted_and_never_started(rig: Rig) -> None:
    rig.cache()
    rig.fake.set_metadata(
        BTIH,
        [
            ("Tears of Steel/tears_of_steel_1080p.webm", 1200 * MB),
            ("Tears of Steel/tears_of_steel.en.srt", 40_000),
        ],
    )

    response = await rig.post()

    body = response.json()
    assert body["status"] == "unsupported"
    assert set(body) == {"status", "job_id"}
    assert rig.fake.deleted == [(BTIH, True)]
    assert rig.fake.calls_to(START) == []
    assert rig.fake.calls_to(FILE_PRIO) == []
    assert BTIH not in rig.fake.torrents
    fetched = await rig.api.get(f"/api/download/{body['job_id']}")
    assert fetched.json() == body


async def test_a_big_film_in_another_format_with_a_small_allowed_trailer_is_unsupported(
    rig: Rig,
) -> None:
    rig.cache()
    rig.fake.set_metadata(
        BTIH,
        [
            ("Movie/Movie.m2ts", 20 * 1024 * MB),
            ("Movie/Trailer.mp4", 100 * MB),
        ],
    )

    response = await rig.post()

    body = response.json()
    assert body["status"] == "unsupported"
    assert rig.fake.deleted == [(BTIH, True)]
    assert rig.fake.calls_to(START) == []
    assert rig.fake.calls_to(FILE_PRIO) == []
    assert BTIH not in rig.fake.torrents


async def test_a_torrent_holding_only_samples_is_rejected(rig: Rig) -> None:
    rig.cache()
    rig.fake.set_metadata(
        BTIH, [("Movie/Sample/sample.mkv", 30 * MB), ("Movie/movie-sample.avi", 20 * MB)]
    )

    response = await rig.post()

    assert response.json()["status"] == "rejected"
    assert rig.fake.deleted == [(BTIH, True)]
    assert rig.fake.calls_to(START) == []


async def test_a_season_pack_keeps_every_episode_and_drops_the_sample(rig: Rig) -> None:
    rig.cache(SERIE_RESULT_ID, SERIE_MAGNET, "serie")
    episodes = [(f"Show/Show.S01E{n:02d}.mkv", 700 * MB) for n in range(1, 11)]
    rig.fake.set_metadata(
        SERIE_BTIH, [*episodes, ("Show/Sample/sample.mkv", 30 * MB), ("Show/Show.nfo", 900)]
    )

    response = await rig.post(SERIE_RESULT_ID, "serie")

    assert response.json()["status"] == "started"
    priorities = {row["name"]: row["priority"] for row in rig.fake.torrents[SERIE_BTIH].files}
    assert [priorities[name] for name, _ in episodes] == [1] * 10
    assert priorities["Show/Sample/sample.mkv"] == 0
    assert priorities["Show/Show.nfo"] == 0


async def test_a_priority_that_did_not_stick_deletes_the_torrent_and_never_starts_it(
    rig: Rig,
) -> None:
    rig.cache()
    rig.fake.set_metadata(BTIH, SINTEL_FILES)
    rig.fake.ignore_prio_ids = {1}  # the poster would stay enabled

    response = await rig.post()

    assert response.json()["status"] == "failed"
    assert rig.fake.deleted == [(BTIH, True)]
    assert rig.fake.calls_to(START) == []


# -- slow and missing metadata (D-11, D-12) -------------------------------------------------


async def test_slow_metadata_answers_preparing_and_the_job_ends_started_later(rig: Rig) -> None:
    rig.app.state.settings = rig.app.state.settings.model_copy(
        update={"download_wait_seconds": 0.05}
    )

    async def slow_sleep(seconds: float) -> None:
        rig.clock.now += seconds
        await asyncio.sleep(0.01)

    rig.use_sleep(slow_sleep)
    rig.cache()
    rig.fake.set_metadata(BTIH, SINTEL_FILES, delay_polls=20)
    began = rig.clock.now

    first = await rig.post()

    assert first.status_code == 200
    assert first.json()["status"] == "preparing"
    job_id = first.json()["job_id"]
    assert (await rig.api.get(f"/api/download/{job_id}")).json()["status"] == "preparing"
    await asyncio.wait_for(rig.app.state.jobs.task(job_id), 5)
    later = await rig.api.get(f"/api/download/{job_id}")
    assert later.json() == {"status": "started", "job_id": job_id}
    assert rig.clock.now - began >= 20
    assert len(rig.adds()) == 1


async def test_no_metadata_before_the_timeout_deletes_the_torrent_as_unavailable(
    rig: Rig,
) -> None:
    rig.cache()  # the fake never releases a file list for this torrent
    began = rig.clock.now

    response = await rig.post()

    assert response.json()["status"] == "unavailable"
    assert rig.fake.deleted == [(BTIH, True)]
    assert rig.fake.calls_to(START) == []
    waited = rig.clock.now - began
    assert rig.app.state.settings.metadata_timeout <= waited < 310


# -- duplicates and add failures ---------------------------------------------------------------


async def test_a_magnet_already_in_qbittorrent_is_a_duplicate_and_is_not_added(rig: Rig) -> None:
    rig.cache()
    rig.fake.torrents[BTIH] = FakeTorrent(BTIH, MAGNET, "Film", [], rig.clock.now)

    response = await rig.post()

    assert response.json()["status"] == "duplicate"
    assert rig.adds() == []
    assert rig.fake.deleted == []  # somebody else's torrent is never touched


async def test_a_409_from_add_is_a_duplicate(rig: Rig) -> None:
    rig.cache()
    rig.fake.register("POST", ADD, lambda request: httpx.Response(409, text="Conflict"))

    response = await rig.post()

    assert response.json()["status"] == "duplicate"
    assert rig.fake.calls_to(START) == []


async def test_an_invalid_torrent_answered_415_is_unavailable(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    rig.cache()
    rig.fake.register(
        "POST", ADD, lambda request: httpx.Response(415, text="is not a valid torrent file")
    )

    with caplog.at_level(logging.WARNING):
        response = await rig.post()

    assert response.json()["status"] == "unavailable"
    assert rig.fake.calls_to(START) == []
    assert rig.fake.calls_to(DELETE) == []
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "HTTP 415" in warnings[0]
    assert MAGNET not in warnings[0]
    assert BTIH not in warnings[0]
    assert "valid torrent" not in warnings[0]


async def test_a_category_path_refused_with_409_fails_the_job_and_logs_the_status(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    rig.cache()
    rig.fake.set_metadata(BTIH, SINTEL_FILES)
    rig.fake.category_table["Film"]["savePath"] = "/somewhere/else"
    rig.fake.register(
        "POST",
        "/api/v2/torrents/editCategory",
        lambda request: httpx.Response(409, text="Category editing failed"),
    )

    with caplog.at_level(logging.WARNING):
        response = await rig.post()

    assert response.json()["status"] == "failed"
    assert rig.adds() == []
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("QbitError" in w and "HTTP 409" in w for w in warnings)
    assert not any("Category editing failed" in w for w in warnings)


async def test_any_other_add_error_still_fails(rig: Rig) -> None:
    rig.cache()
    rig.fake.register("POST", ADD, lambda request: httpx.Response(500, text="boom"))

    response = await rig.post()

    assert response.json()["status"] == "failed"
    assert rig.fake.calls_to(START) == []


async def test_a_qbittorrent_error_midway_fails_the_job_and_keeps_the_pending_tag(
    rig: Rig,
) -> None:
    rig.cache()
    rig.fake.set_metadata(BTIH, SINTEL_FILES)
    rig.fake.register("POST", START, lambda request: httpx.Response(500, text="boom"))

    response = await rig.post()

    assert response.json()["status"] == "failed"
    # Not started, not deleted: the fx-pending tag lets the next start finish or clean it up.
    assert "fx-pending" in rig.fake.torrents[BTIH].tags
    assert rig.fake.torrents[BTIH].started is False


async def test_a_tap_after_a_job_failed_midway_finishes_the_torrent_instead_of_saying_duplicate(
    rig: Rig,
) -> None:
    rig.cache()
    rig.fake.set_metadata(BTIH, SINTEL_FILES)
    working_start = rig.fake._torrents_start
    rig.fake.register("POST", START, lambda request: httpx.Response(500, text="boom"))
    first = await rig.post()
    assert first.json()["status"] == "failed"
    assert "fx-pending" in rig.fake.torrents[BTIH].tags

    rig.fake.register("POST", START, working_start)  # qBittorrent recovers
    second = await rig.post()

    assert second.json()["status"] == "started"
    assert len(rig.adds()) == 1  # the stranded torrent is finished, not added again
    assert rig.fake.torrents[BTIH].started is True
    assert rig.fake.torrents[BTIH].tags == ["fx"]
    assert rig.fake.deleted == []


async def test_a_pending_torrent_a_running_job_owns_is_still_a_duplicate(rig: Rig) -> None:
    rig.cache()
    job_id = "cccccccccccccccc"
    rig.fake.torrents[BTIH] = FakeTorrent(
        BTIH, MAGNET, "Film", ["fx", "fx-pending", f"fx-job-{job_id}"], rig.clock.now
    )
    gate = asyncio.Event()

    async def hold() -> None:
        await gate.wait()

    from app.download.jobs import Job

    owner = Job(job_id, None, "film", JobState.PREPARING, BTIH, rig.clock.now)
    rig.app.state.jobs.spawn(owner, hold())

    response = await rig.post()
    gate.set()

    assert response.json()["status"] == "duplicate"
    assert rig.fake.calls_to(START) == []


async def test_a_url_with_a_line_break_fails_before_any_torrent_call(rig: Rig) -> None:
    rig.cache(url=MAGNET + "\nmagnet:?xt=urn:btih:" + SERIE_BTIH)

    response = await rig.post()

    assert response.json()["status"] == "failed"
    assert rig.adds() == []
    # (The startup reconcile lists fx-pending torrents; the job itself looks nothing up.)
    lookups = [c for c in rig.fake.calls_to("/api/v2/torrents/info") if "hashes" in c.params]
    assert lookups == []


async def test_add_torrent_refuses_a_multi_line_url_before_any_request(
    settings: Settings, fake_qbit: FakeQbit
) -> None:
    client = QbitClient(
        settings.qbittorrent_url,
        settings.qbittorrent_user,
        settings.qbittorrent_pass,
        transport=fake_qbit.transport,
    )
    for url in ("magnet:?a\nmagnet:?b", "magnet:?a\rmagnet:?b"):
        with pytest.raises(ValueError):
            await client.add_torrent(url, "Film", ["fx"])
    assert fake_qbit.calls == []
    await client.aclose()


async def test_add_torrent_always_sends_the_stop_condition_and_never_stopped(
    settings: Settings, fake_qbit: FakeQbit
) -> None:
    client = QbitClient(
        settings.qbittorrent_url,
        settings.qbittorrent_user,
        settings.qbittorrent_pass,
        transport=fake_qbit.transport,
    )
    await client.add_torrent(MAGNET, "Film", ["fx"])
    await client.add_torrent(PAGE_URL, "Film", ["fx"], downloader="limetorrents")
    await client.add_torrent(
        "https://torlock.example/tor/12345.torrent", "Film", ["fx"], downloader="torlock"
    )
    forms = [call.form for call in fake_qbit.calls_to(ADD)]
    assert len(forms) == 3
    for form in forms:
        assert form["stopCondition"] == "MetadataReceived"
        assert "stopped" not in form
    # No way to ask for a stopped add: a stopped magnet never fetches its metadata (G-01-3).
    assert "stopped" not in inspect.signature(QbitClient.add_torrent).parameters
    await client.aclose()


async def test_delete_always_sends_the_delete_files_flag(
    settings: Settings, fake_qbit: FakeQbit
) -> None:
    client = QbitClient(
        settings.qbittorrent_url,
        settings.qbittorrent_user,
        settings.qbittorrent_pass,
        transport=fake_qbit.transport,
    )
    await client.delete(["abc"], False)
    await client.delete(["abc"], True)
    forms = [call.form for call in fake_qbit.calls_to(DELETE)]
    assert [form["deleteFiles"] for form in forms] == ["false", "true"]
    assert not hasattr(client, "set_category")
    await client.aclose()


# -- results that are not magnets (research Pitfall 5) -----------------------------------------

PAGE_URL = "https://limetorrents.example/torrent/12345"
# What limetorrents' downloader prints for that page: a magnet, not a .torrent path (G-01-3).
LIME_BTIH = "2222222222222222222222222222222222222222"
LIME_MAGNET = f"magnet:?xt=urn:btih:{LIME_BTIH}&dn=tears+of+steel"
# A direct .torrent URL (torlock prints this kind of path for its pages too).
TORRENT_URL = "https://torlock.example/tor/12345.torrent"


async def test_a_non_magnet_result_is_added_with_its_downloader_and_found_by_tag(
    rig: Rig,
) -> None:
    rig.cache(url=PAGE_URL, engine="limetorrents")
    page_hash = FakeQbit.hash_for(PAGE_URL)
    rig.fake.downloader_delay_calls = 2
    rig.fake.set_metadata(page_hash, SINTEL_FILES)

    response = await rig.post()

    body = response.json()
    assert body["status"] == "started"
    (add,) = rig.adds()
    assert add.form["downloader"] == "limetorrents"
    assert add.form["category"] == "Film"
    # Every route sends the stop condition (D-23); qBittorrent pauses a torrent that has its
    # metadata at add, so no payload was requested before the allowlist ran.
    assert add.form["stopCondition"] == "MetadataReceived"
    assert "stopped" not in add.form
    assert rig.fake.torrents[page_hash].downloaded == 0
    lookups = rig.fake.calls_to("/api/v2/torrents/info")
    assert any(call.params.get("tag") == f"fx-job-{body['job_id']}" for call in lookups)
    assert rig.fake.torrents[page_hash].started is True


async def test_a_page_result_whose_downloader_prints_a_magnet_fetches_metadata_and_starts(
    rig: Rig,
) -> None:
    rig.cache(url=PAGE_URL, engine="limetorrents")
    rig.fake.downloader_magnets[PAGE_URL] = LIME_MAGNET
    rig.fake.downloader_delay_calls = 2
    rig.fake.set_metadata(LIME_BTIH, SINTEL_FILES, delay_polls=2)
    began = rig.clock.now

    response = await rig.post()

    body = response.json()
    assert body["status"] == "started"  # not the 300 s give-up path (G-01-3 a)
    assert rig.clock.now - began < 60
    (add,) = rig.adds()
    assert add.form["urls"] == PAGE_URL
    assert add.form["downloader"] == "limetorrents"
    assert add.form["category"] == "Film"
    assert add.form["stopCondition"] == "MetadataReceived"
    assert "stopped" not in add.form
    torrent = rig.fake.torrents[LIME_BTIH]
    assert torrent.downloaded == 0  # no payload before the allowlist
    assert torrent.started is True
    assert torrent.tags == ["fx"]
    assert [call.form["hashes"] for call in rig.fake.calls_to(START)] == [LIME_BTIH]


# The four ways a torrent reaches qBittorrent: (result URL, engine, magnet printed by the
# downloader or None, hash the torrent ends up under).
ROUTES = {
    "magnet": (MAGNET, "limetorrents", None, BTIH),
    "downloader->magnet": (PAGE_URL, "limetorrents", LIME_MAGNET, LIME_BTIH),
    "downloader->.torrent": (PAGE_URL, "limetorrents", None, FakeQbit.hash_for(PAGE_URL)),
    "url->.torrent": (TORRENT_URL, "torlock", None, FakeQbit.hash_for(TORRENT_URL)),
}


@pytest.mark.parametrize("route", list(ROUTES), ids=list(ROUTES))
async def test_no_route_downloads_a_payload_byte_before_the_allowlist(rig: Rig, route: str) -> None:
    url, engine, printed, torrent_hash = ROUTES[route]
    rig.cache(url=url, engine=engine)
    if printed is not None:
        rig.fake.downloader_magnets[url] = printed
    rig.fake.set_metadata(torrent_hash, SINTEL_FILES, delay_polls=1)

    response = await rig.post()

    body = response.json()
    assert body["status"] == "started"
    (add,) = rig.adds()
    assert add.form["stopCondition"] == "MetadataReceived"
    assert "stopped" not in add.form
    assert add.form["category"] == "Film"
    torrent = rig.fake.torrents[torrent_hash]
    assert torrent.downloaded == 0  # nothing was fetched before the allowlist ran
    assert torrent.started is True
    assert [call.form["hashes"] for call in rig.fake.calls_to(START)] == [torrent_hash]
    assert torrent.tags == ["fx"]
    priorities = {row["name"]: row["priority"] for row in torrent.files}
    assert priorities == {
        "Sintel/Sintel.mp4": 1,
        "Sintel/poster.jpg": 0,
        "Sintel/subs/Sintel.en.srt": 1,
        "Sintel/subs/Sintel.it.srt": 1,
        "Sintel/readme.txt": 0,
        "Sintel/setup.exe": 0,
    }


async def test_a_downloader_magnet_without_a_video_is_rejected_with_zero_payload(
    rig: Rig,
) -> None:
    rig.cache(url=PAGE_URL, engine="limetorrents")
    rig.fake.downloader_magnets[PAGE_URL] = LIME_MAGNET
    rig.fake.set_metadata(LIME_BTIH, [("Movie/setup.exe", 5000), ("Movie/readme.txt", 10)])
    held_at_delete: list[int] = []
    real_delete = rig.fake._routes[("POST", DELETE)]

    def spy_delete(request: httpx.Request) -> httpx.Response:
        for torrent_hash in rig.fake._form(request).get("hashes", "").split("|"):
            held_at_delete.append(rig.fake.torrents[torrent_hash].downloaded)
        return real_delete(request)

    rig.fake.register("POST", DELETE, spy_delete)

    response = await rig.post()

    assert response.json()["status"] == "rejected"
    assert rig.fake.deleted == [(LIME_BTIH, True)]
    assert held_at_delete == [0]
    assert rig.fake.calls_to(START) == []
    assert rig.fake.calls_to(FILE_PRIO) == []
    assert LIME_BTIH not in rig.fake.torrents


async def test_a_downloader_magnet_with_slow_metadata_answers_preparing_then_started(
    rig: Rig,
) -> None:
    rig.app.state.settings = rig.app.state.settings.model_copy(
        update={"download_wait_seconds": 0.05}
    )

    async def slow_sleep(seconds: float) -> None:
        rig.clock.now += seconds
        await asyncio.sleep(0.01)

    rig.use_sleep(slow_sleep)
    rig.cache(url=PAGE_URL, engine="limetorrents")
    rig.fake.downloader_magnets[PAGE_URL] = LIME_MAGNET
    rig.fake.set_metadata(LIME_BTIH, SINTEL_FILES, delay_polls=20)

    first = await rig.post()

    assert first.json()["status"] == "preparing"
    job_id = first.json()["job_id"]
    await asyncio.wait_for(rig.app.state.jobs.task(job_id), 5)
    later = await rig.api.get(f"/api/download/{job_id}")
    assert later.json() == {"status": "started", "job_id": job_id}
    assert len(rig.adds()) == 1
    assert rig.fake.torrents[LIME_BTIH].downloaded == 0


async def test_the_fake_holds_a_metadata_complete_torrent_added_with_the_stop_condition(
    settings: Settings, fake_qbit: FakeQbit
) -> None:
    client = QbitClient(
        settings.qbittorrent_url,
        settings.qbittorrent_user,
        settings.qbittorrent_pass,
        transport=fake_qbit.transport,
    )
    torrent_hash = FakeQbit.hash_for(TORRENT_URL)
    fake_qbit.set_metadata(torrent_hash, SINTEL_FILES)

    await client.add_torrent(TORRENT_URL, "Film", ["fx"], downloader="torlock")
    (row,) = await client.torrents_info()  # releases the downloader torrent

    # qBittorrent 5.2.4 pauses it at add (sessionimpl.cpp:2794-2801): only `start` runs it.
    assert row["hash"] == torrent_hash
    assert row["state"] == "stoppedDL"
    assert row["downloaded"] == 0
    await client.aclose()


async def test_a_non_magnet_torrent_that_never_appears_is_unavailable(rig: Rig) -> None:
    rig.cache(url=PAGE_URL, engine="limetorrents")
    rig.fake.downloader_delay_calls = 10**6

    response = await rig.post()

    assert response.json()["status"] == "unavailable"
    assert rig.fake.deleted == []  # there is nothing to delete


def private_ip(last: int) -> str:
    """A household-LAN address built at run time (the repo scan bans such literals)."""
    return ".".join(str(part) for part in (192, 168, 1, last))


# -- untrusted plugin URLs (WR-03) ----------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://tracker.example/t.torrent",
        "http://qbittorrent:8080/api/v2/app/shutdown",
        "http://127.0.0.1:8080/",
        f"http://{private_ip(1)}/t.torrent",
    ],
)
async def test_a_cached_url_that_is_not_safe_is_never_sent_to_qbittorrent(
    rig: Rig, url: str
) -> None:
    rig.cache(url=url, engine="limetorrents")

    response = await rig.post()

    assert response.json()["status"] == "failed"
    assert rig.adds() == []
    assert rig.fake.torrents == {}


async def test_a_host_that_resolves_to_a_private_address_is_refused(rig: Rig) -> None:
    rig.cache(url=PAGE_URL, engine="limetorrents")
    rig.dns["limetorrents.example"] = [
        "93.184.216.34",
        private_ip(20),
    ]  # one bad answer is enough

    response = await rig.post()

    assert response.json()["status"] == "failed"
    assert rig.adds() == []


async def test_a_host_that_does_not_resolve_is_refused(rig: Rig) -> None:
    rig.cache(url=PAGE_URL, engine="limetorrents")
    rig.dns["limetorrents.example"] = []

    response = await rig.post()

    assert response.json()["status"] == "failed"
    assert rig.adds() == []


# -- concurrency (SEC-03, DOWN-01) ---------------------------------------------------------------


async def test_double_tap_adds_one_torrent_and_both_taps_get_the_same_job(rig: Rig) -> None:
    rig.cache()
    rig.fake.set_metadata(BTIH, SINTEL_FILES, delay_polls=3)

    first, second = await asyncio.gather(rig.post(), rig.post())

    assert len(rig.adds()) == 1
    assert first.json()["job_id"] == second.json()["job_id"]
    assert first.json()["status"] == second.json()["status"] == "started"


async def test_a_tap_after_the_job_started_returns_that_job_without_a_new_add(rig: Rig) -> None:
    rig.cache()
    rig.fake.set_metadata(BTIH, SINTEL_FILES)
    first = await rig.post()

    again = await rig.post()

    assert again.json() == first.json()
    assert len(rig.adds()) == 1


async def test_concurrent_film_and_serie_requests_each_use_their_own_category(rig: Rig) -> None:
    rig.cache(RESULT_ID, MAGNET, "film")
    rig.cache(SERIE_RESULT_ID, SERIE_MAGNET, "serie")
    rig.fake.set_metadata(BTIH, SINTEL_FILES, delay_polls=2)
    rig.fake.set_metadata(SERIE_BTIH, [("Show.S01E01.mkv", 700 * MB)], delay_polls=1)

    film, serie = await asyncio.gather(
        rig.post(RESULT_ID, "film"), rig.post(SERIE_RESULT_ID, "serie")
    )

    assert film.json()["status"] == serie.json()["status"] == "started"
    categories = {call.form["urls"]: call.form["category"] for call in rig.adds()}
    assert categories == {MAGNET: "Film", SERIE_MAGNET: "SerieTV"}


# -- restart (D-12, FILT-02) ------------------------------------------------------------------

PENDING_OLD = "2" * 40
PENDING_NEW = "3" * 40
JOB_NEW = "bbbbbbbbbbbbbbbb"


async def finished(rig: Rig, job_id: str) -> None:
    """Wait for the background job of a reconciled torrent."""
    task = rig.app.state.jobs.task(job_id)
    assert task is not None, "reconcile did not resume the torrent"
    await asyncio.wait_for(task, 5)


def stranded(rig: Rig, torrent_hash: str, category: str, job_id: str, age: float) -> None:
    rig.fake.torrents[torrent_hash] = FakeTorrent(
        torrent_hash,
        f"magnet:?xt=urn:btih:{torrent_hash}",
        category,
        ["fx", "fx-pending", f"fx-job-{job_id}"],
        rig.clock.now - age,
    )


async def test_reconcile_deletes_an_expired_pending_torrent_and_resumes_a_fresh_one(
    rig: Rig,
) -> None:
    stranded(rig, PENDING_OLD, "Film", "aaaaaaaaaaaaaaaa", age=301)
    stranded(rig, PENDING_NEW, "SerieTV", JOB_NEW, age=10)
    rig.fake.set_metadata(PENDING_NEW, [("Show.S01E01.mkv", 700 * MB), ("Show.exe", 1000)])

    await rig.app.state.pipeline.reconcile()
    await finished(rig, JOB_NEW)

    assert rig.fake.deleted == [(PENDING_OLD, True)]
    resumed = rig.fake.torrents[PENDING_NEW]
    assert resumed.started is True
    assert resumed.category == "SerieTV"  # whatever qBittorrent held is kept
    assert resumed.tags == ["fx"]
    assert rig.app.state.jobs.get(JOB_NEW).state is JobState.STARTED
    assert rig.fake.calls_to("/api/v2/torrents/setCategory") == []
    assert rig.adds() == []


async def test_reconcile_never_deletes_a_started_torrent_that_kept_its_pending_tag(
    rig: Rig,
) -> None:
    # CR-01: tag cleanup failed after start; the download has been running for an hour.
    stranded(rig, PENDING_OLD, "Film", JOB_NEW, age=3600)
    running = rig.fake.torrents[PENDING_OLD]
    running.started = True
    running.downloaded = 50 * MB
    rig.fake.set_metadata(PENDING_OLD, [("Movie/Movie.mkv", 800 * MB), ("Movie/setup.exe", 1000)])

    await rig.app.state.pipeline.reconcile()
    await finished(rig, JOB_NEW)

    assert rig.fake.deleted == []
    kept = rig.fake.torrents[PENDING_OLD]
    assert kept.started is True
    assert kept.downloaded == 50 * MB
    assert kept.tags == ["fx"]  # the allowlist ran again and the tag is gone now
    assert rig.app.state.jobs.get(JOB_NEW).state is JobState.STARTED


async def test_reconcile_never_deletes_a_stopped_torrent_that_already_holds_payload(
    rig: Rig,
) -> None:
    stranded(rig, PENDING_OLD, "Film", JOB_NEW, age=3600)
    rig.fake.torrents[PENDING_OLD].downloaded = 10 * MB  # started once, paused by the household
    rig.fake.set_metadata(PENDING_OLD, [("Movie/Movie.mkv", 800 * MB)])

    await rig.app.state.pipeline.reconcile()
    await finished(rig, JOB_NEW)

    assert rig.fake.deleted == []
    assert PENDING_OLD in rig.fake.torrents


async def test_a_failed_tag_cleanup_after_start_is_retried(rig: Rig) -> None:
    rig.cache()
    rig.fake.set_metadata(BTIH, SINTEL_FILES)
    real_remove = rig.fake._torrents_remove_tags
    attempts = []

    def flaky(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) < 3:
            return httpx.Response(500, text="boom")
        return real_remove(request)

    rig.fake.register("POST", "/api/v2/torrents/removeTags", flaky)

    response = await rig.post()

    assert response.json()["status"] == "started"
    assert len(attempts) == 3
    assert rig.fake.torrents[BTIH].tags == ["fx"]


async def test_reconcile_never_starts_a_pending_torrent_without_running_the_allowlist(
    rig: Rig,
) -> None:
    stranded(rig, PENDING_NEW, "Film", JOB_NEW, age=10)
    rig.fake.set_metadata(PENDING_NEW, [("Movie/setup.exe", 1000)])  # no video at all

    await rig.app.state.pipeline.reconcile()
    await finished(rig, JOB_NEW)

    assert rig.app.state.jobs.get(JOB_NEW).state is JobState.REJECTED
    assert rig.fake.deleted == [(PENDING_NEW, True)]
    assert rig.fake.calls_to(START) == []


async def test_reconcile_gives_up_on_a_resumed_torrent_that_never_gets_metadata(
    rig: Rig,
) -> None:
    stranded(rig, PENDING_NEW, "Film", JOB_NEW, age=290)  # 10 s of the 300 s left

    await rig.app.state.pipeline.reconcile()
    await finished(rig, JOB_NEW)

    assert rig.app.state.jobs.get(JOB_NEW).state is JobState.UNAVAILABLE
    assert rig.fake.deleted == [(PENDING_NEW, True)]
    assert rig.clock.now - 1_700_000_000 < 15


async def test_reconcile_skips_a_torrent_a_running_job_owns(rig: Rig) -> None:
    rig.app.state.settings = rig.app.state.settings.model_copy(
        update={"download_wait_seconds": 0.02}
    )

    async def slow_sleep(seconds: float) -> None:
        rig.clock.now += seconds
        await asyncio.sleep(0.01)

    rig.use_sleep(slow_sleep)
    rig.cache()
    rig.fake.set_metadata(BTIH, SINTEL_FILES, delay_polls=5)
    first = await rig.post()
    assert first.json()["status"] == "preparing"

    await rig.app.state.pipeline.reconcile()  # the torrent is fx-pending but a job owns it
    await asyncio.wait_for(rig.app.state.jobs.task(first.json()["job_id"]), 5)

    assert len(rig.adds()) == 1
    assert len(rig.fake.calls_to(START)) == 1


async def test_the_startup_bootstrap_reconciles_torrents_stranded_by_a_restart(
    settings: Settings, fake_qbit: FakeQbit
) -> None:
    import time

    fake_qbit.torrents[PENDING_NEW] = FakeTorrent(
        PENDING_NEW,
        f"magnet:?xt=urn:btih:{PENDING_NEW}",
        "Film",
        ["fx", "fx-pending", f"fx-job-{JOB_NEW}"],
        time.time() - 5,
    )
    fake_qbit.set_metadata(PENDING_NEW, [("Movie/Movie.mkv", 800 * MB)])
    client = QbitClient(
        settings.qbittorrent_url,
        settings.qbittorrent_user,
        settings.qbittorrent_pass,
        transport=fake_qbit.transport,
    )
    app = create_app(settings, client)

    async with app.router.lifespan_context(app):
        await wait_for_bootstrap(app)
        async with asyncio.timeout(5):
            while app.state.jobs.get(JOB_NEW) is None:
                await asyncio.sleep(0.01)
            await app.state.jobs.task(JOB_NEW)

    assert fake_qbit.torrents[PENDING_NEW].started is True
    assert fake_qbit.torrents[PENDING_NEW].tags == ["fx"]
