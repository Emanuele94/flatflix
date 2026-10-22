"""Application settings read from environment variables (SEC-04).

The process environment is the only source: compose injects `.env` through
`env_file`, so this module never reads an env file itself. Error messages name
the variable and never echo its value.
"""

import logging
from functools import lru_cache

from argon2 import extract_parameters
from argon2.exceptions import InvalidHashError
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PLACEHOLDER_PREFIX = "change-me"
SECRET_KEY_MIN_LENGTH = 32
ARGON2ID_PREFIX = "$argon2id$"
BAD_HASH_MESSAGE = (
    "APP_PASS_HASH is not an argon2id hash: generate it with "
    "python -m app.tools.hash_password and keep the single quotes in .env"
)


def ensure_real_secret(name: str, value: str) -> str:
    """Reject an empty value or an unedited `.env.example` placeholder."""
    if not value or not value.strip():
        raise ValueError(f"{name} is empty")
    if value.startswith(PLACEHOLDER_PREFIX):
        raise ValueError(f"{name} still holds the .env.example placeholder")
    return value


class Settings(BaseSettings):
    # hide_input_in_errors keeps rejected values out of ValidationError text.
    model_config = SettingsConfigDict(
        case_sensitive=False, extra="ignore", hide_input_in_errors=True
    )

    qbittorrent_url: str
    qbittorrent_user: str
    qbittorrent_pass: SecretStr
    log_level: str = "INFO"

    # Portal access (AUTH-01, D-15..D-18): one shared account from the environment.
    app_user: str
    app_pass_hash: SecretStr
    secret_key: SecretStr
    login_max_attempts: int = Field(default=5, ge=1)
    login_window_minutes: int = Field(default=15, ge=1)
    session_max_age_days: int = Field(default=30, ge=1)

    @property
    def session_max_age_seconds(self) -> int:
        return self.session_max_age_days * 24 * 3600

    @property
    def login_window_seconds(self) -> float:
        return self.login_window_minutes * 60.0

    @field_validator("app_user")
    @classmethod
    def _check_app_user(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("APP_USER is empty")
        return value

    @field_validator("app_pass_hash")
    @classmethod
    def _check_app_pass_hash(cls, value: SecretStr) -> SecretStr:
        raw = ensure_real_secret("APP_PASS_HASH", value.get_secret_value())
        if not raw.startswith(ARGON2ID_PREFIX):
            raise ValueError(BAD_HASH_MESSAGE)
        try:
            extract_parameters(raw)
        except InvalidHashError:
            raise ValueError(BAD_HASH_MESSAGE) from None
        return value

    @field_validator("secret_key")
    @classmethod
    def _check_secret_key(cls, value: SecretStr) -> SecretStr:
        raw = ensure_real_secret("SECRET_KEY", value.get_secret_value())
        if len(raw) < SECRET_KEY_MIN_LENGTH:
            raise ValueError(f"SECRET_KEY is shorter than {SECRET_KEY_MIN_LENGTH} characters")
        return value

    @field_validator("qbittorrent_url")
    @classmethod
    def _check_url(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("QBITTORRENT_URL must start with http:// or https://")
        return value.rstrip("/")

    @field_validator("qbittorrent_user")
    @classmethod
    def _check_user(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("QBITTORRENT_USER is empty")
        return value

    @field_validator("qbittorrent_pass")
    @classmethod
    def _check_pass(cls, value: SecretStr) -> SecretStr:
        ensure_real_secret("QBITTORRENT_PASS", value.get_secret_value())
        return value

    @field_validator("log_level")
    @classmethod
    def _check_log_level(cls, value: str) -> str:
        level = value.strip().upper()
        if level not in logging.getLevelNamesMapping():
            raise ValueError("LOG_LEVEL is not a known logging level")
        return level


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # fields come from the environment
