"""Strict secret validation (SEC-04, D-17, Pitfall 6) and the hash helper CLI."""

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
COMPOSE_LEVEL_KEYS = {"WEB_PORT", "MEDIA_ROOT", "INCOMPLETE_DIR", "PUID", "PGID", "TZ"}


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
