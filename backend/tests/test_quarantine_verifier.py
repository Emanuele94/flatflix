"""The verifier (QUAR-01, QUAR-02, QUAR-04, QUAR-05, D-45..D-54, D-58, D-63).

A rig wires FakeQbit, FakeRunner and a real folder under `tmp_path`: files are sparse, so a 4 GB
film costs nothing. Tests watch what reaches the media folder, what the fake qBittorrent was told
(`addTags`, `delete`) and what the fake runner was asked to probe.
"""

import asyncio
import json
import logging
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.download.listing import download_id
from app.main import create_app
from app.qbit.bootstrap import Readiness
from app.qbit.client import QbitClient
from app.quarantine import handoff
from app.quarantine import verifier as verifier_module
from app.quarantine.guard import HandoffGuard
from app.quarantine.handoff import HandoffError, link_into_media, media_target, source_path
from app.quarantine.runner_client import RunnerClient
from app.quarantine.verifier import Verifier, is_candidate
from tests.conftest import PORTAL_PASS_HASH, QBIT_PASS, QBIT_USER, wait_for_bootstrap
from tests.fakeqbit import FakeQbit
from tests.fakerunner import FakeRunner, failed_facts, film_facts

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


class TrackingRunner(FakeRunner):
    """A FakeRunner that counts probes in flight and can hold the answer until `hold` is set."""

    def __init__(self) -> None:
        super().__init__()
        self.in_flight = 0
        self.max_in_flight = 0
        self.hold: asyncio.Event | None = None
        self.started = asyncio.Event()

    async def handler(self, request: httpx.Request) -> httpx.Response:  # type: ignore[override]
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            if self.hold is not None:
                self.started.set()
                await self.hold.wait()
            else:
                await asyncio.sleep(0)
            return super().handler(request)
        finally:
            self.in_flight -= 1


@dataclass
class Rig:
    settings: Settings
    fake: FakeQbit
    runner: TrackingRunner
    verifier: Verifier
    qbit: QbitClient
    runner_client: RunnerClient
    guard: HandoffGuard = field(default_factory=HandoffGuard)

    def make_verifier(self, **kwargs) -> Verifier:
        kwargs.setdefault("guard", self.guard)
        kwargs.setdefault("clock", lambda: NOW)
        return Verifier(self.qbit, self.runner_client, self.settings, **kwargs)

    async def only_row(self, torrent_hash: str = FILM_HASH) -> dict:
        (row,) = await self.qbit.torrents_info(hashes=torrent_hash)
        return row

    def tag_calls(self) -> list:
        return self.fake.calls_to("/api/v2/torrents/addTags")

    def media_files(self) -> list[str]:
        return sorted(str(p.relative_to(self.media)) for p in self.media.rglob("*") if p.is_file())

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
        progress: float = 1.0,
        save_path: str | None = None,
    ) -> None:
        """A finished torrent with its files (sparse) on disk under its category's save path."""
        if save_path is None:
            save_path = self.settings.category_paths.get(category, self.settings.save_path_film)
        self.fake.add_torrent_row(
            torrent_hash,
            name=name,
            category=category,
            tags=tags,
            state=state,
            progress=progress,
            completion_on=completion_on,
            save_path=save_path,
        )
        self.fake.set_metadata(torrent_hash, files, progress=progress)
        if on_disk:
            for file_name, size in files:
                put_file(Path(save_path) / file_name, size)


@pytest.fixture
async def rig(tmp_path: Path):
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
    verifier = Verifier(qbit, runner_client, settings, guard=guard, clock=lambda: NOW)
    yield Rig(settings, fake, runner, verifier, qbit, runner_client, guard)
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


# --- Task 2: waiting, restarts, cancel, changed files, the loop and the lifespan -------------------

FILM_FILE = "Movie/movie.mkv"
FILM_REL = "Film/Movie/movie.mkv"
INFO = "/api/v2/torrents/info"
FILES = "/api/v2/torrents/files"


def audit_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == "app.audit"]


def add_film(rig: Rig, **kwargs) -> None:
    rig.add_finished(FILM_HASH, "Movie", [(FILM_FILE, 4 * GB)], **kwargs)
    rig.runner.script(FILM_REL, film_facts(duration=6000.0))


async def test_runner_unavailable_waits_and_one_outage_writes_one_audit_line(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="app.audit")
    add_film(rig)
    rig.runner.unreachable = True

    for _ in range(3):
        await rig.verifier.run_once()

    assert rig.verifier.runner_down == "unreachable"
    assert rig.media_files() == []
    assert rig.tag_calls() == []
    assert rig.fake.deleted == []
    assert audit_lines(caplog) == ["event=quarantine.runner_unavailable why=unreachable"]

    rig.runner.unreachable = False
    await rig.verifier.run_once()  # the runner answers again: the next tick hands off

    assert rig.verifier.runner_down is None
    assert rig.media_files() == ["Film/Movie/movie.mkv"]
    assert len(rig.tag_calls()) == 1


async def test_runner_down_503_names_its_reason_and_stops_the_tick(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="app.audit")
    add_film(rig)
    rig.runner.script(FILM_REL, ("down", "kvm"))
    rig.add_finished("b" * 40, "Other", [("Other/o.mkv", GB)], completion_on=200)
    rig.runner.script("Film/Other/o.mkv", film_facts(duration=3000.0, size=GB))

    await rig.verifier.run_once()

    assert rig.verifier.runner_down == "kvm"
    assert rig.runner.calls == [FILM_REL]  # the tick stopped: the second torrent was not probed
    assert rig.media_files() == []
    assert audit_lines(caplog) == ["event=quarantine.runner_unavailable why=kvm"]


async def test_a_renamed_executable_fails_twice_and_is_held_owner_only_then_deleted(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="app.audit")
    rig.add_finished(FILM_HASH, "Movie", [(FILM_FILE, 8 * 1024 * 1024)])
    rig.runner.script(FILM_REL, failed_facts("probe_failed"))
    outcome_id = download_id(rig.settings.secret_key.get_secret_value(), FILM_HASH)

    outcome = await rig.verifier.check_torrent(await rig.only_row())

    assert outcome == "rejected"
    assert rig.runner.calls == [FILM_REL, FILM_REL]  # probed once more in a fresh VM (D-57)
    held = Path(rig.settings.rejected_root) / outcome_id / "Movie" / "movie.mkv"
    assert held.exists()
    assert stat.S_IMODE(os.stat(held.parent).st_mode) & 0o077 == 0  # the folder is the barrier
    assert stat.S_IMODE(os.stat(held.parent).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(held.parent.parent).st_mode) == 0o700
    sidecar = Path(rig.settings.rejected_root) / f"{outcome_id}.json"
    stored = json.loads(sidecar.read_text())
    assert set(stored) == {"id", "name", "type", "kind", "skipped", "at"}
    assert (stored["id"], stored["name"], stored["type"]) == (outcome_id, "Movie", "film")
    assert (stored["kind"], stored["skipped"], stored["at"]) == ("rejected", 1, NOW)
    assert stat.S_IMODE(os.stat(sidecar).st_mode) == 0o600
    assert rig.fake.deleted == [(FILM_HASH, True)]
    assert rig.media_files() == []
    assert rig.tag_calls() == []
    (line,) = audit_lines(caplog)
    assert "event=quarantine.rejected" in line
    assert "reason=probe_failed" in line
    assert 'file="Movie/movie.mkv"' in line
    assert "size=8388608" in line
    assert "/data" not in line
    assert FILM_HASH not in line


async def test_a_file_the_runner_refuses_is_unprobeable_and_rejected_without_a_retry(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="app.audit")
    rig.add_finished(FILM_HASH, "Movie", [(FILM_FILE, 4 * GB)])
    rig.runner.script(FILM_REL, 409)  # not_regular_file: about this file only

    outcome = await rig.verifier.check_torrent(await rig.only_row())

    assert outcome == "rejected"
    assert rig.runner.calls == [FILM_REL]  # a refused path is not retried
    assert rig.media_files() == []
    assert rig.fake.deleted == [(FILM_HASH, True)]
    (line,) = audit_lines(caplog)
    assert "reason=unprobeable" in line
    assert "format=none codec=none duration=none" in line


@pytest.mark.parametrize("status", [400, 404])
async def test_a_runner_that_does_not_see_the_file_is_a_host_fault_never_a_verdict(
    rig: Rig, caplog: pytest.LogCaptureFixture, status: int
) -> None:
    """CR-02: the backend lstat'ed the file, so a 400/404 means the runner sees another
    quarantine folder (stale bind mount, other version). Nothing may be rejected or deleted."""
    caplog.set_level(logging.INFO, logger="app.audit")
    add_film(rig)
    rig.runner.script(FILM_REL, status)
    rig.add_finished("b" * 40, "Other", [("Other/o.mkv", GB)], completion_on=200)
    rig.runner.script("Film/Other/o.mkv", film_facts(duration=3000.0, size=GB))

    for _ in range(2):
        await rig.verifier.run_once()

    assert rig.verifier.runner_down == "path_mismatch"
    assert rig.runner.calls == [FILM_REL, FILM_REL]  # one probe per tick, the queue waits
    assert rig.fake.deleted == []
    assert rig.media_files() == []
    assert not list(Path(rig.settings.rejected_root).glob("*.json"))
    assert audit_lines(caplog) == ["event=quarantine.runner_unavailable why=path_mismatch"]

    rig.runner.script(FILM_REL, film_facts(duration=6000.0, size=4_000_000_000))
    await rig.verifier.run_once()  # the host is fixed: the same torrent is checked normally

    assert rig.verifier.runner_down is None
    assert "Film/Movie/movie.mkv" in rig.media_files()


NOT_CANDIDATES = {
    "still downloading": {"state": "downloading", "progress": 0.5},
    "re-hashing": {"state": "checkingUP"},
    "other category": {"category": "Other"},
    "sub-category": {"category": "Film/Extra"},
    "legacy save path in media": {"save_path": "MEDIA/Film"},
    "save path outside the data folder": {"save_path": "OUTSIDE"},
    "already verified": {"tags": ("fx-ok-123",)},
}


@pytest.mark.parametrize("case", sorted(NOT_CANDIDATES))
async def test_a_torrent_that_is_not_a_candidate_is_never_probed(rig: Rig, case: str) -> None:
    options = dict(NOT_CANDIDATES[case])
    if options.get("save_path") == "MEDIA/Film":
        options["save_path"] = str(rig.media / "Film")
    if options.get("save_path") == "OUTSIDE":
        options["save_path"] = str(Path(rig.settings.data_path).parent / "elsewhere")
    rig.add_finished(FILM_HASH, "Movie", [(FILM_FILE, 4 * GB)], **options)
    rig.runner.script(FILM_REL, film_facts(duration=6000.0))
    media_before = rig.media_files()

    await rig.verifier.run_once()

    assert rig.fake.calls_to(FILES) == []  # never even looked at its files
    assert rig.runner.calls == []
    assert rig.tag_calls() == []
    assert rig.fake.deleted == []
    assert rig.media_files() == media_before


async def test_is_candidate_is_exact_about_category_state_save_path_and_tag(rig: Rig) -> None:
    good = {
        "category": "SerieTV",
        "state": "uploading",
        "save_path": rig.settings.save_path_tv,
        "tags": "fx, other",
    }
    assert is_candidate(good, rig.settings)
    assert not is_candidate(dict(good, category="serietv"), rig.settings)
    assert not is_candidate(dict(good, save_path=rig.settings.quarantine_root), rig.settings)
    assert not is_candidate(dict(good, save_path=""), rig.settings)
    assert not is_candidate(dict(good, tags="fx, fx-ok-1700000000"), rig.settings)
    assert not is_candidate(dict(good, state="stoppedDL"), rig.settings)


async def test_an_admin_added_series_is_verified_like_a_portal_one(rig: Rig) -> None:
    rig.add_finished(
        "c" * 40,
        "Show.S01",
        [("Show.S01/Show.S01E01.mkv", 700_000_000), ("Show.S01/Show.S01E02.mkv", 700_000_000)],
        category="SerieTV",
        tags=(),  # no fx tags at all: added in the qBittorrent WebUI
    )
    for episode in ("E01", "E02"):
        rig.runner.script(
            f"SerieTV/Show.S01/Show.S01{episode}.mkv",
            film_facts(duration=3000.0, size=700_000_000),
        )

    await rig.verifier.run_once()

    assert rig.media_files() == [
        "SerieTV/Show.S01/Show.S01E01.mkv",
        "SerieTV/Show.S01/Show.S01E02.mkv",
    ]
    assert len(rig.tag_calls()) == 1
    assert rig.runner.calls == [
        "SerieTV/Show.S01/Show.S01E01.mkv",
        "SerieTV/Show.S01/Show.S01E02.mkv",
    ]  # files in index order


async def test_a_text_subtitle_is_screened_without_the_vm_and_linked_with_the_film(
    rig: Rig,
) -> None:
    rig.add_finished(FILM_HASH, "Movie", [(FILM_FILE, 4 * GB), ("Movie/movie.en.srt", 64)])
    (Path(rig.settings.save_path_film) / "Movie/movie.en.srt").write_text(
        "1\n00:00:01,000 --> 00:00:02,000\nHello\n"
    )
    rig.runner.script(FILM_REL, film_facts(duration=6000.0))

    await rig.verifier.run_once()

    assert rig.runner.calls == [FILM_REL]  # the subtitle never reaches the VM
    assert rig.media_files() == ["Film/Movie/movie.en.srt", "Film/Movie/movie.mkv"]


async def test_a_restart_after_a_half_finished_hand_off_links_the_rest_without_duplicates(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig.add_finished(
        "c" * 40,
        "Show.S01",
        [("Show.S01/Show.S01E01.mkv", 700_000_000), ("Show.S01/Show.S01E02.mkv", 700_000_000)],
        category="SerieTV",
    )
    for episode in ("E01", "E02"):
        rig.runner.script(
            f"SerieTV/Show.S01/Show.S01{episode}.mkv",
            film_facts(duration=3000.0, size=700_000_000),
        )
    real_link = handoff.link_into_media
    links = []

    def second_link_fails(src, dst, **kwargs):
        links.append(dst)
        if len(links) == 2:
            raise HandoffError("EIO")
        return real_link(src, dst, **kwargs)

    monkeypatch.setattr(verifier_module, "link_into_media", second_link_fails)
    await rig.verifier.run_once()  # crashes after the first link

    assert rig.media_files() == ["SerieTV/Show.S01/Show.S01E01.mkv"]
    assert rig.tag_calls() == []  # still Checking

    monkeypatch.setattr(verifier_module, "link_into_media", real_link)
    restarted = rig.make_verifier(guard=HandoffGuard())
    await restarted.run_once()

    assert rig.media_files() == [
        "SerieTV/Show.S01/Show.S01E01.mkv",
        "SerieTV/Show.S01/Show.S01E02.mkv",
    ]
    for name in ("Show.S01E01.mkv", "Show.S01E02.mkv"):
        source = Path(rig.settings.save_path_tv) / "Show.S01" / name
        assert os.stat(source).st_nlink == 2  # one link in media each, never a second one
    assert len(rig.tag_calls()) == 1


async def test_candidates_are_checked_oldest_completion_first_one_probe_at_a_time(
    rig: Rig,
) -> None:
    rig.add_finished("b" * 40, "Newer", [("Newer/n.mkv", GB)], completion_on=200)
    rig.add_finished("c" * 40, "Older", [("Older/o.mkv", GB)], completion_on=100)
    for name in ("Newer/n.mkv", "Older/o.mkv"):
        rig.runner.script(f"Film/{name}", film_facts(duration=3000.0, size=GB))

    await rig.verifier.run_once()

    assert rig.runner.calls == ["Film/Older/o.mkv", "Film/Newer/n.mkv"]
    assert rig.runner.max_in_flight == 1


async def test_a_cancel_requested_before_the_tick_aborts_without_a_probe(rig: Rig) -> None:
    add_film(rig)
    rig.guard.request_cancel(FILM_HASH)

    outcome = await rig.verifier.check_torrent(await rig.only_row())
    await rig.verifier.run_once()

    assert outcome == "aborted"
    assert rig.runner.calls == []
    assert rig.media_files() == []
    assert rig.tag_calls() == []


async def test_a_cancel_requested_during_the_probe_links_nothing(rig: Rig) -> None:
    add_film(rig)
    rig.runner.hold = asyncio.Event()
    task = asyncio.create_task(rig.verifier.check_torrent(await rig.only_row()))
    await asyncio.wait_for(rig.runner.started.wait(), 5)

    rig.guard.request_cancel(FILM_HASH)
    rig.runner.hold.set()

    assert await asyncio.wait_for(task, 5) == "aborted"
    assert rig.media_files() == []
    assert rig.tag_calls() == []


async def test_a_torrent_deleted_during_the_probe_links_nothing(rig: Rig) -> None:
    add_film(rig)
    rig.runner.hold = asyncio.Event()
    task = asyncio.create_task(rig.verifier.check_torrent(await rig.only_row()))
    await asyncio.wait_for(rig.runner.started.wait(), 5)

    del rig.fake.torrents[FILM_HASH]
    rig.runner.hold.set()

    assert await asyncio.wait_for(task, 5) == "aborted"
    assert rig.media_files() == []
    assert rig.tag_calls() == []


async def test_a_file_changed_between_probe_and_hand_off_is_not_linked_until_probed_again(
    rig: Rig,
) -> None:
    add_film(rig)
    source = Path(rig.settings.save_path_film) / FILM_FILE
    row = await rig.only_row()
    rig.runner.hold = asyncio.Event()
    task = asyncio.create_task(rig.verifier.check_torrent(row))
    await asyncio.wait_for(rig.runner.started.wait(), 5)

    os.utime(source, ns=(1_000_000_000, 1_000_000_000))  # swapped while the VM was looking
    rig.runner.hold.set()

    assert await asyncio.wait_for(task, 5) == "aborted"
    assert rig.media_files() == []
    assert rig.tag_calls() == []

    rig.runner.hold = None
    assert await rig.verifier.check_torrent(row) == "passed"  # probed again, then handed off
    assert rig.runner.calls == [FILM_REL, FILM_REL]
    assert rig.media_files() == ["Film/Movie/movie.mkv"]


async def test_cancel_flags_of_torrents_gone_from_qbittorrent_are_dropped(rig: Rig) -> None:
    add_film(rig)
    rig.guard.request_cancel("d" * 40)  # a torrent that no longer exists
    rig.guard.request_cancel(FILM_HASH)

    await rig.verifier.run_once()

    assert not rig.guard.cancel_requested("d" * 40)
    assert rig.guard.cancel_requested(FILM_HASH)


async def test_the_loop_waits_for_readiness_then_polls_after_one_interval(rig: Rig) -> None:
    settings = make_settings(Path(rig.settings.data_path).parent, verify_poll_seconds=7)
    readiness = Readiness()
    sleeps: list[float] = []
    info_calls_at_sleep: list[int] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        info_calls_at_sleep.append(len(rig.fake.calls_to(INFO)))
        if len(sleeps) == 2:
            readiness.mark_ready()
        if len(sleeps) == 4:
            raise asyncio.CancelledError

    verifier = Verifier(
        rig.qbit,
        rig.runner_client,
        settings,
        guard=rig.guard,
        sleep=fake_sleep,
        readiness=readiness,
    )

    with pytest.raises(asyncio.CancelledError):
        await verifier.run_forever()

    assert info_calls_at_sleep == [0, 0, 0, 1]  # nothing asked of qBittorrent before ready
    assert sleeps[2] == sleeps[3] == 7  # the first tick comes one poll interval after ready
    assert sleeps[0] != 7


async def test_a_qbittorrent_error_in_a_tick_is_audited_and_the_loop_continues(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="app.audit")
    add_film(rig)
    rig.fake.unreachable = True
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 2:
            rig.fake.unreachable = False  # qBittorrent is back for the second tick
        if len(sleeps) == 3:
            raise asyncio.CancelledError

    verifier = rig.make_verifier(sleep=fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await verifier.run_forever()

    assert audit_lines(caplog)[0] == "event=error where=verifier exc=QbitUnavailable status=none"
    assert len([line for line in audit_lines(caplog) if "event=error" in line]) == 1
    assert rig.media_files() == ["Film/Movie/movie.mkv"]  # the loop went on to the next tick


async def test_one_torrent_whose_qbittorrent_call_fails_does_not_starve_the_queue_or_the_cleanup(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    """WR-01: a poison torrent at the head of the queue is audited and backs off; the torrents
    behind it, the purge and the seeding cleanup still run on every tick."""
    caplog.set_level(logging.INFO, logger="app.audit")
    now = [NOW]
    verifier = rig.make_verifier(clock=lambda: now[0])
    poison, seeded = "b" * 40, "c" * 40
    rig.add_finished(poison, "Poison", [("Poison/p.mkv", GB)], completion_on=50)
    add_film(rig)  # completed after the poison one
    rig.add_finished(seeded, "Seeded", [("Seeded/s.mkv", GB)], state="stoppedUP", tags=("fx-ok-1",))
    original = rig.fake._routes[("GET", FILES)]

    def files(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("hash") == poison:
            return httpx.Response(500, text="boom")
        return original(request)

    rig.fake.register("GET", FILES, files)

    await verifier.run_once()

    assert rig.media_files() == ["Film/Movie/movie.mkv"]  # the torrent behind the poison one
    assert len(rig.tag_calls()) == 1
    assert (seeded, True) in rig.fake.deleted  # the seeding cleanup ran as well
    assert len([line for line in audit_lines(caplog) if "event=error" in line]) == 1

    asked = len(rig.fake.calls_to(FILES))
    await verifier.run_once()  # backing off: the poison torrent is not asked about again
    assert len(rig.fake.calls_to(FILES)) == asked
    now[0] += 61
    await verifier.run_once()
    assert len(rig.fake.calls_to(FILES)) == asked + 1
    assert len([line for line in audit_lines(caplog) if "event=error" in line]) == 2


async def test_the_loop_survives_an_unexpected_error_in_a_tick(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 3:
            raise asyncio.CancelledError

    verifier = rig.make_verifier(sleep=fake_sleep)

    async def broken_tick() -> None:
        raise RuntimeError("boom with /secret/path")

    monkeypatch.setattr(verifier, "run_once", broken_tick)

    with pytest.raises(asyncio.CancelledError):
        await verifier.run_forever()

    assert len(sleeps) == 3  # two ticks failed, the loop never died


async def test_the_passed_audit_line_carries_the_escaped_name_and_the_file_count_only(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="app.audit")
    rig.add_finished(FILM_HASH, 'Movie "x"\nevent=login', [(FILM_FILE, 4 * GB)])
    rig.runner.script(FILM_REL, film_facts(duration=6000.0))

    await rig.verifier.run_once()

    (line,) = audit_lines(caplog)
    assert line == 'event=quarantine.passed name="Movie \\"x\\"\\nevent=login" files=1'
    assert rig.settings.data_path not in line


async def test_the_lifespan_runs_the_verifier_and_stops_it_with_the_backend(
    tmp_path: Path,
) -> None:
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
    app = create_app(settings, qbit, runner=runner_client)

    async with app.router.lifespan_context(app):
        await wait_for_bootstrap(app)
        assert isinstance(app.state.verifier, Verifier)
        assert isinstance(app.state.guard, HandoffGuard)
        assert app.state.runner is runner_client
        assert not app.state.verify_task.done()
        task = app.state.verify_task

    assert task.cancelled()  # stopped with the backend, no error raised
    assert runner_client._http.is_closed


# --- the hand-off's own path rules (T-02.1-22) -----------------------------------------------------


@pytest.fixture
def folders(tmp_path: Path) -> tuple[Path, Path]:
    quarantine = tmp_path / "quarantine"
    media = tmp_path / "media" / "Film"
    (quarantine / "Film").mkdir(parents=True)
    media.mkdir(parents=True)
    return quarantine, media


@pytest.mark.parametrize(
    "name", ["../escape.mkv", "/etc/passwd", "a//b.mkv", "./a.mkv", "a/../b.mkv", "a\x00b.mkv", ""]
)
def test_unsafe_names_are_refused_at_both_ends(name: str, folders: tuple[Path, Path]) -> None:
    quarantine, media = folders
    with pytest.raises(HandoffError) as source_error:
        source_path(str(quarantine / "Film"), name, str(quarantine))
    with pytest.raises(HandoffError) as target_error:
        media_target(str(media), name)
    assert source_error.value.why == target_error.value.why == "unsafe_path"


def test_a_symlinked_file_or_folder_is_never_a_source(
    folders: tuple[Path, Path], tmp_path: Path
) -> None:
    quarantine, _ = folders
    outside = tmp_path / "outside.mkv"
    outside.write_bytes(b"x")
    save = quarantine / "Film"
    (save / "link.mkv").symlink_to(outside)
    (save / "dir").symlink_to(tmp_path)
    with pytest.raises(HandoffError):
        source_path(str(save), "link.mkv", str(quarantine))
    with pytest.raises(HandoffError):
        source_path(str(save), "dir/outside.mkv", str(quarantine))


def test_a_save_path_outside_quarantine_is_refused(
    folders: tuple[Path, Path], tmp_path: Path
) -> None:
    quarantine, media = folders
    (media / "m.mkv").write_bytes(b"x")
    with pytest.raises(HandoffError):
        source_path(str(media), "m.mkv", str(quarantine))
    with pytest.raises(HandoffError):
        source_path(str(quarantine), "Film/m.mkv", str(quarantine))  # the root itself


def test_a_missing_file_is_missing_and_a_folder_is_not_a_file(
    folders: tuple[Path, Path],
) -> None:
    quarantine, _ = folders
    save = quarantine / "Film"
    (save / "dir").mkdir()
    with pytest.raises(HandoffError) as gone:
        source_path(str(save), "nope.mkv", str(quarantine))
    with pytest.raises(HandoffError) as folder:
        source_path(str(save), "dir", str(quarantine))
    assert (gone.value.why, folder.value.why) == ("missing", "unsafe_path")


def test_a_hardlink_is_idempotent_and_never_overwrites_another_file(
    folders: tuple[Path, Path],
) -> None:
    quarantine, media = folders
    src = quarantine / "Film" / "a.mkv"
    src.write_bytes(b"film")
    dst = media_target(str(media), "Movie/a.mkv")

    assert link_into_media(src, dst, media_dir=str(media)) == dst
    assert link_into_media(src, dst, media_dir=str(media)) == dst  # same inode: skipped
    assert os.stat(src).st_nlink == 2

    other = media / "Other" / "a.mkv"
    other.parent.mkdir()
    other.write_bytes(b"different")
    used = link_into_media(src, other, media_dir=str(media))
    assert used == media / "Other" / "a (2).mkv"  # the next free name, never the existing file
    assert other.read_bytes() == b"different"
    assert os.stat(used).st_ino == os.stat(src).st_ino


def test_a_symlinked_media_folder_is_refused(folders: tuple[Path, Path], tmp_path: Path) -> None:
    quarantine, media = folders
    src = quarantine / "Film" / "a.mkv"
    src.write_bytes(b"film")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (media / "Movie").symlink_to(elsewhere)

    with pytest.raises(HandoffError) as refused:
        link_into_media(src, media_target(str(media), "Movie/a.mkv"), media_dir=str(media))

    assert refused.value.why == "unsafe_path"
    assert list(elsewhere.iterdir()) == []


def test_a_symlinked_parent_is_refused_before_any_folder_is_created_behind_it(
    folders: tuple[Path, Path], tmp_path: Path
) -> None:
    """WR-05: makedirs follows links, so the folders used to be built at the link's target."""
    quarantine, media = folders
    src = quarantine / "Film" / "a.mkv"
    src.write_bytes(b"film")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (media / "Series").symlink_to(elsewhere)

    with pytest.raises(HandoffError) as refused:
        link_into_media(
            src, media_target(str(media), "Series/Season 01/a.mkv"), media_dir=str(media)
        )

    assert refused.value.why == "unsafe_path"
    assert list(elsewhere.iterdir()) == []


def test_missing_folders_below_media_are_created_one_by_one(
    folders: tuple[Path, Path],
) -> None:
    quarantine, media = folders
    src = quarantine / "Film" / "a.mkv"
    src.write_bytes(b"film")

    used = link_into_media(
        src, media_target(str(media), "Series/Season 01/a.mkv"), media_dir=str(media)
    )

    assert used == media / "Series" / "Season 01" / "a.mkv"
    assert os.stat(used).st_ino == os.stat(src).st_ino


def test_a_link_across_filesystems_names_the_errno(
    folders: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    quarantine, media = folders
    src = quarantine / "Film" / "a.mkv"
    src.write_bytes(b"film")

    def cross_device(*args, **kwargs):
        raise OSError(18, "Invalid cross-device link")

    monkeypatch.setattr(os, "link", cross_device)

    with pytest.raises(HandoffError) as failed:
        link_into_media(src, media_target(str(media), "a.mkv"), media_dir=str(media))

    assert failed.value.why == "EXDEV"


# --- plan 02.1-07 Task 2: mixed packs, subtitles, collisions, link failures ---------------------------

TEXT_SUBTITLE = "1\n00:00:01,000 --> 00:00:02,000\nHello\n"


def held_files(rig: Rig, torrent_hash: str = FILM_HASH) -> list[str]:
    """Every file held in the rejected folder of a torrent, relative to its folder."""
    folder = Path(rig.settings.rejected_root) / download_id(
        rig.settings.secret_key.get_secret_value(), torrent_hash
    )
    if not folder.exists():
        return []
    return sorted(str(p.relative_to(folder)) for p in folder.rglob("*") if p.is_file())


def stored_outcome(rig: Rig, torrent_hash: str = FILM_HASH) -> dict:
    outcome_id = download_id(rig.settings.secret_key.get_secret_value(), torrent_hash)
    return json.loads((Path(rig.settings.rejected_root) / f"{outcome_id}.json").read_text())


async def test_a_mixed_series_pack_delivers_the_good_episodes_and_holds_the_bad_one(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="app.audit")
    names = [f"Show.S01/Show.S01E0{n}.mkv" for n in (1, 2, 3)]
    rig.add_finished(
        "c" * 40, "Show.S01", [(name, 700_000_000) for name in names], category="SerieTV"
    )
    rig.runner.script(f"SerieTV/{names[0]}", film_facts(duration=3000.0, size=700_000_000))
    rig.runner.script(f"SerieTV/{names[1]}", failed_facts("probe_failed"))
    rig.runner.script(f"SerieTV/{names[2]}", film_facts(duration=3000.0, size=700_000_000))

    outcome = await rig.verifier.check_torrent(await rig.only_row("c" * 40))

    assert outcome == "partial"
    assert rig.media_files() == [f"SerieTV/{names[0]}", f"SerieTV/{names[2]}"]
    assert held_files(rig, "c" * 40) == [names[1]]
    stored = stored_outcome(rig, "c" * 40)
    assert (stored["kind"], stored["skipped"], stored["type"]) == ("ready", 1, "serie")
    assert rig.fake.deleted == [("c" * 40, True)]  # a torrent that held a suspect file never seeds
    assert rig.tag_calls() == []
    lines = audit_lines(caplog)
    assert sorted(line.split()[0] for line in lines) == [
        "event=quarantine.passed",
        "event=quarantine.rejected",
    ]
    for name in (names[0], names[2]):  # the delete took the quarantine name, not the media link
        assert os.stat(rig.media / "SerieTV" / name).st_nlink >= 2


async def test_a_mixed_film_delivers_the_main_video_and_holds_the_failing_extra(
    rig: Rig,
) -> None:
    rig.add_finished(
        FILM_HASH, "Movie", [(FILM_FILE, 3 * GB), ("Movie/extras/making-of.mkv", 300_000_000)]
    )
    rig.runner.script(FILM_REL, film_facts(duration=6000.0))
    rig.runner.script(
        "Film/Movie/extras/making-of.mkv",
        film_facts(duration=1200.0, format_name="mov,mp4,m4a,3gp,3g2,mj2"),
    )

    outcome = await rig.verifier.check_torrent(await rig.only_row())

    assert outcome == "partial"
    assert rig.media_files() == ["Film/Movie/movie.mkv"]
    assert held_files(rig) == ["Movie/extras/making-of.mkv"]
    assert stored_outcome(rig)["skipped"] == 1
    assert rig.fake.deleted == [(FILM_HASH, True)]


async def test_a_main_video_shorter_than_the_film_minimum_is_rejected_but_an_extra_is_not(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="app.audit")
    rig.add_finished(FILM_HASH, "Movie", [(FILM_FILE, 3 * GB)])
    rig.runner.script(FILM_REL, film_facts(duration=1800.0))  # 30 minutes, minimum is 40

    assert await rig.verifier.check_torrent(await rig.only_row()) == "rejected"
    assert "reason=too_short" in audit_lines(caplog)[0]

    rig.add_finished("b" * 40, "Other", [("Other/o.mkv", 3 * GB), ("Other/extra.mkv", 100_000_000)])
    rig.runner.script("Film/Other/o.mkv", film_facts(duration=6000.0))
    rig.runner.script("Film/Other/extra.mkv", film_facts(duration=300.0))  # no minimum on extras

    assert await rig.verifier.check_torrent(await rig.only_row("b" * 40)) == "passed"
    assert rig.media_files() == ["Film/Other/extra.mkv", "Film/Other/o.mkv"]


async def test_a_text_subtitle_next_to_a_passing_video_keeps_the_torrent_seeding(
    rig: Rig,
) -> None:
    rig.add_finished(FILM_HASH, "Movie", [(FILM_FILE, 4 * GB), ("Movie/movie.en.srt", 64)])
    (Path(rig.settings.save_path_film) / "Movie/movie.en.srt").write_text(TEXT_SUBTITLE)
    rig.runner.script(FILM_REL, film_facts(duration=6000.0))

    assert await rig.verifier.check_torrent(await rig.only_row()) == "passed"

    assert rig.media_files() == ["Film/Movie/movie.en.srt", "Film/Movie/movie.mkv"]
    assert len(rig.tag_calls()) == 1
    assert rig.fake.deleted == []


async def test_a_binary_subtitle_is_held_with_the_early_removal_but_is_not_a_skipped_video(
    rig: Rig,
) -> None:
    rig.add_finished(FILM_HASH, "Movie", [(FILM_FILE, 4 * GB), ("Movie/movie.srt", 64)])
    rig.runner.script(FILM_REL, film_facts(duration=6000.0))  # the srt is sparse: all NUL bytes

    outcome = await rig.verifier.check_torrent(await rig.only_row())

    assert outcome == "partial"
    assert rig.media_files() == ["Film/Movie/movie.mkv"]
    assert held_files(rig) == ["Movie/movie.srt"]
    stored = stored_outcome(rig)
    assert (stored["kind"], stored["skipped"]) == ("ready", 0)
    assert rig.fake.deleted == [(FILM_HASH, True)]
    assert rig.tag_calls() == []


async def test_a_subtitle_never_moves_when_its_video_failed(rig: Rig) -> None:
    rig.add_finished(FILM_HASH, "Movie", [(FILM_FILE, 4 * GB), ("Movie/movie.srt", 64)])
    (Path(rig.settings.save_path_film) / "Movie/movie.srt").write_text(TEXT_SUBTITLE)
    rig.runner.script(FILM_REL, failed_facts("timeout"))

    assert await rig.verifier.check_torrent(await rig.only_row()) == "rejected"

    assert rig.media_files() == []
    assert held_files(rig) == ["Movie/movie.mkv"]  # the subtitle is neither linked nor held
    assert stored_outcome(rig)["skipped"] == 1
    assert rig.runner.calls == [FILM_REL, FILM_REL]  # a timeout is retried once too


async def test_a_torrent_with_nothing_to_check_is_rejected_with_no_video(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="app.audit")
    rig.add_finished(
        FILM_HASH, "Movie", [("Movie/Sample/sample.mkv", 10_000_000), ("Movie/movie.nfo", 100)]
    )

    assert await rig.verifier.check_torrent(await rig.only_row()) == "rejected"

    assert rig.runner.calls == []
    assert rig.media_files() == []
    stored = stored_outcome(rig)
    assert (stored["kind"], stored["skipped"]) == ("rejected", 0)
    assert rig.fake.deleted == [(FILM_HASH, True)]
    (line,) = audit_lines(caplog)
    assert "file=null" in line
    assert "reason=no_video" in line


async def test_an_empty_file_list_is_a_host_fault_and_deletes_nothing(rig: Rig) -> None:
    rig.add_finished(FILM_HASH, "Movie", [])  # qBittorrent has not listed the files yet

    assert await rig.verifier.check_torrent(await rig.only_row()) == "held"

    assert rig.fake.deleted == []
    assert not Path(rig.settings.rejected_root).exists()


async def test_a_name_collision_in_media_takes_the_next_free_name_and_keeps_the_old_file(
    rig: Rig,
) -> None:
    add_film(rig)
    existing = rig.media / "Film" / "Movie" / "movie.mkv"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"another film")

    assert await rig.verifier.check_torrent(await rig.only_row()) == "passed"

    assert existing.read_bytes() == b"another film"
    assert rig.media_files() == ["Film/Movie/movie (2).mkv", "Film/Movie/movie.mkv"]
    source = rig.quarantine / "Film" / "Movie" / "movie.mkv"
    assert os.stat(rig.media / "Film/Movie/movie (2).mkv").st_ino == os.stat(source).st_ino


async def test_a_second_collision_takes_the_third_name(rig: Rig) -> None:
    add_film(rig)
    folder = rig.media / "Film" / "Movie"
    folder.mkdir(parents=True)
    (folder / "movie.mkv").write_bytes(b"one")
    (folder / "movie (2).mkv").write_bytes(b"two")

    assert await rig.verifier.check_torrent(await rig.only_row()) == "passed"

    assert (folder / "movie (3).mkv").exists()
    assert (folder / "movie.mkv").read_bytes() == b"one"
    assert (folder / "movie (2).mkv").read_bytes() == b"two"


async def test_a_target_that_already_is_the_same_file_is_reused_not_renamed(rig: Rig) -> None:
    add_film(rig)
    folder = rig.media / "Film" / "Movie"
    folder.mkdir(parents=True)
    os.link(rig.quarantine / "Film" / "Movie" / "movie.mkv", folder / "movie.mkv")

    assert await rig.verifier.check_torrent(await rig.only_row()) == "passed"

    assert rig.media_files() == ["Film/Movie/movie.mkv"]
    assert len(rig.tag_calls()) == 1


async def test_when_every_name_is_taken_the_torrent_stays_checking_and_collision_is_logged(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="app.audit")
    add_film(rig)
    folder = rig.media / "Film" / "Movie"
    folder.mkdir(parents=True)
    (folder / "movie.mkv").write_bytes(b"x")
    for n in range(2, 100):
        (folder / f"movie ({n}).mkv").write_bytes(b"x")

    for _ in range(2):
        assert await rig.verifier.check_torrent(await rig.only_row()) == "held"

    assert len(list(folder.iterdir())) == 99  # nothing new was linked
    assert rig.tag_calls() == []
    assert rig.fake.deleted == []
    assert audit_lines(caplog) == ['event=quarantine.link_failed name="Movie" why=collision']


async def test_a_link_fail_with_exdev_never_becomes_a_copy_and_is_logged_once_over_two_ticks(
    rig: Rig, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil

    caplog.set_level(logging.INFO, logger="app.audit")
    add_film(rig)
    now = [NOW]
    verifier = rig.make_verifier(clock=lambda: now[0])
    copies: list[str] = []

    def cross_device(*args, **kwargs):
        raise OSError(18, "Invalid cross-device link")

    def no_copy(*args, **kwargs):
        copies.append("called")
        raise AssertionError("a copy fallback must never run")

    monkeypatch.setattr(os, "link", cross_device)
    for name in ("copy", "copy2", "copyfile", "copytree", "move"):
        monkeypatch.setattr(shutil, name, no_copy)

    await verifier.run_once()
    await verifier.run_once()

    assert copies == []
    assert rig.media_files() == []
    assert rig.tag_calls() == []
    assert rig.fake.deleted == []
    assert not list(Path(rig.settings.rejected_root).glob("*.json"))  # no outcome either
    assert audit_lines(caplog) == ['event=quarantine.link_failed name="Movie" why=EXDEV']
    assert len(rig.runner.calls) == 1  # WR-04: held, so the second tick does not re-probe it

    now[0] += 61  # the backoff is over: still a candidate, probed again, still logged once
    await verifier.run_once()

    assert len(rig.runner.calls) == 2
    assert audit_lines(caplog) == ['event=quarantine.link_failed name="Movie" why=EXDEV']


async def test_a_link_fail_into_rejected_deletes_nothing_either(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig.add_finished(FILM_HASH, "Movie", [(FILM_FILE, 8 * 1024 * 1024)])
    rig.runner.script(FILM_REL, failed_facts("probe_failed"))

    def refused(*args, **kwargs):
        raise OSError(1, "Operation not permitted")

    monkeypatch.setattr(os, "link", refused)

    assert await rig.verifier.check_torrent(await rig.only_row()) == "held"

    assert rig.fake.deleted == []
    assert not list(Path(rig.settings.rejected_root).glob("*.json"))


async def test_a_mixed_pack_whose_media_link_fails_has_already_secured_the_failing_file(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WR-04: the failing files are held before the passing ones go into media, so a link that
    fails half way never leaves partial content in Jellyfin without the held copy."""
    rig.add_finished(
        FILM_HASH, "Pack", [("Pack/a.mkv", GB), ("Pack/b.mkv", GB)], category="SerieTV"
    )
    rig.runner.script("SerieTV/Pack/a.mkv", film_facts(duration=3000.0, size=GB))
    rig.runner.script("SerieTV/Pack/b.mkv", failed_facts("probe_failed"))
    real_link = os.link
    order: list[str] = []

    def spying_link(src, dst, **kwargs):
        order.append("rejected" if "rejected" in str(dst) else "media")
        if order[-1] == "media":
            raise OSError(28, "No space left on device")
        return real_link(src, dst, **kwargs)

    monkeypatch.setattr(os, "link", spying_link)

    assert await rig.verifier.check_torrent(await rig.only_row()) == "held"

    assert order == ["rejected", "media"]
    assert rig.media_files() == []
    assert rig.fake.deleted == []


async def test_blocking_file_work_runs_off_the_event_loop_thread(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WR-02: stat, hardlinks and the fsync'ed sidecar write must never block the loop (login,
    the list and the healthcheck share it)."""
    import threading

    from app.quarantine.outcomes import OutcomeStore

    loop_thread = threading.get_ident()
    seen: dict[str, int] = {}

    def spy(name: str, original):
        def wrapper(*args, **kwargs):
            seen.setdefault(name, threading.get_ident())
            return original(*args, **kwargs)

        return wrapper

    monkeypatch.setattr(verifier_module, "source_path", spy("source_path", source_path))
    monkeypatch.setattr(verifier_module, "link_into_media", spy("media", link_into_media))
    monkeypatch.setattr(
        verifier_module, "link_into_rejected", spy("rejected", verifier_module.link_into_rejected)
    )
    monkeypatch.setattr(OutcomeStore, "write", spy("write", OutcomeStore.write))
    monkeypatch.setattr(OutcomeStore, "get", spy("get", OutcomeStore.get))
    rig.add_finished(
        FILM_HASH,
        "Pack",
        [("Pack/a.mkv", GB), ("Pack/b.mkv", GB)],
        category="SerieTV",
    )
    rig.runner.script("SerieTV/Pack/a.mkv", film_facts(duration=3000.0, size=GB))
    rig.runner.script("SerieTV/Pack/b.mkv", failed_facts("probe_failed"))

    assert await rig.verifier.check_torrent(await rig.only_row()) == "partial"

    assert set(seen) == {"source_path", "media", "rejected", "write", "get"}
    assert all(thread != loop_thread for thread in seen.values()), seen


async def test_a_torrent_that_already_has_an_outcome_is_not_probed_again_only_deleted(
    rig: Rig,
) -> None:
    from app.quarantine.outcomes import Outcome, OutcomeStore

    add_film(rig)  # completion_on 100
    outcome_id = download_id(rig.settings.secret_key.get_secret_value(), FILM_HASH)
    OutcomeStore(rig.settings.rejected_root).write(
        Outcome(outcome_id, "Movie", "film", "rejected", 1, NOW)
    )

    await rig.verifier.run_once()  # a delete that failed earlier is retried

    assert rig.runner.calls == []
    assert rig.fake.deleted == [(FILM_HASH, True)]
    assert rig.media_files() == []


async def test_an_old_outcome_does_not_stop_the_same_film_from_being_downloaded_again(
    rig: Rig,
) -> None:
    from app.quarantine.outcomes import Outcome, OutcomeStore

    add_film(rig, completion_on=int(NOW) + 500)  # finished after the old outcome was stored
    outcome_id = download_id(rig.settings.secret_key.get_secret_value(), FILM_HASH)
    OutcomeStore(rig.settings.rejected_root).write(
        Outcome(outcome_id, "Movie", "film", "rejected", 1, NOW)
    )

    await rig.verifier.run_once()

    assert rig.runner.calls == [FILM_REL]  # checked like any new download
    assert rig.media_files() == ["Film/Movie/movie.mkv"]
    assert rig.fake.deleted == []


def test_a_stale_held_file_of_a_returning_torrent_is_replaced_not_a_collision(
    tmp_path: Path,
) -> None:
    from app.quarantine.handoff import link_into_rejected

    src = tmp_path / "q.mkv"
    src.write_bytes(b"new")
    held = tmp_path / "rejected" / "0123456789abcdef"
    stale = held / "Movie" / "movie.mkv"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"old")

    used = link_into_rejected(src, held, "Movie/movie.mkv")

    assert used == stale
    assert os.stat(stale).st_ino == os.stat(src).st_ino


def test_holding_a_file_never_changes_the_mode_of_the_shared_quarantine_inode(
    tmp_path: Path,
) -> None:
    """CR-01: a hardlink shares its inode, so a chmod on the held name would lock the sandbox
    runner (another uid) out of the quarantine file and stall every later check."""
    from app.quarantine.handoff import link_into_rejected

    src = tmp_path / "q.mkv"
    src.write_bytes(b"data")
    os.chmod(src, 0o644)
    held = tmp_path / "rejected" / "0123456789abcdef"

    used = link_into_rejected(src, held, "Movie/movie.mkv")

    assert os.stat(used).st_ino == os.stat(src).st_ino
    assert stat.S_IMODE(os.stat(src).st_mode) == 0o644
    assert stat.S_IMODE(os.stat(held).st_mode) == 0o700  # the folders keep other users out
    assert stat.S_IMODE(os.stat(held / "Movie").st_mode) == 0o700


# --- plan 02.1-07 Task 3: the purge, the seeding-end removal and the lifespan -------------------------

DAY = 86400


def delete_removes_quarantine_names(rig: Rig) -> None:
    """Like qBittorrent: deleteFiles=true unlinks the torrent's names, not other hardlinks."""
    from urllib.parse import parse_qsl

    original = rig.fake._torrents_delete

    def deleting(request: httpx.Request) -> httpx.Response:
        form = dict(parse_qsl(request.content.decode()))
        if form.get("deleteFiles") == "true":
            for torrent_hash in form.get("hashes", "").split("|"):
                torrent = rig.fake.torrents.get(torrent_hash)
                for row in (torrent.files or []) if torrent is not None else []:
                    (Path(torrent.save_path) / row["name"]).unlink(missing_ok=True)
        return original(request)

    rig.fake.register("POST", "/api/v2/torrents/delete", deleting)


def finished_and_linked(rig: Rig, *, state: str, tags: tuple[str, ...], **kwargs) -> Path:
    """A verified film whose media hardlink already exists; returns the media link."""
    rig.add_finished(FILM_HASH, "Movie", [(FILM_FILE, 4 * GB)], state=state, tags=tags, **kwargs)
    link = rig.media / "Film" / "Movie" / "movie.mkv"
    link.parent.mkdir(parents=True)
    os.link(Path(rig.settings.save_path_film) / FILM_FILE, link)
    return link


def sidecar_of(rig: Rig, torrent_hash: str = FILM_HASH) -> Path:
    outcome_id = download_id(rig.settings.secret_key.get_secret_value(), torrent_hash)
    return Path(rig.settings.rejected_root) / f"{outcome_id}.json"


async def test_every_tick_purges_old_held_files_and_logs_the_count_only_when_something_went(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    from app.quarantine.outcomes import Outcome, OutcomeStore

    caplog.set_level(logging.INFO, logger="app.audit")
    store = OutcomeStore(rig.settings.rejected_root)
    old_id = "0123456789abcdef"
    store.write(Outcome(old_id, "Old", "film", "rejected", 1, NOW - 8 * DAY))
    folder = store.rejected_dir(old_id)
    folder.mkdir()
    os.utime(folder, (NOW - 8 * DAY, NOW - 8 * DAY))

    await rig.verifier.run_once()
    await rig.verifier.run_once()

    assert audit_lines(caplog) == ["event=quarantine.purged count=2"]
    assert not folder.exists()
    assert store.get(old_id) is None


@pytest.mark.parametrize("state", ["stoppedUP", "pausedUP"])
async def test_seeding_end_stores_the_outcome_and_deletes_only_the_quarantine_link(
    rig: Rig, caplog: pytest.LogCaptureFixture, state: str
) -> None:
    caplog.set_level(logging.INFO, logger="app.audit")
    delete_removes_quarantine_names(rig)
    verified = int(NOW) - 1000
    link = finished_and_linked(rig, state=state, tags=(f"fx-ok-{verified}",))
    assert os.stat(link).st_nlink == 2

    await rig.verifier.run_once()

    stored = json.loads(sidecar_of(rig).read_text())
    assert (stored["kind"], stored["skipped"], stored["at"]) == ("ready", 0, float(verified))
    assert (stored["name"], stored["type"]) == ("Movie", "film")
    assert rig.fake.deleted == [(FILM_HASH, True)]
    assert link.exists()  # the film is still in media
    assert os.stat(link).st_nlink == 1
    assert not (Path(rig.settings.save_path_film) / FILM_FILE).exists()
    assert audit_lines(caplog) == ['event=quarantine.seeding_done name="Movie"']
    assert rig.runner.calls == []


@pytest.mark.parametrize("change", ["re-added", "removed"])
async def test_the_seeding_cleanup_decides_on_a_fresh_row_not_on_the_tick_snapshot(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    """WR-03: probes take minutes. A hash that was removed or re-added since the listing is a
    different download and must not be deleted (with files) nor given a Ready sidecar."""
    delete_removes_quarantine_names(rig)
    finished_and_linked(rig, state="stoppedUP", tags=(f"fx-ok-{int(NOW) - 1000}",))
    real_purge = rig.verifier._purge

    async def purge_then_the_world_changes() -> None:
        await real_purge()
        torrent = rig.fake.torrents[FILM_HASH]
        if change == "removed":
            del rig.fake.torrents[FILM_HASH]
        else:  # the same hash, added again: unverified and downloading
            torrent.tags = []
            torrent.state = "downloading"

    monkeypatch.setattr(rig.verifier, "_purge", purge_then_the_world_changes)

    await rig.verifier.run_once()

    assert rig.fake.deleted == []
    assert not sidecar_of(rig).exists()
    assert (Path(rig.settings.save_path_film) / FILM_FILE).exists()


async def test_a_verified_torrent_that_is_still_seeding_is_left_alone(rig: Rig) -> None:
    finished_and_linked(rig, state="stalledUP", tags=(f"fx-ok-{int(NOW) - 1000}",))

    await rig.verifier.run_once()

    assert rig.fake.deleted == []
    assert not sidecar_of(rig).exists()


@pytest.mark.parametrize("tagged", [True, False])
async def test_a_legacy_torrent_outside_quarantine_is_never_deleted(rig: Rig, tagged: bool) -> None:
    legacy = str(rig.media / "Film")
    tags = (f"fx-ok-{int(NOW) - 1000}",) if tagged else ()
    rig.add_finished(
        FILM_HASH, "Old film", [("old.mkv", GB)], state="stoppedUP", tags=tags, save_path=legacy
    )

    await rig.verifier.run_once()

    assert rig.fake.deleted == []
    assert rig.runner.calls == []
    assert not sidecar_of(rig).exists()


async def test_a_stopped_torrent_without_the_verified_tag_is_never_deleted_by_the_seeding_rule(
    rig: Rig,
) -> None:
    rig.add_finished(FILM_HASH, "Movie", [(FILM_FILE, 4 * GB)], state="stoppedUP")
    # not a candidate to delete: it is checked (and passes), never removed as "seeding done"
    rig.runner.script(FILM_REL, film_facts(duration=6000.0))

    await rig.verifier.run_once()

    assert rig.fake.deleted == []
    assert len(rig.tag_calls()) == 1


async def test_a_verified_torrent_older_than_the_visible_window_is_deleted_without_an_outcome(
    rig: Rig,
) -> None:
    link = finished_and_linked(rig, state="stoppedUP", tags=(f"fx-ok-{int(NOW) - 8 * DAY}",))

    await rig.verifier.run_once()

    assert rig.fake.deleted == [(FILM_HASH, True)]
    assert not sidecar_of(rig).exists()
    assert link.exists()


async def test_the_lifespan_hands_the_outcome_store_to_the_verifier(tmp_path: Path) -> None:
    from app.quarantine.outcomes import OutcomeStore

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
    app = create_app(settings, qbit, runner=runner_client)

    async with app.router.lifespan_context(app):
        await wait_for_bootstrap(app)
        assert isinstance(app.state.outcomes, OutcomeStore)
        assert str(app.state.outcomes.root) == settings.rejected_root
        assert app.state.verifier._outcomes is app.state.outcomes
