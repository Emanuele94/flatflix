"""Contract tests for the Jellyfin provisioning scripts (JFIN-01, JFIN-02, JFIN-03).

`scripts/jellyfin_setup.py` and `scripts/make_compat_clips.py` are standalone standard-library
scripts, so they are loaded by path. Only their pure parts are exercised here: no request is made
and no file under the real env file or the jellyfin folder is touched.
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from urllib.parse import urlparse

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def load(name: str, filename: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses looks its own module up here
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def js() -> ModuleType:
    return load("flatflix_jellyfin_setup", "jellyfin_setup.py")


@pytest.fixture(scope="module")
def mc() -> ModuleType:
    return load("flatflix_make_compat_clips", "make_compat_clips.py")


def write_env(tmp_path: Path, **values: str) -> Path:
    path = tmp_path / "env"
    path.write_text("".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8")
    return path


# --- auth header ---------------------------------------------------------------------


def test_auth_header_without_a_token_names_the_client_and_carries_no_token(js: ModuleType) -> None:
    header = js.auth_header(None)

    assert header.startswith("MediaBrowser ")
    for part in ("Client=", "Device=", "DeviceId=", "Version="):
        assert part in header
    assert "Token" not in header


def test_auth_header_with_a_token_ends_with_the_token(js: ModuleType) -> None:
    assert js.auth_header("t0k").endswith('Token="t0k"')


def test_the_default_base_goes_through_caddy_never_to_the_jellyfin_port(js: ModuleType) -> None:
    assert js.DEFAULT_BASE == "http://127.0.0.1/jellyfin"
    assert "8096" not in (SCRIPTS / "jellyfin_setup.py").read_text(encoding="utf-8")


# --- public users --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("names", "expected"),
    [
        (["household"], True),
        ([], False),
        (["admin", "household"], False),
        (["Household"], False),
        (["household", "household"], False),
    ],
)
def test_public_users_ok_accepts_only_the_household_tile(
    js: ModuleType, names: list[str], expected: bool
) -> None:
    assert js.public_users_ok(names) is expected


# --- passwords -----------------------------------------------------------------------


GOOD = {"JELLYFIN_ADMIN_PASSWORD": "a" * 40, "JELLYFIN_HOUSEHOLD_PASSWORD": "kt7m3xq9ab"}


def test_passwords_reads_both_values_by_key(
    js: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(js, "ENV_FILE", write_env(tmp_path, **GOOD))

    assert js.passwords() == (GOOD["JELLYFIN_ADMIN_PASSWORD"], GOOD["JELLYFIN_HOUSEHOLD_PASSWORD"])


@pytest.mark.parametrize("key", sorted(GOOD))
@pytest.mark.parametrize("bad", ["", "change-me", "change-me-please"])
def test_passwords_refuses_an_empty_or_placeholder_value_and_names_only_the_key(
    js: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, key: str, bad: str
) -> None:
    monkeypatch.setattr(js, "ENV_FILE", write_env(tmp_path, **{**GOOD, key: bad}))

    with pytest.raises(js.Fail) as caught:
        js.passwords()

    assert caught.value.step == "config"
    assert key in caught.value.reason
    assert not bad or bad not in caught.value.reason


@pytest.mark.parametrize("key", sorted(GOOD))
def test_passwords_refuses_a_missing_key(
    js: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, key: str
) -> None:
    values = {k: v for k, v in GOOD.items() if k != key}
    monkeypatch.setattr(js, "ENV_FILE", write_env(tmp_path, **values))

    with pytest.raises(js.Fail) as caught:
        js.passwords()

    assert caught.value.step == "config"
    assert key in caught.value.reason


def test_passwords_refuses_equal_admin_and_household_passwords_without_printing_them(
    js: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    same = "samesamesame"
    monkeypatch.setattr(
        js,
        "ENV_FILE",
        write_env(
            tmp_path, JELLYFIN_ADMIN_PASSWORD=same, JELLYFIN_HOUSEHOLD_PASSWORD=same
        ),
    )

    with pytest.raises(js.Fail) as caught:
        js.passwords()

    assert caught.value.step == "config"
    assert same not in caught.value.reason


def test_the_script_reads_every_jellyfin_key_the_template_promises(js: ModuleType) -> None:
    source = (SCRIPTS / "jellyfin_setup.py").read_text(encoding="utf-8")

    for key in (
        "JELLYFIN_ADMIN_PASSWORD",
        "JELLYFIN_HOUSEHOLD_PASSWORD",
        "JELLYFIN_MAX_BITRATE_MBPS",
    ):
        assert key in source


# --- library options -----------------------------------------------------------------


def test_library_options_for_an_online_library(js: ModuleType) -> None:
    options = js.library_options(True)

    assert options["EnableInternetProviders"] is True
    assert options["SaveLocalMetadata"] is False
    assert options["EnableRealtimeMonitor"] is True
    assert options["PreferredMetadataLanguage"] == "en"
    assert options["MetadataCountryCode"] == "US"
    assert options["EnableTrickplayImageExtraction"] is False
    assert options["EnableChapterImageExtraction"] is False


def test_library_options_offline_differs_only_in_the_internet_providers(js: ModuleType) -> None:
    online, offline = js.library_options(True), js.library_options(False)

    assert offline["EnableInternetProviders"] is False
    assert {k: v for k, v in online.items() if k != "EnableInternetProviders"} == {
        k: v for k, v in offline.items() if k != "EnableInternetProviders"
    }


# --- scan wait -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("samples", "start", "expected"),
    [
        ([("Idle", 0, 0)], 0, False),
        ([("Running", 3, 3), ("Idle", 5, 1)], 0, False),
        ([("Running", 3, 3), ("Idle", 5, 0), ("Idle", 5, 0)], 0, True),
        ([("Idle", 2, 0), ("Idle", 2, 0)], 0, True),
        ([("Idle", 2, 0), ("Idle", 2, 0)], 2, False),
        ([("Running", 5, 0), ("Running", 5, 0)], 0, False),
        ([("Idle", 2, 0), ("Idle", 2, 1)], 0, False),
        ([], 0, False),
    ],
)
def test_scan_settled_needs_a_seen_scan_idle_and_two_equal_samples(
    js: ModuleType, samples: list[tuple[str, int, int]], start: int, expected: bool
) -> None:
    assert js.scan_settled(samples, start) is expected


def test_scan_settled_accepts_a_scan_seen_to_finish_between_two_polls(js: ModuleType) -> None:
    quiet = [("Idle", 4, 0), ("Idle", 4, 0)]

    assert js.scan_settled(quiet, 4) is False
    assert js.scan_settled(quiet, 4, finished_seen=True) is True


# --- clip maker ----------------------------------------------------------------------


def test_movie_path_uses_the_title_year_folder_and_file_name(mc: ModuleType) -> None:
    assert mc.movie_path("bbb") == (
        mc.SCRATCH / "Movies" / "Big Buck Bunny (2008)" / "Big Buck Bunny (2008).mp4"
    )


def test_every_source_comes_from_the_blender_download_host(mc: ModuleType) -> None:
    assert mc.SOURCES
    for source in mc.SOURCES.values():
        parsed = urlparse(source.url)
        assert parsed.scheme == "https"
        assert parsed.hostname == "download.blender.org"
