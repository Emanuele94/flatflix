"""The verifier (QUAR-01, QUAR-02, QUAR-04, QUAR-05, D-45..D-54, D-58, D-63).

A rig wires FakeQbit, FakeRunner and a real folder under `tmp_path`: files are sparse, so a 4 GB
film costs nothing. Tests watch what reaches the media folder, what the fake qBittorrent was told
(`addTags`, `delete`) and what the fake runner was asked to probe.
"""

import asyncio
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from app.config import Settings
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


async def test_an_unreachable_runner_waits_and_one_outage_writes_one_audit_line(
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


async def test_a_503_from_the_runner_names_its_reason_and_stops_the_tick(
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


async def test_a_failing_video_leaves_the_torrent_untouched_and_checking(rig: Rig) -> None:
    from tests.fakerunner import failed_facts

    add_film(rig)
    rig.runner.script(FILM_REL, failed_facts("probe_failed"))

    outcome = await rig.verifier.check_torrent(await rig.only_row())

    assert outcome == "held"
    assert rig.media_files() == []
    assert rig.tag_calls() == []
    assert rig.fake.deleted == []


async def test_a_file_the_runner_refuses_is_unprobeable_and_held(rig: Rig) -> None:
    rig.add_finished(FILM_HASH, "Movie", [(FILM_FILE, 4 * GB)])  # nothing scripted: 404

    outcome = await rig.verifier.check_torrent(await rig.only_row())

    assert outcome == "held"
    assert rig.media_files() == []
    assert rig.tag_calls() == []
    assert rig.fake.deleted == []


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


async def test_a_binary_subtitle_holds_the_whole_torrent(rig: Rig) -> None:
    rig.add_finished(FILM_HASH, "Movie", [(FILM_FILE, 4 * GB), ("Movie/movie.en.srt", 64)])
    rig.runner.script(FILM_REL, film_facts(duration=6000.0))  # the srt is sparse: all NUL bytes

    outcome = await rig.verifier.check_torrent(await rig.only_row())

    assert outcome == "held"
    assert rig.media_files() == []
    assert rig.tag_calls() == []


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
    with pytest.raises(HandoffError) as collision:
        link_into_media(src, other, media_dir=str(media))
    assert collision.value.why == "collision"
    assert other.read_bytes() == b"different"


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
