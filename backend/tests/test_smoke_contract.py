"""The smoke probe checks the same eight-key list contract as the API (QUAR-04, D-77).

`scripts/smoke.py` is a standalone standard-library script, so it is loaded by path. Only its pure
parts are exercised here: the per-item check and the leak markers.
"""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

SMOKE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "smoke.py"


@pytest.fixture(scope="module")
def smoke() -> ModuleType:
    spec = importlib.util.spec_from_file_location("flatflix_smoke", SMOKE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def item(**overrides: object) -> dict:
    base: dict = {
        "id": "0123456789abcdef",
        "name": "Dune",
        "type": "film",
        "state": "checking",
        "progress": 99,
        "eta_seconds": None,
        "action": "cancel",
        "skipped": 0,
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    ("state", "action"),
    [("checking", "cancel"), ("check_failed", None), ("ready", "remove"), ("problem", "cancel")],
)
def test_an_item_with_the_eight_keys_and_a_new_state_is_accepted(
    smoke: ModuleType, state: str, action: str | None
) -> None:
    smoke.check_item(item(state=state, action=action, skipped=2))


def test_an_item_without_skipped_is_refused(smoke: ModuleType) -> None:
    seven = item()
    del seven["skipped"]

    with pytest.raises(smoke.Fail, match="eight"):
        smoke.check_item(seven)


@pytest.mark.parametrize("skipped", [-1, "2", True, 1.5, None])
def test_a_skipped_that_is_not_a_non_negative_integer_is_refused(
    smoke: ModuleType, skipped: object
) -> None:
    with pytest.raises(smoke.Fail, match="skipped"):
        smoke.check_item(item(skipped=skipped))


def test_the_contract_constants_name_the_new_keys_and_states(smoke: ModuleType) -> None:
    assert "skipped" in smoke.DOWNLOAD_LIST_KEYS
    assert len(smoke.DOWNLOAD_LIST_KEYS) == 8
    assert {"checking", "check_failed"} <= smoke.DOWNLOAD_ITEM_STATES


def test_the_leak_markers_include_the_quarantine_layout(
    smoke: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(smoke, "read_env_value", lambda key: f"value-of-{key}")

    markers = set(smoke.leak_markers().values())

    assert {"/quarantine", "/rejected", "/data/"} <= markers


@pytest.mark.parametrize(
    ("value", "refused"),
    [(None, True), ("40", True), ("6", True), ("5", False), ("1", False), ("abc", True)],
)
def test_the_handoff_probe_refuses_a_film_minimum_above_five_minutes(
    smoke: ModuleType, monkeypatch: pytest.MonkeyPatch, value: str | None, refused: bool
) -> None:
    monkeypatch.setattr(smoke, "read_env_optional", lambda key: value)

    if refused:
        with pytest.raises(smoke.Fail) as caught:
            smoke.check_handoff_threshold()
        assert caught.value.step == "handoff-threshold"
        assert "MIN_FILM_DURATION_MINUTES=5" in caught.value.reason
    else:
        smoke.check_handoff_threshold()


def test_the_started_film_is_the_open_licensed_item_the_list_did_not_hold_before(
    smoke: ModuleType,
) -> None:
    old = item(id="a" * 16, name="Sintel.2010.1080p", type="film", state="ready")
    other = item(id="b" * 16, name="Some Other Film", type="film", state="downloading")
    series = item(id="c" * 16, name="Sintel S01", type="serie", state="downloading")
    new = item(id="d" * 16, name="Big.Buck.Bunny.1080p", type="film", state="downloading")
    before = smoke.open_film_states([old, other, series])

    assert before == {"a" * 16: "ready"}
    assert smoke.pick_started_film([old, other, series], before) is None
    assert smoke.pick_started_film([old, other, series, new], before) == new
    # the same torrent again after its earlier entry finished: picked once it is active
    again = item(id="a" * 16, name="Sintel.2010.1080p", type="film", state="downloading")
    assert smoke.pick_started_film([again], before) == again
