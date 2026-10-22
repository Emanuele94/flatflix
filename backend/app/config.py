"""Application settings read from environment variables (SEC-04).

The process environment is the only source: compose injects `.env` through
`env_file`, so this module never reads an env file itself. Error messages name
the variable and never echo its value.
"""

import logging
from functools import lru_cache

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PLACEHOLDER_PREFIX = "change-me"


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
