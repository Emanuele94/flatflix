"""Bootstrap configures qBittorrent before downloads are possible (DOWN-03, FILT-01, DOWN-02)."""

import json
from urllib.parse import parse_qsl

import pytest
from pydantic import SecretStr

from app.config import Settings
from app.download.allowlist import EXCLUDED_FILE_PATTERNS
from app.qbit.bootstrap import Bootstrapper, Readiness, build_preferences, require_ready
from app.qbit.client import QbitClient
from app.tools import doctor
from tests.conftest import (
    PORTAL_PASS_HASH,
    PORTAL_SECRET_KEY,
    PORTAL_USER,
    QBIT_PASS,
    QBIT_URL,
    QBIT_USER,
)
from tests.fakeqbit import FakeQbit

FILM = "/media/Film"
SERIES = "/media/SerieTV"


def make_bootstrapper(
    fake: FakeQbit, settings: Settings, readiness: Readiness | None = None, sleep=None
) -> tuple[Bootstrapper, Readiness]:
    client = QbitClient(
        settings.qbittorrent_url,
        settings.qbittorrent_user,
        settings.qbittorrent_pass,
        transport=fake.transport,
    )
    readiness = readiness or Readiness()
    kwargs = {"sleep": sleep} if sleep else {}
    return Bootstrapper(client, settings, readiness, **kwargs), readiness


async def test_fresh_qbittorrent_gets_exactly_film_and_serietv(
    fake_qbit: FakeQbit, settings: Settings
) -> None:
    bootstrapper, readiness = make_bootstrapper(fake_qbit, settings)

    await bootstrapper.run_once()

    assert {n: c["savePath"] for n, c in fake_qbit.category_table.items()} == {
        "Film": FILM,
        "SerieTV": SERIES,
    }
    assert readiness.state == "ready"


async def test_preferences_carry_filt01_patterns_temp_path_and_auto_tmm(
    fake_qbit: FakeQbit, settings: Settings
) -> None:
    bootstrapper, _ = make_bootstrapper(fake_qbit, settings)

    await bootstrapper.run_once()

    prefs = fake_qbit.preferences
    assert prefs["excluded_file_names_enabled"] is True
    assert prefs["excluded_file_names"].split("\n")[: len(EXCLUDED_FILE_PATTERNS)] == list(
        EXCLUDED_FILE_PATTERNS
    )
    assert prefs["auto_tmm_enabled"] is True
    assert prefs["category_changed_tmm_enabled"] is True
    assert prefs["temp_path_enabled"] is True
    assert prefs["temp_path"] == "/incomplete"


def test_exclusion_list_is_never_empty_even_when_qbittorrent_had_none(
    settings: Settings,
) -> None:
    prefs = build_preferences(settings, "")

    assert prefs["excluded_file_names_enabled"] is True
    assert prefs["excluded_file_names"] == "\n".join(EXCLUDED_FILE_PATTERNS)


def test_admin_patterns_follow_the_fixed_list_without_case_insensitive_duplicates(
    settings: Settings,
) -> None:
    prefs = build_preferences(settings, "*.txt\n*.EXE\n*.nfo\n*.TXT")

    assert prefs["excluded_file_names"].split("\n") == [*EXCLUDED_FILE_PATTERNS, "*.txt", "*.nfo"]


async def test_categories_are_never_taken_from_a_request(settings: Settings) -> None:
    assert settings.category_paths == {"Film": FILM, "SerieTV": SERIES}


async def test_not_ready_guard_returns_503_until_ready(
    fake_qbit: FakeQbit, settings: Settings
) -> None:
    from types import SimpleNamespace

    from fastapi import HTTPException

    readiness = Readiness()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(readiness=readiness)))

    with pytest.raises(HTTPException) as caught:
        require_ready(request)  # type: ignore[arg-type]
    assert caught.value.status_code == 503
    assert caught.value.detail == "not_ready"

    readiness.mark_ready()
    require_ready(request)  # type: ignore[arg-type]


async def test_doctor_reports_paths_and_never_credentials(
    fake_qbit: FakeQbit, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    bootstrapper, _ = make_bootstrapper(fake_qbit, settings)
    await bootstrapper.run_once()
    client = QbitClient(
        settings.qbittorrent_url,
        settings.qbittorrent_user,
        settings.qbittorrent_pass,
        transport=fake_qbit.transport,
    )

    checks = await doctor.collect(client, settings)
    for ok, text in checks:
        print(doctor.line(ok, text))

    out = capsys.readouterr().out
    assert all(ok for ok, _ in checks)
    assert FILM in out and SERIES in out
    assert QBIT_USER not in out and QBIT_PASS not in out
    assert "password" not in out.lower()
    assert PORTAL_USER not in out
    await client.aclose()


async def test_doctor_fails_against_an_unconfigured_qbittorrent(
    fake_qbit: FakeQbit, settings: Settings
) -> None:
    client = QbitClient(
        settings.qbittorrent_url,
        settings.qbittorrent_user,
        settings.qbittorrent_pass,
        transport=fake_qbit.transport,
    )

    checks = await doctor.collect(client, settings)

    assert not all(ok for ok, _ in checks)
    await client.aclose()


def test_settings_reject_bad_category_names_and_paths() -> None:
    base = {
        "qbittorrent_url": QBIT_URL,
        "qbittorrent_user": QBIT_USER,
        "qbittorrent_pass": SecretStr(QBIT_PASS),
        "app_user": PORTAL_USER,
        "app_pass_hash": SecretStr(PORTAL_PASS_HASH),
        "secret_key": SecretStr(PORTAL_SECRET_KEY),
    }
    for bad in (
        {"category_film": "Film/../x"},
        {"category_tv": "Serie TV"},
        {"save_path_film": "media/Film"},
        {"save_path_tv": "/media/../etc"},
        {"incomplete_path": "relative"},
        {"search_plugins": "ok Bad-Name"},
        {"search_plugins_ref": "main"},
        {"category_film": "Same", "category_tv": "Same"},
    ):
        with pytest.raises(ValueError):
            Settings(**base, **bad)


def test_fake_wire_format_matches_the_documented_forms() -> None:
    # The fake decodes the `json` form field the same way the real WebAPI does.
    assert json.loads(dict(parse_qsl("json=%7B%22a%22%3A+1%7D"))["json"]) == {"a": 1}
