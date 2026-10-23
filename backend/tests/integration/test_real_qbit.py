"""Download flow against the real pinned qBittorrent (research A8, FILT-01, FILT-02, DOWN-03).

Only three kinds of torrent are ever added: the Sintel open-movie demo magnet (Blender
Foundation, CC BY 3.0), locally bencoded synthetic torrents, and open-licensed Blender results
found through a magnet-printing plugin (limetorrents or torrentproject). A test deletes (with
files) only what it added itself; a torrent that already exists before the test, such as the
household's real Sintel download, is never touched and makes the Sintel test skip.
"""

import asyncio
import hashlib
import re
import secrets
import time

import httpx
import pytest
from fastapi import FastAPI

from app.config import Settings
from app.download.allowlist import TorrentFile, decide
from app.qbit.client import QbitClient, QbitError
from app.search.service import CachedResult
from tests.integration.conftest import credentials

pytestmark = pytest.mark.integration

SINTEL_BTIH = "08ada5a7a6183aae1e09d831df6748d566095a10"  # CC BY 3.0 Blender Foundation
SINTEL_MAGNET = (
    f"magnet:?xt=urn:btih:{SINTEL_BTIH}&dn=Sintel&tr=udp://tracker.opentrackr.org:1337/announce"
)
RESULT_ID = "5e1c0de5e1c0de01"
PIECE_LENGTH = 16384


def bencode(value: object) -> bytes:
    if isinstance(value, int):
        return b"i%de" % value
    if isinstance(value, bytes):
        return b"%d:%s" % (len(value), value)
    if isinstance(value, str):
        return bencode(value.encode())
    if isinstance(value, list):
        return b"l" + b"".join(bencode(v) for v in value) + b"e"
    if isinstance(value, dict):
        items = sorted((k.encode(), v) for k, v in value.items())
        return b"d" + b"".join(bencode(k) + bencode(v) for k, v in items) + b"e"
    raise TypeError(type(value))


def synthetic_torrent(files: list[tuple[list[str], int]]) -> tuple[bytes, str]:
    """A multi-file .torrent with random pieces, and its info-hash (so it is always new)."""
    total = sum(size for _, size in files)
    pieces = b"".join(secrets.token_bytes(20) for _ in range(-(-total // PIECE_LENGTH)))
    info = {
        "name": "Movie",
        "piece length": PIECE_LENGTH,
        "pieces": pieces,
        "files": [{"length": size, "path": path} for path, size in files],
    }
    return bencode({"info": info}), hashlib.sha1(bencode(info)).hexdigest()


async def torrent_row(qbit: QbitClient, torrent_hash: str) -> dict | None:
    rows = await qbit.torrents_info(hashes=torrent_hash)
    return rows[0] if rows else None


async def wait_until(predicate, seconds: float):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = await predicate()
        if value:
            return value
        await asyncio.sleep(1)
    return None


async def test_sintel_magnet_flow(
    real_app: FastAPI, real_api: httpx.AsyncClient, real_qbit: QbitClient, record_property
) -> None:
    if await torrent_row(real_qbit, SINTEL_BTIH) is not None:
        pytest.skip("the Sintel torrent already exists in qBittorrent; it is never touched")
    real_app.state.search._cache[RESULT_ID] = CachedResult(
        result_id=RESULT_ID,
        engine="test",
        file_url=SINTEL_MAGNET,
        type="film",
        name="Sintel",
        expires_at=float("inf"),
    )
    # A8 evidence: how much payload qBittorrent holds the instant before the start call.
    evidence: list[int] = []
    real_start = real_app.state.qbit.start

    async def spy_start(hashes):
        rows = await real_app.state.qbit.torrents_info(hashes=hashes)
        evidence.append(int(rows[0]["downloaded"]))
        await real_start(hashes)

    real_app.state.qbit.start = spy_start

    added_by_test = True
    try:
        response = await real_api.post(
            "/api/download", json={"result_id": RESULT_ID, "type": "film"}
        )
        assert response.status_code == 200, response.text
        assert set(response.json()) == {"status", "job_id"}
        job_id = response.json()["job_id"]

        async def finished():
            body = (await real_api.get(f"/api/download/{job_id}")).json()
            return body["status"] if body["status"] != "preparing" else None

        outcome = await wait_until(finished, 90)
        assert outcome == "started", f"job ended as {outcome!r}"

        row = await torrent_row(real_qbit, SINTEL_BTIH)
        assert row is not None
        assert row["category"] == "Film"
        assert row["save_path"].rstrip("/") == "/data/quarantine/Film"
        tags = {t.strip() for t in row["tags"].split(",")}
        assert "fx" in tags and "fx-pending" not in tags
        files = {f["name"]: f["priority"] for f in await real_qbit.torrent_files(SINTEL_BTIH)}
        assert files["Sintel/Sintel.mp4"] >= 1
        assert files["Sintel/poster.jpg"] == 0
        subtitles = [name for name in files if name.lower().endswith(".srt")]
        assert subtitles, "the Sintel torrent is expected to carry subtitles"
        assert all(files[name] >= 1 for name in subtitles)
        assert evidence, "start was never called"
        record_property("downloaded_bytes_before_start", evidence[0])
        print(f"A8 evidence: downloaded={evidence[0]} bytes just before torrents/start")
        # The guarantee itself (WR-04): not one payload byte before the allowlist ran.
        assert evidence[0] == 0, f"{evidence[0]} payload bytes were downloaded before start"
    finally:
        real_app.state.qbit.start = real_start
        if added_by_test:
            await real_qbit.delete([SINTEL_BTIH], True)


async def test_synthetic_torrent_exclusions(real_settings: Settings, real_app: FastAPI) -> None:
    user, password = credentials()
    layout = [
        (["Movie.mkv"], 100_000),
        (["setup.exe"], 1_000),
        (["Movie.mkv.exe"], 1_000),
        (["SETUP.EXE"], 1_000),
        (["readme.txt"], 500),
        (["Sample", "sample.mkv"], 5_000),
    ]
    payload, torrent_hash = synthetic_torrent(layout)
    qbit: QbitClient = real_app.state.qbit
    async with httpx.AsyncClient(base_url=real_settings.qbittorrent_url) as http:
        login = await http.post("/api/v2/auth/login", data={"username": user, "password": password})
        assert login.status_code in (200, 204) and login.text.strip() != "Fails."
        try:
            added = await http.post(
                "/api/v2/torrents/add",
                files={"torrents": ("movie.torrent", payload, "application/x-bittorrent")},
                data={"category": "Film", "autoTMM": "true", "stopCondition": "MetadataReceived"},
            )
            assert added.status_code == 200, added.status_code

            async def listed():
                try:
                    return await qbit.torrent_files(torrent_hash)
                except QbitError:  # the torrent is not registered yet
                    return []

            rows = await wait_until(listed, 20)
            assert rows, "qBittorrent never listed the synthetic torrent's files"
            priorities = {row["name"]: row["priority"] for row in rows}
            # FILT-01 on the real engine: the exclusion list is active at add time.
            assert priorities["Movie/setup.exe"] == 0
            assert priorities["Movie/Movie.mkv.exe"] == 0
            assert priorities["Movie/SETUP.EXE"] == 0
            decision = decide([TorrentFile.from_qbit(row) for row in rows])
            kept = {row["name"] for row in rows if row["index"] in decision.keep_ids}
            assert decision.accept
            assert kept == {"Movie/Movie.mkv"}
        finally:
            await qbit.delete([torrent_hash], True)


STOPPED_STATES = {"stoppedDL", "pausedDL"}
LAYOUT = [
    (["Movie.mkv"], 100_000),
    (["setup.exe"], 1_000),
    (["readme.txt"], 500),
    (["Sample", "sample.mkv"], 5_000),
]


async def add_synthetic(real_settings: Settings, payload: bytes, data: dict) -> None:
    user, password = credentials()
    async with httpx.AsyncClient(base_url=real_settings.qbittorrent_url) as http:
        login = await http.post("/api/v2/auth/login", data={"username": user, "password": password})
        assert login.status_code in (200, 204) and login.text.strip() != "Fails."
        added = await http.post(
            "/api/v2/torrents/add",
            files={"torrents": ("movie.torrent", payload, "application/x-bittorrent")},
            data=data,
        )
        assert added.status_code == 200, added.status_code


async def listed_files(qbit: QbitClient, torrent_hash: str) -> list[dict]:
    async def listed():
        try:
            return await qbit.torrent_files(torrent_hash)
        except QbitError:  # the torrent is not registered yet
            return []

    rows = await wait_until(listed, 20)
    assert rows, "qBittorrent never listed the synthetic torrent's files"
    return rows


async def test_a_metadata_complete_torrent_added_with_the_stop_condition_holds_still_until_the_pipeline_starts_it(
    real_settings: Settings, real_app: FastAPI, real_qbit: QbitClient
) -> None:
    """The .torrent routes: a torrent that has its metadata at add, with the portal's add form.

    qBittorrent 5.2.4 adds such a torrent paused under `stopCondition=MetadataReceived`
    (sessionimpl.cpp:2794-2801). Before the start it must be in a stopped state with zero payload
    and a readable file list. Then `reconcile`'s resume path, which is the same `_process` the
    download job runs, filters and starts it: allowlist, priorities, verify, start.
    """
    job_id = secrets.token_hex(8)
    payload, torrent_hash = synthetic_torrent(LAYOUT)
    try:
        await add_synthetic(
            real_settings,
            payload,
            {
                "category": "Film",
                "autoTMM": "true",
                "stopCondition": "MetadataReceived",
                "tags": f"fx,fx-pending,fx-job-{job_id}",
            },
        )
        rows = await listed_files(real_qbit, torrent_hash)

        async def stopped():
            row = await torrent_row(real_qbit, torrent_hash)
            assert row is not None
            assert int(row["downloaded"]) == 0
            # checkingResumeData is the moment right after the add, before the stopped state.
            return row if row["state"] in STOPPED_STATES else None

        assert await wait_until(stopped, 20), "the torrent never settled in a stopped state"
        assert {r["name"] for r in rows} >= {"Movie/Movie.mkv", "Movie/setup.exe"}

        await real_app.state.pipeline.reconcile()
        task = real_app.state.jobs.task(job_id)
        assert task is not None, "reconcile did not resume the torrent"
        await asyncio.wait_for(task, 60)

        assert real_app.state.jobs.get(job_id).state.value == "started"
        priorities = {r["name"]: r["priority"] for r in await real_qbit.torrent_files(torrent_hash)}
        assert priorities["Movie/Movie.mkv"] >= 1
        assert priorities["Movie/setup.exe"] == 0
        assert priorities["Movie/readme.txt"] == 0
        assert priorities["Movie/Sample/sample.mkv"] == 0

        async def running():
            row = await torrent_row(real_qbit, torrent_hash)
            return row if row is not None and row["state"] not in STOPPED_STATES else None

        after = await wait_until(running, 20)
        assert after is not None, "the torrent never left the stopped state after start"
        assert {t.strip() for t in after["tags"].split(",")} == {"fx"}
    finally:
        await real_qbit.delete([torrent_hash], True)


# The only titles this guard may ever download: the Blender open movies (CC BY). Keep this
# list equal to OPEN_LICENSED in scripts/smoke.py.
OPEN_LICENSED = re.compile(
    r"\b(big[ ._-]?buck[ ._-]?bunny|sintel|tears[ ._-]?of[ ._-]?steel"
    r"|elephants?[ ._-]?dream|cosmos[ ._-]?laundromat)\b",
    re.IGNORECASE,
)
# Plugins whose downloader prints a magnet instead of a .torrent path (G-01-3).
MAGNET_PRINTING = {"limetorrents", "torrentproject"}
PLUGIN_QUERIES = ("Tears of Steel", "Sintel", "Big Buck Bunny")
METADATA_FETCHING_STATES = {"metaDL", "forcedMetaDL"}
SEARCH_WAIT_SECONDS = 45


async def find_magnet_printing_result(
    real_app: FastAPI, real_api: httpx.AsyncClient
) -> tuple[str, str] | None:
    """(result_id, plugin) of an open-licensed result whose cached URL is a page, not a magnet."""
    for query in PLUGIN_QUERIES:
        started = await real_api.post("/api/search", json={"q": query, "type": "film"})
        assert started.status_code == 200, started.text
        search_id = started.json()["search_id"]
        deadline = time.monotonic() + SEARCH_WAIT_SECONDS
        body: dict = {}
        while time.monotonic() < deadline:
            body = (await real_api.get(f"/api/search/{search_id}")).json()
            if body["done"]:
                break
            await asyncio.sleep(1)
        for row in body.get("results", []):
            if row["source"] not in MAGNET_PRINTING or not OPEN_LICENSED.search(row["name"]):
                continue
            cached = real_app.state.search.get_result(row["result_id"])
            if cached is not None and not cached.file_url.lower().startswith("magnet:"):
                return row["result_id"], row["source"]
    return None


async def test_a_plugin_result_whose_downloader_prints_a_magnet_fetches_metadata_with_zero_payload(
    real_settings: Settings,
    real_app: FastAPI,
    real_api: httpx.AsyncClient,
    real_qbit: QbitClient,
    record_property,
) -> None:
    """The route UAT test 3 failed on (G-01-3): a page result whose downloader prints a magnet.

    The torrent must fetch its metadata (never sit stopped without it) and must hold no payload
    when the pipeline decides: before `start` for an accepted torrent, before `delete` for a
    rejected one.
    """
    found = await find_magnet_printing_result(real_app, real_api)
    if found is None:
        pytest.skip(
            "no open-licensed Blender result from limetorrents or torrentproject for "
            + ", ".join(PLUGIN_QUERIES)
        )
    result_id, plugin = found
    before = {str(row["hash"]) for row in await real_qbit.torrents_info()}
    held_before: dict[str, list[int]] = {"start": [], "delete": []}
    qbit: QbitClient = real_app.state.qbit
    real_start, real_delete = qbit.start, qbit.delete

    def spy(kind: str, real):
        async def wrapper(hashes, *args):
            for row in await qbit.torrents_info(hashes=hashes):
                held_before[kind].append(int(row["downloaded"]))
            return await real(hashes, *args)

        return wrapper

    qbit.start = spy("start", real_start)
    qbit.delete = spy("delete", real_delete)
    job_id: str | None = None
    try:
        response = await real_api.post(
            "/api/download", json={"result_id": result_id, "type": "film"}
        )
        assert response.status_code == 200, response.text
        job_id = response.json()["job_id"]
        observed: list[tuple[str, bool]] = []
        stuck_polls = 0
        outcome = response.json()["status"]
        deadline = time.monotonic() + real_settings.metadata_timeout + 30
        while outcome == "preparing" and time.monotonic() < deadline:
            await asyncio.sleep(2)
            outcome = (await real_api.get(f"/api/download/{job_id}")).json()["status"]
            for row in await real_qbit.torrents_info(tag=f"fx-job-{job_id}"):
                try:
                    has_metadata = bool(await real_qbit.torrent_files(str(row["hash"])))
                except QbitError:
                    has_metadata = False
                observed.append((str(row["state"]), has_metadata))
                # A stopped magnet can never fetch metadata: that is the G-01-3 defect. Two polls
                # in a row, so the moment metadata arrives and the torrent stops is not mistaken.
                if row["state"] in STOPPED_STATES and not has_metadata:
                    stuck_polls += 1
                    assert stuck_polls < 2, f"torrent sits stopped without metadata: {observed}"
                else:
                    stuck_polls = 0
        decided = held_before["start"] or held_before["delete"]
        record_property("plugin", plugin)
        record_property("outcome", outcome)
        record_property("downloaded_before_decision", decided[0] if decided else None)
        print(f"G-01-3 evidence: plugin={plugin} outcome={outcome} downloaded={decided}")
        if outcome == "started":
            assert held_before["start"] == [0], held_before
        elif outcome in ("rejected", "unsupported"):
            assert held_before["delete"] and set(held_before["delete"]) == {0}, held_before
        elif outcome == "duplicate":
            pytest.skip("the torrent is already in qBittorrent; it is never touched")
        elif outcome == "unavailable" and observed:
            if all(state in METADATA_FETCHING_STATES for state, _ in observed):
                pytest.skip(
                    "no peers sent metadata before METADATA_TIMEOUT; the add itself was correct"
                )
            pytest.fail(f"unavailable with states {observed}")
        else:
            pytest.fail(f"job ended as {outcome!r} with states {observed}")
    finally:
        qbit.start, qbit.delete = real_start, real_delete
        job = real_app.state.jobs.get(job_id) if job_id else None
        job_hash = job.torrent_hash if job else None
        if job_hash and job_hash not in before and await torrent_row(real_qbit, job_hash):
            await real_qbit.delete([job_hash], True)
