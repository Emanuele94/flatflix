"""Strict secret validation (SEC-04, D-17, Pitfall 6) and the hash helper CLI."""

import importlib.util
import io
import re
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from pydantic import SecretStr, ValidationError

from app.config import Settings
from app.tools import hash_password
from tests.conftest import (
    PORTAL_PASS_HASH,
    PORTAL_SECRET_KEY,
    PORTAL_USER,
    QBIT_PASS,
    QBIT_URL,
    QBIT_USER,
)


def build(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "qbittorrent_url": QBIT_URL,
        "qbittorrent_user": QBIT_USER,
        "qbittorrent_pass": SecretStr(QBIT_PASS),
        "app_user": PORTAL_USER,
        "app_pass_hash": SecretStr(PORTAL_PASS_HASH),
        "secret_key": SecretStr(PORTAL_SECRET_KEY),
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def error_text(**overrides: object) -> str:
    with pytest.raises(ValidationError) as caught:
        build(**overrides)
    return str(caught.value)


def test_secret_key_of_31_characters_is_rejected_and_32_accepted() -> None:
    assert "SECRET_KEY" in error_text(secret_key=SecretStr("k" * 31))
    assert build(secret_key=SecretStr("k" * 32)).secret_key.get_secret_value() == "k" * 32


@pytest.mark.parametrize(
    ("field", "name"),
    [
        ("secret_key", "SECRET_KEY"),
        ("app_pass_hash", "APP_PASS_HASH"),
        ("qbittorrent_pass", "QBITTORRENT_PASS"),
    ],
)
def test_empty_secret_is_rejected_and_named(field: str, name: str) -> None:
    assert name in error_text(**{field: SecretStr("")})


@pytest.mark.parametrize(
    ("field", "name"),
    [
        ("secret_key", "SECRET_KEY"),
        ("app_pass_hash", "APP_PASS_HASH"),
        ("qbittorrent_pass", "QBITTORRENT_PASS"),
    ],
)
def test_placeholder_secret_is_rejected_and_named(field: str, name: str) -> None:
    text = error_text(**{field: SecretStr("change-me-" + "x" * 40)})

    assert name in text
    assert "placeholder" in text


def test_empty_environment_variable_counts_as_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    env = {
        "QBITTORRENT_URL": QBIT_URL,
        "QBITTORRENT_USER": QBIT_USER,
        "QBITTORRENT_PASS": QBIT_PASS,
        "APP_USER": PORTAL_USER,
        "APP_PASS_HASH": PORTAL_PASS_HASH,
        "SECRET_KEY": "",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    with pytest.raises(ValidationError) as caught:
        Settings()  # type: ignore[call-arg]

    assert "SECRET_KEY" in str(caught.value)


def test_missing_environment_variable_stops_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("SECRET_KEY", "APP_PASS_HASH", "APP_USER"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("QBITTORRENT_URL", QBIT_URL)
    monkeypatch.setenv("QBITTORRENT_USER", QBIT_USER)
    monkeypatch.setenv("QBITTORRENT_PASS", QBIT_PASS)

    with pytest.raises(ValidationError) as caught:
        Settings()  # type: ignore[call-arg]

    text = str(caught.value).lower()
    assert "secret_key" in text
    assert "app_pass_hash" in text


@pytest.mark.parametrize(
    "bad_hash",
    [
        "$2b$12$" + "a" * 53,  # bcrypt
        PORTAL_PASS_HASH.replace("$", ""),  # what Compose interpolation leaves behind
        PORTAL_PASS_HASH.replace("$argon2id$", "$argon2i$", 1),  # wrong variant
        "$argon2id$not-parameters$abc",
        "just-a-plain-password",
    ],
)
def test_non_argon2id_hash_is_rejected_with_the_single_quote_hint(bad_hash: str) -> None:
    text = error_text(app_pass_hash=SecretStr(bad_hash))

    assert "APP_PASS_HASH" in text
    assert "single quotes" in text


def test_a_real_argon2id_hash_is_accepted() -> None:
    assert build().app_pass_hash.get_secret_value().startswith("$argon2id$")


@pytest.mark.parametrize(
    ("overrides", "rejected"),
    [
        ({"secret_key": SecretStr("tooshort-secret-value")}, "tooshort-secret-value"),
        ({"app_pass_hash": SecretStr("$2b$12$" + "q" * 53)}, "q" * 53),
        ({"qbittorrent_pass": SecretStr("change-me-leaky-value")}, "leaky-value"),
        ({"app_pass_hash": SecretStr("plain-text-password-77")}, "plain-text-password-77"),
    ],
)
def test_error_messages_never_contain_the_rejected_value(
    overrides: dict[str, object], rejected: str
) -> None:
    assert rejected not in error_text(**overrides)


def test_session_and_throttle_settings_have_the_documented_defaults() -> None:
    settings = build()

    assert settings.session_max_age_seconds == 2592000
    assert settings.login_max_attempts == 5
    assert settings.login_window_minutes == 15


# --- hash helper -----------------------------------------------------------------


def test_stdin_mode_prints_one_single_quoted_line_that_verifies(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("correct horse battery\n"))

    code = hash_password.main(["--stdin"])

    out = capsys.readouterr().out
    assert code == 0
    assert out.count("\n") == 1
    match = re.fullmatch(r"APP_PASS_HASH='(\$argon2id\$[^']+)'\n", out)
    assert match, "output must be exactly one single-quoted APP_PASS_HASH line"
    assert PasswordHasher().verify(match.group(1), "correct horse battery")


def test_interactive_mode_with_mismatching_confirmation_exits_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    answers = iter(["correct horse battery", "something different"])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(answers))

    code = hash_password.main([])

    assert code == 2
    assert "APP_PASS_HASH" not in capsys.readouterr().out


def test_interactive_mode_prints_the_hash_when_confirmed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "correct horse battery")

    code = hash_password.main([])

    assert code == 0
    assert capsys.readouterr().out.startswith("APP_PASS_HASH='$argon2id$")


@pytest.mark.parametrize("argv", [["--stdin"], []])
def test_password_shorter_than_8_characters_exits_2(
    argv: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("short7!\n"))
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "short7!")

    code = hash_password.main(argv)

    assert code == 2
    assert "APP_PASS_HASH" not in capsys.readouterr().out


# SEC-04 adjacency: .env.example and Settings describe the same set of keys.
ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"
COMPOSE_LEVEL_KEYS = {
    "WEB_PORT",
    "DATA_ROOT",
    "PUID",
    "PGID",
    "TZ",
    "KVM_GID",
    "VM_VCPUS",
    "VM_MEMORY_MIB",
    "VM_TIMEOUT_SECONDS",
}


def test_env_example_keys_match_the_settings_fields_exactly() -> None:
    documented = {
        line.partition("=")[0].strip()
        for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#") and "=" in line
    }
    expected = {name.upper() for name in Settings.model_fields} | COMPOSE_LEVEL_KEYS

    missing_in_example = sorted(expected - documented)
    orphan_in_example = sorted(documented - expected)
    assert missing_in_example == [], (
        f"Settings fields without a key in .env.example: {missing_in_example}"
    )
    assert orphan_in_example == [], f"keys in .env.example that nothing reads: {orphan_in_example}"


# --- quarantine layout (QUAR-01, D-44, D-45) ---------------------------------------


def test_layout_defaults_put_downloads_in_quarantine_and_checked_files_in_media() -> None:
    settings = build()

    assert settings.quarantine_root == "/data/quarantine"
    assert settings.media_root == "/data/media"
    assert settings.rejected_root == "/data/rejected"
    assert settings.media_paths == {"Film": "/data/media/Film", "SerieTV": "/data/media/SerieTV"}
    assert settings.category_paths == {
        "Film": "/data/quarantine/Film",
        "SerieTV": "/data/quarantine/SerieTV",
    }


@pytest.mark.parametrize(
    ("overrides", "name"),
    [
        ({"save_path_film": "/data/media/Film"}, "SAVE_PATH_FILM"),
        ({"save_path_tv": "/data/quarantine"}, "SAVE_PATH_TV"),
        ({"save_path_tv": "/srv/other/SerieTV"}, "SAVE_PATH_TV"),
        ({"incomplete_path": "/data/quarantine/inc"}, "INCOMPLETE_PATH"),
        ({"incomplete_path": "/data/media/inc"}, "INCOMPLETE_PATH"),
        ({"incomplete_path": "/data/rejected/inc"}, "INCOMPLETE_PATH"),
        ({"incomplete_path": "/elsewhere/incomplete"}, "INCOMPLETE_PATH"),
        ({"data_path": "data"}, "DATA_PATH"),
        ({"data_path": "/data/../etc"}, "DATA_PATH"),
    ],
)
def test_a_layout_that_could_bypass_the_check_stops_startup_and_names_the_variable(
    overrides: dict[str, object], name: str
) -> None:
    text = error_text(**overrides)

    assert name in text
    for value in overrides.values():
        if "/" in str(value):  # a bare word such as "data" is part of the field name itself
            assert str(value) not in text


def test_a_custom_data_path_works_when_everything_sits_inside_it() -> None:
    settings = build(
        data_path="/srv/flat",
        save_path_film="/srv/flat/quarantine/Film",
        save_path_tv="/srv/flat/quarantine/SerieTV",
        incomplete_path="/srv/flat/incomplete",
    )

    assert settings.media_paths["Film"] == "/srv/flat/media/Film"


# --- verifier settings (D-50, D-55, D-62, D-64, D-65, D-78) --------------------------


def test_verifier_settings_have_the_decided_defaults() -> None:
    settings = build()

    assert settings.sandbox_url == "http://sandbox:8090"
    assert settings.probe_timeout_seconds == 90
    assert settings.verify_poll_seconds == 10
    assert settings.min_film_duration_minutes == 40
    assert settings.min_episode_duration_minutes == 10
    assert settings.min_bitrate_kbps == 100
    assert settings.max_bitrate_kbps == 100000
    assert settings.subtitle_text_max_mb == 5
    assert settings.subtitle_bitmap_max_mb == 200
    assert settings.rejected_retention_days == 7
    assert settings.checking_problem_hours == 6
    assert settings.rejected_retention_seconds == 604800
    assert settings.checking_problem_seconds == 21600
    assert settings.subtitle_text_max_bytes == 5 * 1024 * 1024
    assert settings.subtitle_bitmap_max_bytes == 200 * 1024 * 1024


def test_max_bitrate_must_exceed_min_bitrate() -> None:
    text = error_text(min_bitrate_kbps=100, max_bitrate_kbps=100)

    assert "MAX_BITRATE_KBPS" in text


def test_sandbox_url_needs_a_scheme_and_loses_a_trailing_slash() -> None:
    assert "SANDBOX_URL" in error_text(sandbox_url="sandbox:8090")
    assert build(sandbox_url="http://sandbox:8090/").sandbox_url == "http://sandbox:8090"


# --- dev_env.py fills KVM_GID from /dev/kvm (QUAR-05) -------------------------------

DEV_ENV = Path(__file__).resolve().parents[2] / "scripts" / "dev_env.py"


def load_dev_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, template: str):
    spec = importlib.util.spec_from_file_location("dev_env_under_test", DEV_ENV)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / ".env.example").write_text(template, encoding="utf-8")
    monkeypatch.setattr(module, "TEMPLATE", tmp_path / ".env.example")
    monkeypatch.setattr(module, "TARGET", tmp_path / ".env")
    monkeypatch.setattr(module, "PASSWORD_FILE", tmp_path / ".dev-portal-password")
    monkeypatch.setattr(module, "KVM_DEVICE", tmp_path / "kvm", raising=False)
    return module


def test_dev_env_fills_kvm_gid_from_the_device_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = load_dev_env(tmp_path, monkeypatch, "WEB_PORT=80\nKVM_GID=\n")
    (tmp_path / "kvm").write_text("", encoding="utf-8")

    assert module.main([]) == 0

    gid = (tmp_path / "kvm").stat().st_gid
    assert f"KVM_GID={gid}" in (tmp_path / ".env").read_text(encoding="utf-8").splitlines()
    assert str(gid) not in capsys.readouterr().out.replace("KVM_GID", "")


def test_dev_env_leaves_kvm_gid_empty_when_there_is_no_device(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = load_dev_env(tmp_path, monkeypatch, "WEB_PORT=80\nKVM_GID=\n")

    assert module.main([]) == 0

    assert "KVM_GID=" in (tmp_path / ".env").read_text(encoding="utf-8").splitlines()
    assert "KVM_GID left empty: /dev/kvm not found" in capsys.readouterr().out


def test_dev_env_never_rewrites_an_existing_kvm_gid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_dev_env(tmp_path, monkeypatch, "WEB_PORT=80\nKVM_GID=\n")
    (tmp_path / "kvm").write_text("", encoding="utf-8")
    (tmp_path / ".env").write_text("KVM_GID=4242\n", encoding="utf-8")

    assert module.main([]) == 0

    assert (tmp_path / ".env").read_text(encoding="utf-8").count("KVM_GID=") == 1
    assert "KVM_GID=4242" in (tmp_path / ".env").read_text(encoding="utf-8")
