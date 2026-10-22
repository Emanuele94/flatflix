"""The pure downloads-list rules: state table, progress, ETA, names, window, order (D-25..D-35).

No I/O: rows go in, items come out. Settings are built like `tests.conftest.settings` does.
"""

import asyncio
import hashlib
import hmac
import re

import pytest
from pydantic import SecretStr, ValidationError

from app.config import Settings
from app.download import jobs as jobs_module
from app.download.jobs import Job, JobRegistry, JobState
from app.download.listing import (
    FAILED_JOB_STATES,
    READY_STATES,
    build_items,
    display_name,
    download_id,
    eta_of,
    percent,
    plain_state,
)
from tests.conftest import (
    PORTAL_PASS_HASH,
    PORTAL_SECRET_KEY,
    PORTAL_USER,
    QBIT_PASS,
    QBIT_URL,
    QBIT_USER,
)

NOW = 1_800_000_000.0
SECRET = "listing-test-secret-0123456789abcdef"
DAY = 86400
PENDING_TAGS = "fx, fx-pending, fx-job-0123456789abcdef"


def make_settings(**overrides: object) -> Settings:
    return Settings(
        qbittorrent_url=QBIT_URL,
        qbittorrent_user=QBIT_USER,
        qbittorrent_pass=SecretStr(QBIT_PASS),
        app_user=PORTAL_USER,
        app_pass_hash=SecretStr(PORTAL_PASS_HASH),
        secret_key=SecretStr(PORTAL_SECRET_KEY),
        **overrides,
    )


def row(torrent_hash: str = "a" * 40, **fields: object) -> dict:
    base: dict = {
        "hash": torrent_hash,
        "name": "Sintel 1080p",
        "category": "Film",
        "tags": "",
        "state": "downloading",
        "progress": 0.5,
        "eta": 600,
        "added_on": int(NOW) - 3600,
        "completion_on": -1,
    }
    base.update(fields)
    return base


def items_of(rows: list[dict], settings: Settings | None = None) -> list[dict]:
    return build_items(rows, settings or make_settings(), now=NOW, secret=SECRET)


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("uploading", "ready"),
        ("stalledUP", "ready"),
        ("stoppedUP", "ready"),
        ("queuedUP", "ready"),
        ("forcedUP", "ready"),
        ("checkingUP", "ready"),
        ("pausedUP", "ready"),
        ("downloading", "downloading"),
        ("forcedDL", "downloading"),
        ("moving", "downloading"),
        ("metaDL", "preparing"),
        ("forcedMetaDL", "preparing"),
        ("checkingResumeData", "preparing"),
        ("checkingDL", "preparing"),
        ("queuedDL", "preparing"),
        ("error", "problem"),
        ("missingFiles", "problem"),
        ("stalledDL", "stalled"),
        ("unknown", "stalled"),
        ("somethingNew", "stalled"),
        ("", "stalled"),
    ],
)
def test_plain_state_of_every_qbittorrent_state(state: str, expected: str) -> None:
    assert plain_state({"state": state}) == expected


def test_a_row_without_a_state_is_stalled() -> None:
    assert plain_state({}) == "stalled"


@pytest.mark.parametrize("state", ["stoppedDL", "pausedDL"])
def test_a_stopped_torrent_is_preparing_only_while_the_portal_holds_it(state: str) -> None:
    assert plain_state({"state": state, "tags": PENDING_TAGS}) == "preparing"
    assert plain_state({"state": state, "tags": ""}) == "stalled"
    assert plain_state({"state": state, "tags": "fx"}) == "stalled"
    assert plain_state({"state": state}) == "stalled"


def test_only_the_finished_states_read_as_ready() -> None:
    every_state = [
        "error",
        "missingFiles",
        "uploading",
        "stoppedUP",
        "queuedUP",
        "stalledUP",
        "checkingUP",
        "forcedUP",
        "downloading",
        "metaDL",
        "forcedMetaDL",
        "stoppedDL",
        "queuedDL",
        "stalledDL",
        "checkingDL",
        "forcedDL",
        "checkingResumeData",
        "moving",
        "unknown",
        "pausedUP",
        "pausedDL",
    ]
    ready = {s for s in every_state if plain_state({"state": s, "tags": PENDING_TAGS}) == "ready"}

    assert ready == set(READY_STATES)


@pytest.mark.parametrize(
    ("state", "progress", "expected"),
    [
        ("downloading", 0.4567, 45),
        ("downloading", 0.999, 99),
        ("moving", 1.0, 99),
        ("downloading", "x", 0),
        ("downloading", -0.5, 0),
        ("downloading", None, 0),
        ("uploading", 0.98, 100),
    ],
)
def test_progress_is_a_whole_percent_and_100_only_when_ready(
    state: str, progress: object, expected: int
) -> None:
    candidate = {"state": state, "progress": progress}

    assert percent(candidate, plain_state(candidate)) == expected


@pytest.mark.parametrize(
    ("state", "eta", "expected"),
    [
        ("downloading", 600, 600),
        ("downloading", 8640000, None),
        ("downloading", 8639999, 8639999),
        ("downloading", 0, None),
        ("downloading", -1, None),
        ("stalledDL", 600, None),
        ("moving", 600, None),
        ("uploading", 600, None),
        ("downloading", "soon", None),
    ],
)
def test_eta_only_for_a_downloading_torrent_with_a_real_estimate(
    state: str, eta: object, expected: int | None
) -> None:
    candidate = {"state": state, "eta": eta}

    assert eta_of(candidate, plain_state(candidate)) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("a" * 40, None),
        ("F" * 64, None),
        ("", None),
        ("   ", None),
        (None, None),
        ("Sintel 1080p", "Sintel 1080p"),
        ("a" * 41, "a" * 41),
    ],
)
def test_a_bare_info_hash_is_never_a_name(name: str | None, expected: str | None) -> None:
    assert display_name({"name": name}) == expected


def test_download_id_is_a_keyed_16_digit_hex_of_the_info_hash() -> None:
    torrent_hash = "0123456789abcdef0123456789abcdef01234567"
    expected = hmac.new(
        SECRET.encode(), b"download-id:" + torrent_hash.encode(), hashlib.sha256
    ).hexdigest()[:16]

    value = download_id(SECRET, torrent_hash)

    assert value == expected
    assert re.fullmatch(r"[0-9a-f]{16}", value)
    assert download_id(SECRET, torrent_hash) == value
    assert download_id("another-secret-0123456789abcdef", torrent_hash) != value
    assert download_id(SECRET, torrent_hash.upper()) == value


def test_a_ready_torrent_leaves_the_list_exactly_at_the_window() -> None:
    settings = make_settings()
    ready = {"state": "uploading", "progress": 1.0}
    edge = row("e" * 40, completion_on=int(NOW) - 7 * DAY, **ready)
    inside = row("f" * 40, completion_on=int(NOW) - 7 * DAY + 1, **ready)

    shown = items_of([edge, inside], settings)

    assert [item["id"] for item in shown] == [download_id(SECRET, "f" * 40)]


def test_the_window_counts_from_the_add_time_without_a_completion_time() -> None:
    ready = {"state": "uploading", "progress": 1.0, "completion_on": -1}
    old = row("1" * 40, added_on=int(NOW) - 8 * DAY, **ready)
    recent = row("2" * 40, added_on=int(NOW) - 2 * DAY, **ready)

    shown = items_of([old, recent])

    assert [item["id"] for item in shown] == [download_id(SECRET, "2" * 40)]


def test_the_window_follows_the_setting() -> None:
    ready = row(state="uploading", progress=1.0, completion_on=int(NOW) - 2 * DAY)

    assert items_of([ready], make_settings(completed_visible_days=1)) == []
    assert len(items_of([ready], make_settings(completed_visible_days=3))) == 1


def test_a_downloading_torrent_is_never_hidden_by_age() -> None:
    old = row(added_on=int(NOW) - 30 * DAY)

    (item,) = items_of([old])

    assert item["state"] == "downloading"


@pytest.mark.parametrize(
    ("category", "expected"),
    [("Film", "film"), ("SerieTV", "serie")],
)
def test_the_two_categories_give_the_two_types(category: str, expected: str) -> None:
    (item,) = items_of([row(category=category)])

    assert item["type"] == expected


@pytest.mark.parametrize("category", ["Film/Extra", "film", "", "Other", "SerieTV/Old"])
def test_every_other_category_is_dropped(category: str) -> None:
    assert items_of([row(category=category)]) == []


def test_an_item_has_exactly_the_seven_documented_keys() -> None:
    (item,) = items_of([row()])

    assert set(item) == {"id", "name", "type", "state", "progress", "eta_seconds", "action"}
    assert item["action"] == "cancel"
    assert item["eta_seconds"] == 600
    assert item["progress"] == 50


def test_a_ready_item_can_be_removed_and_a_problem_item_can_be_cancelled() -> None:
    ready = row("1" * 40, state="stalledUP", progress=1.0, completion_on=int(NOW) - 60)
    broken = row("2" * 40, state="error")

    actions = {item["state"]: item["action"] for item in items_of([ready, broken])}

    assert actions == {"ready": "remove", "problem": "cancel"}


def test_active_rows_come_first_then_newest_first_inside_each_group() -> None:
    old_active = row("1" * 40, added_on=int(NOW) - 5000)
    new_active = row("2" * 40, added_on=int(NOW) - 100)
    stalled = row("3" * 40, state="stalledDL", added_on=int(NOW) - 3000)
    done_old = row("4" * 40, state="uploading", completion_on=int(NOW) - 4000)
    done_new = row("5" * 40, state="uploading", completion_on=int(NOW) - 200)
    broken = row("6" * 40, state="error", added_on=int(NOW) - 50)

    shown = items_of([done_old, broken, old_active, done_new, stalled, new_active])

    assert [item["id"] for item in shown] == [download_id(SECRET, h * 40) for h in "231654"]


def test_equal_timestamps_fall_back_to_the_id_so_two_polls_agree() -> None:
    rows = [row(h * 40, added_on=int(NOW) - 100) for h in "abc"]

    first = items_of(rows)
    second = items_of(list(reversed(rows)))

    assert first == second
    assert [item["id"] for item in first] == sorted(item["id"] for item in first)


def test_a_completion_time_beats_the_add_time_for_the_order() -> None:
    added_early_finished_late = row(
        "1" * 40, state="uploading", added_on=int(NOW) - 9000, completion_on=int(NOW) - 100
    )
    added_late_finished_early = row(
        "2" * 40, state="uploading", added_on=int(NOW) - 500, completion_on=int(NOW) - 3000
    )

    shown = items_of([added_late_finished_early, added_early_finished_late])

    assert [item["id"] for item in shown] == [
        download_id(SECRET, "1" * 40),
        download_id(SECRET, "2" * 40),
    ]


def test_downloads_list_windows_have_the_documented_defaults() -> None:
    settings = make_settings()

    assert settings.completed_visible_days == 7
    assert settings.failed_visible_hours == 24
    assert settings.completed_visible_seconds == 7 * DAY
    assert settings.failed_visible_seconds == 24 * 3600
    with pytest.raises(ValidationError):
        make_settings(completed_visible_days=0)
    with pytest.raises(ValidationError):
        make_settings(failed_visible_hours=0)


# -- job rows (D-29, D-30, D-27) ------------------------------------------------------------

JOB_ID = "0123456789abcdef"
FAILURES = [JobState.REJECTED, JobState.UNSUPPORTED, JobState.UNAVAILABLE, JobState.FAILED]
ITEM_KEYS = {"id", "name", "type", "state", "progress", "eta_seconds", "action"}


def job(
    job_id: str = JOB_ID,
    state: JobState = JobState.PREPARING,
    *,
    torrent_hash: str | None = None,
    name: str | None = "Sintel",
    created_at: float = NOW - 100,
    finished_at: float | None = None,
) -> Job:
    return Job(
        job_id=job_id,
        result_id="r" * 16,
        type="film",
        state=state,
        torrent_hash=torrent_hash,
        created_at=created_at,
        name=name,
        finished_at=finished_at,
    )


def items_with_jobs(rows: list[dict], jobs: list[Job]) -> list[dict]:
    return build_items(rows, make_settings(), now=NOW, secret=SECRET, jobs=jobs)


def test_the_listed_failure_states_are_the_four_failures() -> None:
    assert FAILED_JOB_STATES == {"rejected", "unsupported", "unavailable", "failed"}


def test_a_preparing_job_without_a_torrent_is_listed_with_cancel() -> None:
    (item,) = items_with_jobs([], [job()])

    assert set(item) == ITEM_KEYS
    assert item == {
        "id": JOB_ID,
        "name": "Sintel",
        "type": "film",
        "state": "preparing",
        "progress": 0,
        "eta_seconds": None,
        "action": "cancel",
    }


def test_a_preparing_job_gives_way_to_the_torrent_carrying_its_job_tag() -> None:
    tagged = row("a" * 40, state="stoppedDL", tags=PENDING_TAGS, name="a" * 40)

    shown = items_with_jobs([tagged], [job()])

    assert [item["id"] for item in shown] == [download_id(SECRET, "a" * 40)]


def test_a_preparing_job_gives_way_to_the_torrent_with_its_hash() -> None:
    shown = items_with_jobs([row("b" * 40)], [job(torrent_hash="b" * 40)])

    assert [item["id"] for item in shown] == [download_id(SECRET, "b" * 40)]


def test_a_preparing_job_whose_hash_is_not_listed_still_shows() -> None:
    # The torrent is in another category (or gone): nothing represents the attempt.
    other = row("c" * 40, category="Other")

    shown = items_with_jobs([other], [job(torrent_hash="c" * 40)])

    assert [item["id"] for item in shown] == [JOB_ID]


@pytest.mark.parametrize("state", [JobState.STARTED, JobState.DUPLICATE])
def test_started_and_duplicate_jobs_never_get_a_row(state: JobState) -> None:
    assert items_with_jobs([], [job(state=state, finished_at=NOW - 10)]) == []


@pytest.mark.parametrize("state", FAILURES)
def test_a_young_failure_is_listed_with_its_plain_state(state: JobState) -> None:
    (item,) = items_with_jobs([], [job(state=state, finished_at=NOW - 60)])

    assert item["state"] == state.value
    assert item["action"] is None
    assert item["progress"] == 0
    assert item["eta_seconds"] is None


def test_a_failure_row_leaves_exactly_at_the_window() -> None:
    window = 24 * 3600

    old = items_with_jobs([], [job(state=JobState.FAILED, finished_at=NOW - window)])
    young = items_with_jobs([], [job(state=JobState.FAILED, finished_at=NOW - window + 1)])

    assert old == []
    assert [item["id"] for item in young] == [JOB_ID]


def test_a_failure_job_that_has_not_ended_is_not_listed() -> None:
    assert items_with_jobs([], [job(state=JobState.FAILED, finished_at=None)]) == []


def test_a_bare_hash_torrent_takes_the_name_of_the_job_with_its_hash() -> None:
    magnet = row("d" * 40, name="d" * 40, state="metaDL")

    (item,) = items_with_jobs([magnet], [job(torrent_hash="d" * 40, name="Sintel (2010)")])

    assert item["name"] == "Sintel (2010)"


def test_a_bare_hash_torrent_takes_the_name_of_the_job_its_tag_names() -> None:
    magnet = row("e" * 40, name="e" * 40, state="stoppedDL", tags=PENDING_TAGS)

    (item,) = items_with_jobs([magnet], [job(name="Sintel (2010)")])

    assert item["name"] == "Sintel (2010)"


def test_a_bare_hash_torrent_without_a_job_stays_unnamed() -> None:
    (item,) = items_with_jobs(
        [row("f" * 40, name="f" * 40)], [job("1" * 16, torrent_hash="9" * 40)]
    )

    assert item["name"] is None


def test_a_real_torrent_name_is_never_replaced_by_the_job_name() -> None:
    (item,) = items_with_jobs([row("a" * 40, name="Real Name")], [job(torrent_hash="a" * 40)])

    assert item["name"] == "Real Name"


def test_every_film_or_serie_torrent_appears_exactly_once() -> None:
    admin = row("1" * 40, name="By hand", state="stalledDL")
    started = row("2" * 40, state="downloading")
    preparing = row(
        "3" * 40, name="3" * 40, state="stoppedDL", tags="fx, fx-pending, fx-job-" + "c" * 16
    )
    leftover = row("4" * 40, state="downloading")
    jobs = [
        job("a" * 16, JobState.STARTED, torrent_hash="2" * 40, finished_at=NOW - 5),
        job("c" * 16, JobState.PREPARING),
        job("d" * 16, JobState.FAILED, torrent_hash="4" * 40, finished_at=NOW - 5),
        job("e" * 16, JobState.PREPARING),  # a torrent-less preparing job: the one extra row
    ]

    shown = items_with_jobs([admin, started, preparing, leftover], jobs)

    ids = [item["id"] for item in shown]
    for torrent_hash in "1234":
        assert ids.count(download_id(SECRET, torrent_hash * 40)) == 1
    assert ids.count("e" * 16) == 1
    assert ids.count("c" * 16) == 0  # represented by its torrent
    assert ids.count("a" * 16) == 0
    assert ids.count("d" * 16) == 1  # the failed attempt is a row of its own
    assert len(shown) == 4 + 2  # four torrents plus the preparing and the failed job rows
    assert len(set(ids)) == len(ids)


def test_job_rows_join_the_order_by_group_then_newest_first() -> None:
    downloading = row("1" * 40, state="downloading", added_on=int(NOW) - 5000)
    ready = row("2" * 40, state="uploading", completion_on=int(NOW) - 2000)
    jobs = [
        job("b" * 16, JobState.REJECTED, finished_at=NOW - 1000),
        job("a" * 16, JobState.FAILED, finished_at=NOW - 3000),
        job("c" * 16, JobState.PREPARING, created_at=NOW - 10),
    ]

    shown = items_with_jobs([ready, downloading], jobs)

    assert [item["id"] for item in shown] == [
        "c" * 16,  # active group, newest first: created 10 s ago beats the add 5000 s ago
        download_id(SECRET, "1" * 40),
        "b" * 16,  # second group: finished 1000 s ago
        download_id(SECRET, "2" * 40),  # completed 2000 s ago
        "a" * 16,  # finished 3000 s ago
    ]


def test_equal_job_timestamps_fall_back_to_the_id() -> None:
    jobs = [
        job("b" * 16, JobState.FAILED, finished_at=NOW - 50),
        job("a" * 16, JobState.FAILED, finished_at=NOW - 50),
    ]

    assert [item["id"] for item in items_with_jobs([], jobs)] == ["a" * 16, "b" * 16]


async def test_the_registry_stamps_finished_at_once_for_every_ending() -> None:
    now = [100.0]
    registry = JobRegistry(clock=lambda: now[0])
    done, crashed, cancelled = job("1" * 16), job("2" * 16), job("3" * 16)

    async def fine() -> None:
        done.state = JobState.STARTED

    async def boom() -> None:
        raise RuntimeError("x")

    async def wait_forever() -> None:
        await asyncio.sleep(3600)

    registry.spawn(done, fine())
    registry.spawn(crashed, boom())
    task = registry.spawn(cancelled, wait_forever())
    await asyncio.sleep(0.01)
    assert cancelled.finished_at is None  # still running
    now[0] = 250.0
    task.cancel()
    await asyncio.gather(
        *(registry.task(j.job_id) for j in (done, crashed, cancelled)), return_exceptions=True
    )

    assert done.finished_at == 100.0
    assert crashed.finished_at == 100.0
    assert crashed.state is JobState.FAILED
    assert cancelled.finished_at == 250.0


async def test_pruning_drops_the_oldest_finished_job_and_never_a_running_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(jobs_module, "MAX_JOBS", 3)
    now = [0.0]
    registry = JobRegistry(clock=lambda: now[0])
    gate = asyncio.Event()
    first, second, third = job("1" * 16), job("2" * 16), job("3" * 16)

    async def finish_when_open() -> None:
        await gate.wait()
        first.state = JobState.STARTED

    async def finish_now(target: Job) -> None:
        target.state = JobState.STARTED

    registry.spawn(first, finish_when_open())  # inserted first, finishes last
    now[0] = 10.0
    registry.spawn(second, finish_now(second))
    await asyncio.sleep(0.01)  # second ends at 10
    now[0] = 20.0
    registry.spawn(third, finish_now(third))
    await asyncio.sleep(0.01)  # third ends at 20
    now[0] = 30.0
    gate.set()
    await asyncio.sleep(0.01)  # first ends at 30
    assert (first.finished_at, second.finished_at, third.finished_at) == (30.0, 10.0, 20.0)

    fourth = job("4" * 16)
    registry.spawn(fourth, finish_now(fourth))

    assert registry.get("2" * 16) is None  # the oldest finished one went
    assert registry.get("1" * 16) is not None
    assert registry.get("3" * 16) is not None


async def test_pruning_never_drops_a_running_job(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jobs_module, "MAX_JOBS", 2)
    registry = JobRegistry(clock=lambda: 1.0)
    running, ended = job("1" * 16), job("2" * 16)

    async def hold() -> None:
        await asyncio.sleep(3600)

    async def finish() -> None:
        ended.state = JobState.STARTED

    registry.spawn(running, hold())
    registry.spawn(ended, finish())
    await asyncio.sleep(0.01)

    other = job("3" * 16)
    registry.spawn(other, hold())

    assert registry.get("1" * 16) is running
    assert registry.get("2" * 16) is None
    assert registry.get("3" * 16) is other
    await registry.shutdown()
