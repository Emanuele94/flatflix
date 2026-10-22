"""Download flow against the real pinned qBittorrent (research A8, FILT-01, FILT-02, DOWN-03).

Only two torrents are ever added: the Sintel open-movie demo magnet (Blender Foundation,
CC BY 3.0) and a locally bencoded synthetic torrent. Both are deleted with their files at the
end, and a torrent that already exists before the test is never touched.
"""

import asyncio
import hashlib
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
    assert await torrent_row(real_qbit, SINTEL_BTIH) is None, (
        "the Sintel torrent already exists in qBittorrent; remove it and rerun"
    )
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
        assert row["save_path"].rstrip("/") == "/media/Film"
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
    finally:
        real_app.state.qbit.start = real_start
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
                data={"category": "Film", "autoTMM": "true", "stopped": "true"},
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
