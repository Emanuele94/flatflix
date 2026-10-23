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
