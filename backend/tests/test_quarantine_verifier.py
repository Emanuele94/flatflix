"""The verifier (QUAR-01, QUAR-02, QUAR-04, QUAR-05, D-45..D-54, D-58, D-63).

A rig wires FakeQbit, FakeRunner and a real folder under `tmp_path`: files are sparse, so a 4 GB
film costs nothing. Tests watch what reaches the media folder, what the fake qBittorrent was told
(`addTags`, `delete`) and what the fake runner was asked to probe.
"""

import os
from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import SecretStr

from app.config import Settings
from app.qbit.client import QbitClient
from app.quarantine.runner_client import RunnerClient
from app.quarantine.verifier import Verifier
from tests.conftest import PORTAL_PASS_HASH, QBIT_PASS, QBIT_USER
from tests.fakeqbit import FakeQbit
from tests.fakerunner import FakeRunner, film_facts

NOW = 1_700_000_000.0
FILM_HASH = "a" * 40
GB = 1_000_000_000


def make_settings(tmp_path: Path, **overrides) -> Settings:
    data = tmp_path / "data"
    values = {
        "qbittorrent_url": "http://qbittorrent.test:8088",
        "qbittorrent_user": QBIT_USER,
        "qbittorrent_pass": SecretStr(QBIT_PASS),
        "app_user": "famiglia-test",
        "app_pass_hash": SecretStr(PORTAL_PASS_HASH),
        "secret_key": SecretStr("test-secret-key-0123456789abcdefghij"),
        "data_path": str(data),
        "save_path_film": str(data / "quarantine" / "Film"),
        "save_path_tv": str(data / "quarantine" / "SerieTV"),
        "incomplete_path": str(data / "incomplete"),
    }
    values.update(overrides)
    return Settings(**values)


def put_file(path: Path, size: int) -> Path:
    """A sparse file of `size` bytes: no disk is used, but stat reports the full size."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as handle:
        handle.truncate(size)
    return path


@dataclass
class Rig:
    settings: Settings
    fake: FakeQbit
    runner: FakeRunner
    verifier: Verifier
    qbit: QbitClient
    runner_client: RunnerClient

    @property
    def quarantine(self) -> Path:
        return Path(self.settings.quarantine_root)

    @property
    def media(self) -> Path:
        return Path(self.settings.media_root)

    def add_finished(
        self,
        torrent_hash: str,
        name: str,
        files: list[tuple[str, int]],
        *,
        category: str = "Film",
        state: str = "stalledUP",
        completion_on: int = 100,
        tags: tuple[str, ...] = (),
        on_disk: bool = True,
    ) -> None:
        """A finished torrent with its files (sparse) on disk under its category's save path."""
        save_path = self.settings.category_paths[category]
        self.fake.add_torrent_row(
            torrent_hash,
            name=name,
            category=category,
            tags=tags,
            state=state,
            progress=1.0,
            completion_on=completion_on,
            save_path=save_path,
        )
        self.fake.set_metadata(torrent_hash, files, progress=1.0)
        if on_disk:
            for file_name, size in files:
                put_file(Path(save_path) / file_name, size)


@pytest.fixture
async def rig(tmp_path: Path):
    settings = make_settings(tmp_path)
    fake = FakeQbit(QBIT_USER, QBIT_PASS)
    runner = FakeRunner()
    qbit = QbitClient(
        settings.qbittorrent_url,
        settings.qbittorrent_user,
        settings.qbittorrent_pass,
        transport=fake.transport,
    )
    runner_client = RunnerClient(settings.sandbox_url, transport=runner.transport)
    verifier = Verifier(qbit, runner_client, settings, clock=lambda: NOW)
    yield Rig(settings, fake, runner, verifier, qbit, runner_client)
    await qbit.aclose()
    await runner_client.aclose()


# --- Task 1: the tracer ----------------------------------------------------------------------------


async def test_a_finished_film_in_quarantine_is_probed_hardlinked_and_tagged(rig: Rig) -> None:
    rig.add_finished(FILM_HASH, "Movie", [("Movie/movie.mkv", 4 * GB)])
    rig.runner.script("Film/Movie/movie.mkv", film_facts(duration=6000.0))

    await rig.verifier.run_once()

    linked = rig.media / "Film" / "Movie" / "movie.mkv"
    source = rig.quarantine / "Film" / "Movie" / "movie.mkv"
    assert linked.exists()
    assert os.stat(linked).st_ino == os.stat(source).st_ino
    assert os.stat(source).st_nlink == 2  # a hardlink, not a copy; the torrent keeps seeding
    tag_calls = rig.fake.calls_to("/api/v2/torrents/addTags")
    assert [(c.form["hashes"], c.form["tags"]) for c in tag_calls] == [
        (FILM_HASH, "fx-ok-1700000000")
    ]
    assert rig.fake.deleted == []

    await rig.verifier.run_once()  # now tagged: not a candidate any more

    assert rig.runner.calls == ["Film/Movie/movie.mkv"]
