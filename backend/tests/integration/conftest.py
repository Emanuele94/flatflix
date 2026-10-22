"""Opt-in guard against a real, pinned qBittorrent (QBIT_TEST_URL).

Nothing here runs by default: `pyproject.toml` deselects the `integration` marker, and the
tests are skipped unless QBIT_TEST_URL points at a qBittorrent whose WebUI is reachable from
the host (the admin override publishes it on loopback port 8088). Credentials come from
QBIT_TEST_USER / QBIT_TEST_PASS, or are read inside this process from the local env file keys
QBITTORRENT_USER / QBITTORRENT_PASS. They are never printed.
"""

import os
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from argon2 import PasswordHasher
from fastapi import FastAPI
from pydantic import SecretStr

from app.config import Settings
from app.main import create_app
from app.qbit.client import QbitClient
from tests.conftest import (
    PORTAL_PASSWORD,
    PORTAL_SECRET_KEY,
    PORTAL_USER,
    log_in,
    wait_for_bootstrap,
)

HERE = Path(__file__).parent
REPO_ROOT = HERE.parents[2]
ENV_FILE = REPO_ROOT / ".env"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip this directory's tests unless QBIT_TEST_URL is set (the hook sees every item)."""
    if os.environ.get("QBIT_TEST_URL"):
        return
    skip = pytest.mark.skip(reason="QBIT_TEST_URL is not set")
    for item in items:
        if HERE in Path(str(item.fspath)).parents:
            item.add_marker(skip)


def _env_file_value(key: str) -> str | None:
    if not ENV_FILE.is_file():
        return None
    for line in ENV_FILE.read_text().splitlines():
        name, sep, value = line.partition("=")
        if sep and name.strip() == key:
            return value.strip().strip("'\"")
    return None


def credentials() -> tuple[str, str]:
    user = os.environ.get("QBIT_TEST_USER") or _env_file_value("QBITTORRENT_USER")
    password = os.environ.get("QBIT_TEST_PASS") or _env_file_value("QBITTORRENT_PASS")
    if not user or not password:
        pytest.fail("set QBIT_TEST_USER and QBIT_TEST_PASS, or provide the local env file")
    return user, password


@pytest.fixture(scope="session")
def qbit_url() -> str:
    return os.environ["QBIT_TEST_URL"]


@pytest.fixture
def real_settings(qbit_url: str) -> Settings:
    user, password = credentials()
    return Settings(
        qbittorrent_url=qbit_url,
        qbittorrent_user=user,
        qbittorrent_pass=SecretStr(password),
        app_user=PORTAL_USER,
        app_pass_hash=SecretStr(PasswordHasher().hash(PORTAL_PASSWORD)),
        secret_key=SecretStr(PORTAL_SECRET_KEY),
    )


@pytest.fixture
async def real_qbit(real_settings: Settings) -> AsyncIterator[QbitClient]:
    client = QbitClient.from_settings(real_settings)
    yield client
    await client.aclose()


@pytest.fixture
async def real_app(real_settings: Settings) -> AsyncIterator[FastAPI]:
    """The portal wired to the real qBittorrent; its bootstrap re-applies the same config."""
    app = create_app(real_settings)
    async with app.router.lifespan_context(app):
        await wait_for_bootstrap(app, seconds=60)
        assert app.state.readiness.state == "ready"
        yield app


@pytest.fixture
async def real_api(real_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=real_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://portal.test") as client:
        await log_in(client)
        yield client
