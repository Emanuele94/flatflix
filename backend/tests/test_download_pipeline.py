"""Download pipeline through the API: add, metadata, allowlist, priorities, start (DOWN-01..03).

The fake qBittorrent keeps real torrent state, so every assertion is about what the backend
sent (call log) or what the fake ended up holding, never about internal calls.
"""

import asyncio
from dataclasses import dataclass

import httpx
import pytest
from fastapi import FastAPI

from app.download.pipeline import DownloadPipeline
from app.search.service import CachedResult
from tests.fakeqbit import FakeQbit

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
            state.qbit, state.settings, state.search, state.jobs, clock=self.clock, sleep=sleep
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
