"""Application settings read from environment variables (SEC-04).

The process environment is the only source: compose injects `.env` through
`env_file`, so this module never reads an env file itself. Error messages name
the variable and never echo its value.
"""

import logging
import re
from functools import lru_cache

from argon2 import extract_parameters
from argon2.exceptions import InvalidHashError
from pydantic import Field, SecretStr, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.search.filters import DEFAULT_SUSPICIOUS_TERMS

PLACEHOLDER_PREFIX = "change-me"
SECRET_KEY_MIN_LENGTH = 32
ARGON2ID_PREFIX = "$argon2id$"
BAD_HASH_MESSAGE = (
    "APP_PASS_HASH is not an argon2id hash: generate it with "
    "python -m app.tools.hash_password and keep the single quotes in .env"
)


CATEGORY_NAME = re.compile(r"^[A-Za-z0-9]+$")
PLUGIN_NAME = re.compile(r"^[a-z0-9_]+$")
GIT_COMMIT_REF = re.compile(r"^[0-9a-f]{40}$")
VERSION_NUMBER = re.compile(r"^[0-9]+(\.[0-9]+)*$")


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
    # Ceiling across all addresses, so guesses spread over many addresses stay bounded (WR-07).
    login_global_max_attempts: int = Field(default=20, ge=1)
    login_window_minutes: int = Field(default=15, ge=1)
    # Hosts (space separated, resolved through the compose network's DNS) whose
    # `X-Forwarded-For` header is believed. Any other peer is throttled under its own address
    # (WR-02). Empty trusts no header at all.
    trusted_proxy_hosts: str = "web"
    session_max_age_days: int = Field(default=30, ge=1)

    # qBittorrent layout (DOWN-02, DOWN-03). Names and paths come only from here, never from a
    # request. SAVE_PATH_* must match the container mounts in docker-compose.yml.
    category_film: str = "Film"
    category_tv: str = "SerieTV"
    save_path_film: str = "/media/Film"
    save_path_tv: str = "/media/SerieTV"
    incomplete_path: str = "/incomplete"

    # Official search plugins, fetched from one pinned commit of qbittorrent/search-plugins (D-19).
    search_plugins: str = (
        "eztv limetorrents piratebay solidtorrents torlock torrentproject torrentscsv"
    )
    search_plugins_ref: str = "2beb5c67b0edbf2387a031a02d1881fab4bec3c3"

    # Seeding policy (D-21): stop at this ratio or this many minutes, whichever comes first.
    share_ratio_limit: float = Field(default=1.0, gt=0)
    share_time_limit_minutes: int = Field(default=1440, ge=1)

    # Search (SRCH-01..03, D-06..D-08). A result is shown only when it clears these floors.
    min_seeders: int = Field(default=5, ge=0)
    min_film_size_mb: int = Field(default=500, ge=0)
    min_serie_size_mb: int = Field(default=100, ge=0)
    search_timeout: int = Field(default=20, ge=1)
    # Comma-separated; empty means the built-in list in app.search.filters.
    suspicious_terms: str = ""
    max_results: int = Field(default=100, ge=1)
    result_cache_ttl: int = Field(default=900, ge=1)
    max_active_searches: int = Field(default=3, ge=1, le=5)

    # Download pipeline (D-11, D-12). The request waits DOWNLOAD_WAIT_SECONDS for the outcome;
    # the background job keeps going until METADATA_TIMEOUT seconds after the torrent was added.
    metadata_timeout: int = Field(default=300, ge=1)
    download_wait_seconds: float = Field(default=15, ge=0)

    # Downloads list (D-28, D-29). A finished download stays in the list this many days after it
    # completed, a failed attempt this many hours. Neither touches the torrent or its files.
    completed_visible_days: int = Field(default=7, ge=1)
    failed_visible_hours: int = Field(default=24, ge=1)

    # Rate limits (SEC-05, D-38): starts per address per minute. Only a stuck finger or a script
    # should reach them; status polling and the downloads list are never limited.
    search_rate_per_minute: int = Field(default=10, ge=1)
    download_rate_per_minute: int = Field(default=20, ge=1)

    # The tested qBittorrent WebAPI floor (D-22); an older server stops bootstrap.
    min_webapi_version: str = "2.15.1"

    @property
    def category_paths(self) -> dict[str, str]:
        return {self.category_film: self.save_path_film, self.category_tv: self.save_path_tv}

    @property
    def suspicious_term_list(self) -> tuple[str, ...]:
        """SUSPICIOUS_TERMS trimmed and case-folded; empty means the built-in list."""
        terms = tuple(
            term.strip().casefold() for term in self.suspicious_terms.split(",") if term.strip()
        )
        return terms or DEFAULT_SUSPICIOUS_TERMS

    @property
    def trusted_proxy_host_list(self) -> list[str]:
        return self.trusted_proxy_hosts.split()

    @property
    def search_plugin_names(self) -> list[str]:
        return self.search_plugins.split()

    @property
    def session_max_age_seconds(self) -> int:
        return self.session_max_age_days * 24 * 3600

    @property
    def completed_visible_seconds(self) -> int:
        return self.completed_visible_days * 24 * 3600

    @property
    def failed_visible_seconds(self) -> int:
        return self.failed_visible_hours * 3600

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

    @field_validator("category_film", "category_tv")
    @classmethod
    def _check_category(cls, value: str, info: ValidationInfo) -> str:
        if not CATEGORY_NAME.fullmatch(value):
            raise ValueError(f"{info.field_name.upper()} must match ^[A-Za-z0-9]+$")
        return value

    @field_validator("save_path_film", "save_path_tv", "incomplete_path")
    @classmethod
    def _check_path(cls, value: str, info: ValidationInfo) -> str:
        name = info.field_name.upper()
        if not value.startswith("/"):
            raise ValueError(f"{name} must be an absolute path")
        if ".." in value.split("/"):
            raise ValueError(f"{name} must not contain a '..' segment")
        return value.rstrip("/") or "/"

    @field_validator("search_plugins")
    @classmethod
    def _check_plugins(cls, value: str) -> str:
        for name in value.split():
            if not PLUGIN_NAME.fullmatch(name):
                raise ValueError("SEARCH_PLUGINS names must match ^[a-z0-9_]+$")
        return value

    @field_validator("search_plugins_ref")
    @classmethod
    def _check_plugins_ref(cls, value: str) -> str:
        if not GIT_COMMIT_REF.fullmatch(value):
            raise ValueError("SEARCH_PLUGINS_REF must be a 40-character lower-case git commit")
        return value

    @field_validator("min_webapi_version")
    @classmethod
    def _check_min_version(cls, value: str) -> str:
        if not VERSION_NUMBER.fullmatch(value):
            raise ValueError("MIN_WEBAPI_VERSION must look like 2.15.1")
        return value

    @model_validator(mode="after")
    def _check_layout_is_distinct(self) -> "Settings":
        if self.category_film == self.category_tv:
            raise ValueError("CATEGORY_FILM and CATEGORY_TV must differ")
        return self

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
