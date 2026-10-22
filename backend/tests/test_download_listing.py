"""The pure downloads-list rules: state table, progress, ETA, names, window, order (D-25..D-35).

No I/O: rows go in, items come out. Settings are built like `tests.conftest.settings` does.
"""

import hashlib
import hmac
import re

import pytest
from pydantic import SecretStr, ValidationError

from app.config import Settings
from app.download.listing import (
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
