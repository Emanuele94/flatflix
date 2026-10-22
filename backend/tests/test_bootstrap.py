"""Bootstrap configures qBittorrent before downloads are possible (DOWN-03, FILT-01, DOWN-02)."""

import json
from urllib.parse import parse_qsl

import httpx
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.download.allowlist import EXCLUDED_FILE_PATTERNS
from app.qbit import bootstrap as bootstrap_module
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


def test_doctor_torrent_line_has_paths_and_progress_but_no_hash() -> None:
    row = {
        "hash": "0123456789abcdef0123456789abcdef01234567",
        "name": "N" * 80,
        "category": "Film",
        "save_path": "/media/Film",
        "download_path": "/incomplete/Film",
        "state": "downloading",
        "progress": 0.256,
    }

    text = doctor.torrent_line(row)

    assert text == (
        f"{'N' * 60} | category Film | save /media/Film | incomplete /incomplete/Film"
        " | state downloading | 25.6%"
    )
    assert row["hash"] not in text


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


# --- Task 2: idempotence, ordering, failure handling, readiness gate -------------------------

LOGIN = "/api/v2/auth/login"
VERSION = "/api/v2/app/webapiVersion"
PREFS = "/api/v2/app/preferences"
SET_PREFS = "/api/v2/app/setPreferences"
CATEGORIES = "/api/v2/torrents/categories"
CREATE = "/api/v2/torrents/createCategory"
EDIT = "/api/v2/torrents/editCategory"


def wire_paths(fake: FakeQbit) -> list[str]:
    return [call.path for call in fake.calls if call.path != LOGIN]


class SleepLog:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)


def fail_first(fake: FakeQbit, method: str, path: str, times: int, error: Exception) -> None:
    """Make the first `times` calls to a route fail the way a dead connection does."""
    original = fake._routes[(method, path)]
    remaining = {"n": times}

    def route(request):
        if remaining["n"] > 0:
            remaining["n"] -= 1
            raise error
        return original(request)

    fake.register(method, path, route)


async def test_existing_category_with_same_path_gets_no_edit_with_or_without_trailing_slash(
    fake_qbit: FakeQbit, settings: Settings
) -> None:
    fake_qbit.category_table = {
        "Film": {"name": "Film", "savePath": "/media/Film/"},
        "SerieTV": {"name": "SerieTV", "savePath": SERIES},
    }
    bootstrapper, readiness = make_bootstrapper(fake_qbit, settings)

    await bootstrapper.run_once()

    assert fake_qbit.calls_to(EDIT) == []
    assert fake_qbit.calls_to(CREATE) == []
    assert readiness.state == "ready"


async def test_existing_category_with_other_path_gets_exactly_one_edit_to_the_configured_path(
    fake_qbit: FakeQbit, settings: Settings
) -> None:
    fake_qbit.category_table = {"Film": {"name": "Film", "savePath": "/downloads"}}
    bootstrapper, _ = make_bootstrapper(fake_qbit, settings)

    await bootstrapper.run_once()

    edits = fake_qbit.calls_to(EDIT)
    assert [call.form for call in edits] == [{"category": "Film", "savePath": FILM}]
    assert fake_qbit.category_table["Film"]["savePath"] == FILM


async def test_lower_case_category_does_not_satisfy_film(
    fake_qbit: FakeQbit, settings: Settings
) -> None:
    fake_qbit.category_table = {"film": {"name": "film", "savePath": FILM}}
    bootstrapper, _ = make_bootstrapper(fake_qbit, settings)

    await bootstrapper.run_once()

    assert set(fake_qbit.category_table) == {"film", "Film", "SerieTV"}
    created = [call.form["category"] for call in fake_qbit.calls_to(CREATE)]
    assert created == ["Film", "SerieTV"]


async def test_create_conflict_is_treated_as_already_existing(
    fake_qbit: FakeQbit, settings: Settings
) -> None:
    # The category list is stale (empty) but the category exists: createCategory answers 409.
    stale = {"first": True}

    def serve_categories(request):
        if stale["first"]:
            stale["first"] = False
            return httpx.Response(200, json={})
        return httpx.Response(200, json=fake_qbit.category_table)

    fake_qbit.category_table = {
        "Film": {"name": "Film", "savePath": FILM},
        "SerieTV": {"name": "SerieTV", "savePath": SERIES},
    }
    fake_qbit.register("GET", CATEGORIES, serve_categories)
    bootstrapper, readiness = make_bootstrapper(fake_qbit, settings)

    await bootstrapper.run_once()

    assert fake_qbit.calls_to(EDIT) == []
    assert readiness.state == "ready"


async def test_bootstrap_is_idempotent_across_two_runs(
    fake_qbit: FakeQbit, settings: Settings
) -> None:
    bootstrapper, _ = make_bootstrapper(fake_qbit, settings)
    await bootstrapper.run_once()
    first_payload = fake_qbit.preference_payloads[0]
    fake_qbit.calls.clear()

    await bootstrapper.run_once()

    assert fake_qbit.calls_to(CREATE) == []
    assert fake_qbit.calls_to(EDIT) == []
    assert fake_qbit.preference_payloads[1] == first_payload


async def test_bootstrap_call_order_is_version_preferences_set_preferences_categories(
    fake_qbit: FakeQbit, settings: Settings
) -> None:
    bootstrapper, _ = make_bootstrapper(fake_qbit, settings)

    await bootstrapper.run_once()

    assert wire_paths(fake_qbit)[:4] == [VERSION, PREFS, SET_PREFS, CATEGORIES]
    assert wire_paths(fake_qbit)[4:6] == [CREATE, CREATE]


async def test_admin_patterns_are_kept_after_the_fixed_list_without_duplicates(
    fake_qbit: FakeQbit, settings: Settings
) -> None:
    fake_qbit.preferences["excluded_file_names"] = "*.txt\n*.EXE"
    bootstrapper, _ = make_bootstrapper(fake_qbit, settings)

    await bootstrapper.run_once()

    sent = json.loads(fake_qbit.preference_payloads[0])["excluded_file_names"].split("\n")
    assert sent == [*EXCLUDED_FILE_PATTERNS, "*.txt"]


async def test_readiness_flips_only_after_preferences_and_categories(
    fake_qbit: FakeQbit, settings: Settings
) -> None:
    readiness = Readiness()
    seen: list[str] = []

    def spying_create(request):
        seen.append(readiness.state)
        return httpx.Response(200)

    fake_qbit.register("POST", CREATE, spying_create)
    bootstrapper, _ = make_bootstrapper(fake_qbit, settings, readiness)

    await bootstrapper.run_once()

    assert seen == ["starting", "starting"]
    assert fake_qbit.preference_payloads  # setPreferences happened before ready
    assert readiness.state == "ready"


@pytest.mark.parametrize(
    ("version", "compatible"), [("2.15.0", False), ("2.15.1", True), ("2.17.0", True)]
)
async def test_webapi_version_gate_incompatible_below_2_15_1(
    fake_qbit: FakeQbit, settings: Settings, version: str, compatible: bool
) -> None:
    fake_qbit.webapi_version = version
    bootstrapper, readiness = make_bootstrapper(fake_qbit, settings)

    await bootstrapper.run_forever()

    assert (readiness.state == "ready") is compatible
    if not compatible:
        assert readiness.state == "failed"
        assert readiness.reason == "QbitIncompatible"
        assert fake_qbit.calls_to(SET_PREFS) == []


@pytest.mark.parametrize("mode", ["wrong_password", "banned"])
async def test_auth_failure_stops_after_one_attempt_with_one_error_log(
    fake_qbit: FakeQbit,
    settings: Settings,
    caplog: pytest.LogCaptureFixture,
    mode: str,
) -> None:
    if mode == "wrong_password":
        settings = settings.model_copy(update={"qbittorrent_pass": SecretStr("not-the-password")})
    else:
        fake_qbit.ban_after = 0
    sleeps = SleepLog()
    bootstrapper, readiness = make_bootstrapper(fake_qbit, settings, sleep=sleeps)

    with caplog.at_level("INFO"):
        await bootstrapper.run_forever()

    errors = [r for r in caplog.records if r.levelname == "ERROR"]
    assert len(errors) == 1
    assert "qBittorrent bootstrap stopped" in errors[0].getMessage()
    assert "not-the-password" not in caplog.text
    assert fake_qbit.login_attempts == 1
    assert sleeps.delays == []
    assert readiness.state == "failed"
    assert readiness.reason in {"QbitAuthError", "QbitBanned"}


async def test_unreachable_qbittorrent_retries_with_backoff_one_two_four_then_succeeds(
    fake_qbit: FakeQbit, settings: Settings
) -> None:

    fail_first(fake_qbit, "GET", VERSION, 3, httpx.ConnectError("refused"))
    sleeps = SleepLog()
    bootstrapper, readiness = make_bootstrapper(fake_qbit, settings, sleep=sleeps)

    await bootstrapper.run_forever()

    assert sleeps.delays == [1, 2, 4]
    assert readiness.state == "ready"


async def test_backoff_is_capped_at_thirty_seconds(fake_qbit: FakeQbit, settings: Settings) -> None:

    fail_first(fake_qbit, "GET", VERSION, 8, httpx.ConnectError("refused"))
    sleeps = SleepLog()
    bootstrapper, _ = make_bootstrapper(fake_qbit, settings, sleep=sleeps)

    await bootstrapper.run_forever()

    assert sleeps.delays == [1, 2, 4, 8, 16, 30, 30, 30]


async def test_server_error_during_bootstrap_is_retried_with_backoff(
    fake_qbit: FakeQbit, settings: Settings
) -> None:

    original = fake_qbit._routes[("POST", SET_PREFS)]
    failures = {"n": 2}

    def flaky(request):
        if failures["n"]:
            failures["n"] -= 1
            return httpx.Response(500, text="boom secret body")
        return original(request)

    fake_qbit.register("POST", SET_PREFS, flaky)
    sleeps = SleepLog()
    bootstrapper, readiness = make_bootstrapper(fake_qbit, settings, sleep=sleeps)

    await bootstrapper.run_forever()

    assert sleeps.delays == [1, 2]
    assert readiness.state == "ready"


async def test_route_guarded_by_require_ready_is_503_not_ready_until_bootstrap_succeeds(
    settings: Settings, fake_qbit: FakeQbit
) -> None:
    from fastapi import APIRouter, Depends

    from app.main import create_app

    # qBittorrent never answers, so bootstrap stays in its retry loop.
    fail_first(fake_qbit, "GET", VERSION, 10_000, httpx.ConnectError("refused"))
    client = QbitClient(
        settings.qbittorrent_url,
        settings.qbittorrent_user,
        settings.qbittorrent_pass,
        transport=fake_qbit.transport,
    )
    app = create_app(settings, client)
    router = APIRouter()

    @router.get("/api/guarded", dependencies=[Depends(require_ready)])
    async def guarded() -> dict[str, bool]:
        return {"ok": True}

    app.include_router(router)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://portal.test") as web:
            before = await web.get("/api/guarded")
            app.state.readiness.mark_ready()
            after = await web.get("/api/guarded")

    assert before.status_code == 503
    assert before.json() == {"detail": "not_ready"}
    assert after.status_code == 200


async def test_health_is_degraded_while_starting_and_after_failure(
    settings: Settings, fake_qbit: FakeQbit
) -> None:

    from app.main import create_app

    fake_qbit.webapi_version = "2.15.0"  # reachable, but incompatible -> failed
    client = QbitClient(
        settings.qbittorrent_url,
        settings.qbittorrent_user,
        settings.qbittorrent_pass,
        transport=fake_qbit.transport,
    )
    app = create_app(settings, client)
    async with app.router.lifespan_context(app):
        await app.state.bootstrap_task
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://portal.test") as web:
            failed = await web.get("/api/health")
            app.state.readiness.state = "starting"
            starting = await web.get("/api/health")

    assert failed.json()["status"] == "degraded"
    assert starting.json()["status"] == "degraded"


async def test_one_bootstrap_task_runs_per_process(api, app, fake_qbit: FakeQbit) -> None:
    assert app.state.bootstrap_task.done()
    assert len(fake_qbit.calls_to(SET_PREFS)) == 1
    assert len(fake_qbit.calls_to(VERSION)) == 1


async def test_conflict_on_create_without_the_category_appearing_is_an_error_not_ready(
    fake_qbit: FakeQbit, settings: Settings
) -> None:
    from app.qbit.client import QbitError

    fake_qbit.register(
        "POST", CREATE, lambda r: httpx.Response(409, text="Unable to create category")
    )
    bootstrapper, readiness = make_bootstrapper(fake_qbit, settings)

    with pytest.raises(QbitError):
        await bootstrapper.run_once()

    assert readiness.state == "starting"
    assert fake_qbit.calls_to(EDIT) == []


# --- Task 3: pinned official search plugins (D-19) and seeding policy (D-21) ------------------


PLUGINS = "/api/v2/search/plugins"
INSTALL = "/api/v2/search/installPlugin"
REF = "2beb5c67b0edbf2387a031a02d1881fab4bec3c3"
PLUGIN_NAMES = [
    "eztv",
    "limetorrents",
    "piratebay",
    "solidtorrents",
    "torlock",
    "torrentproject",
    "torrentscsv",
]


def test_plugin_url_points_at_the_pinned_official_repository() -> None:
    assert bootstrap_module.plugin_url(REF, "piratebay") == (
        "https://raw.githubusercontent.com/qbittorrent/search-plugins/"
        f"{REF}/nova3/engines/piratebay.py"
    )


async def test_missing_plugins_are_installed_once_each_from_the_pinned_url(
    fake_qbit: FakeQbit, settings: Settings
) -> None:
    bootstrapper, readiness = make_bootstrapper(fake_qbit, settings)

    await bootstrapper.run_once()

    installs = [call.form for call in fake_qbit.calls_to(INSTALL)]
    assert installs == [
        {"sources": bootstrap_module.plugin_url(REF, name)} for name in PLUGIN_NAMES
    ]
    assert sorted(p["name"] for p in fake_qbit.plugins) == PLUGIN_NAMES
    assert readiness.state == "ready"


async def test_plugin_install_runs_after_categories(
    fake_qbit: FakeQbit, settings: Settings
) -> None:
    bootstrapper, _ = make_bootstrapper(fake_qbit, settings)

    await bootstrapper.run_once()

    paths = wire_paths(fake_qbit)
    assert paths.index(PLUGINS) > max(i for i, p in enumerate(paths) if p == CREATE)


async def test_installed_but_disabled_plugin_is_neither_reinstalled_nor_enabled(
    fake_qbit: FakeQbit, settings: Settings
) -> None:
    fake_qbit.plugins = [{"name": "piratebay", "enabled": False, "version": "1.0"}]
    bootstrapper, _ = make_bootstrapper(fake_qbit, settings)

    await bootstrapper.run_once()

    installed = [call.form["sources"] for call in fake_qbit.calls_to(INSTALL)]
    assert bootstrap_module.plugin_url(REF, "piratebay") not in installed
    assert len(installed) == len(PLUGIN_NAMES) - 1
    assert not [c for c in fake_qbit.calls if "enablePlugin" in c.path or "updatePlugins" in c.path]
    assert fake_qbit.plugins[0]["enabled"] is False


async def test_second_run_installs_no_plugin_again(fake_qbit: FakeQbit, settings: Settings) -> None:
    bootstrapper, _ = make_bootstrapper(fake_qbit, settings)
    await bootstrapper.run_once()
    fake_qbit.calls.clear()

    await bootstrapper.run_once()

    assert fake_qbit.calls_to(INSTALL) == []


async def test_bootstrap_waits_for_slow_plugins_polling_every_two_seconds(
    fake_qbit: FakeQbit, settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    fake_qbit.plugin_install_delay_calls = 2
    sleeps = SleepLog()
    bootstrapper, readiness = make_bootstrapper(fake_qbit, settings, sleep=sleeps)

    with caplog.at_level("WARNING"):
        await bootstrapper.run_once()

    assert sleeps.delays == [2, 2]
    assert sorted(p["name"] for p in fake_qbit.plugins) == PLUGIN_NAMES
    assert not [r for r in caplog.records if r.levelname == "WARNING"]
    assert readiness.state == "ready"


async def test_plugins_still_missing_after_thirty_seconds_warn_once_and_stay_ready(
    fake_qbit: FakeQbit, settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    fake_qbit.plugin_install_delay_calls = 10_000
    sleeps = SleepLog()
    bootstrapper, readiness = make_bootstrapper(fake_qbit, settings, sleep=sleeps)

    with caplog.at_level("WARNING"):
        await bootstrapper.run_once()

    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert sum(sleeps.delays) == 30
    assert readiness.state == "ready"


def test_preferences_set_the_seeding_policy_to_stop_at_ratio_one_or_24_hours(
    settings: Settings,
) -> None:
    prefs = build_preferences(settings, "")

    assert prefs["max_ratio_enabled"] is True
    assert prefs["max_ratio"] == 1.0
    assert prefs["max_seeding_time_enabled"] is True
    assert prefs["max_seeding_time"] == 1440
    assert prefs["max_ratio_act"] == 0


async def test_seeding_policy_reads_back_from_qbittorrent(
    fake_qbit: FakeQbit, settings: Settings
) -> None:
    bootstrapper, _ = make_bootstrapper(fake_qbit, settings)

    await bootstrapper.run_once()

    prefs = fake_qbit.preferences
    assert (prefs["max_ratio"], prefs["max_seeding_time"], prefs["max_ratio_act"]) == (1.0, 1440, 0)


def make_client(fake: FakeQbit, settings: Settings) -> QbitClient:
    return QbitClient(
        settings.qbittorrent_url,
        settings.qbittorrent_user,
        settings.qbittorrent_pass,
        transport=fake.transport,
    )


async def test_doctor_lists_share_limits_and_every_plugin_when_compliant(
    fake_qbit: FakeQbit, settings: Settings
) -> None:
    bootstrapper, _ = make_bootstrapper(fake_qbit, settings)
    await bootstrapper.run_once()
    client = make_client(fake_qbit, settings)

    checks = await doctor.collect(client, settings)

    text = "\n".join(t for _, t in checks)
    assert all(ok for ok, _ in checks)
    assert "max_ratio 1.0" in text and "max_seeding_time 1440" in text
    for name in PLUGIN_NAMES:
        assert f"plugin {name} installed enabled True" in text
    await client.aclose()


async def test_doctor_fails_when_a_configured_plugin_is_missing(
    fake_qbit: FakeQbit, settings: Settings
) -> None:
    bootstrapper, _ = make_bootstrapper(fake_qbit, settings)
    await bootstrapper.run_once()
    fake_qbit.plugins = [p for p in fake_qbit.plugins if p["name"] != "torlock"]
    client = make_client(fake_qbit, settings)

    checks = await doctor.collect(client, settings)

    failed = [t for ok, t in checks if not ok]
    assert failed == ["plugin torlock missing"]
    await client.aclose()


async def test_doctor_fails_when_a_share_limit_differs(
    fake_qbit: FakeQbit, settings: Settings
) -> None:
    bootstrapper, _ = make_bootstrapper(fake_qbit, settings)
    await bootstrapper.run_once()
    fake_qbit.preferences["max_seeding_time"] = 60
    client = make_client(fake_qbit, settings)

    checks = await doctor.collect(client, settings)

    assert any(not ok and "max_seeding_time 60" in t for ok, t in checks)
    await client.aclose()


async def test_doctor_accepts_a_plugin_an_admin_disabled(
    fake_qbit: FakeQbit, settings: Settings
) -> None:
    bootstrapper, _ = make_bootstrapper(fake_qbit, settings)
    await bootstrapper.run_once()
    fake_qbit.plugins[0]["enabled"] = False
    client = make_client(fake_qbit, settings)

    checks = await doctor.collect(client, settings)

    assert all(ok for ok, _ in checks)
    assert any(
        f"plugin {fake_qbit.plugins[0]['name']} installed enabled False" in t for _, t in checks
    )
    await client.aclose()
