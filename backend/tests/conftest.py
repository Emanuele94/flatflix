"""Shared fixtures. Settings are built from explicit kwargs, never from the environment."""

from collections.abc import AsyncIterator

import httpx
import pytest
from argon2 import PasswordHasher
from fastapi import FastAPI
from pydantic import SecretStr

from app.config import Settings
from app.main import create_app
from app.qbit.client import QbitClient
from tests.fakeqbit import FakeQbit

QBIT_URL = "http://qbittorrent.test:8088"
QBIT_USER = "portal-test"
QBIT_PASS = "test-qbit-secret-1234"
PORTAL_USER = "famiglia-test"
PORTAL_PASSWORD = "correct horse battery"
PORTAL_SECRET_KEY = "test-secret-key-0123456789abcdefghij"
# Hashed once per run, at runtime: no password hash is ever written to a tracked file.
PORTAL_PASS_HASH = PasswordHasher().hash(PORTAL_PASSWORD)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        qbittorrent_url=QBIT_URL,
        qbittorrent_user=QBIT_USER,
        qbittorrent_pass=SecretStr(QBIT_PASS),
        app_user=PORTAL_USER,
        app_pass_hash=SecretStr(PORTAL_PASS_HASH),
        secret_key=SecretStr(PORTAL_SECRET_KEY),
    )


@pytest.fixture
def fake_qbit() -> FakeQbit:
    return FakeQbit(QBIT_USER, QBIT_PASS)


@pytest.fixture
def app(settings: Settings, fake_qbit: FakeQbit) -> FastAPI:
    client = QbitClient(
        settings.qbittorrent_url,
        settings.qbittorrent_user,
        settings.qbittorrent_pass,
        transport=fake_qbit.transport,
    )
    return create_app(settings, client)


@pytest.fixture
async def api(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://portal.test") as client:
            yield client


async def log_in(client: httpx.AsyncClient) -> httpx.Response:
    """Log the shared test account in; the client keeps the session cookie."""
    response = await client.post(
        "/api/login", json={"username": PORTAL_USER, "password": PORTAL_PASSWORD}
    )
    assert response.status_code == 204
    return response


@pytest.fixture
async def user_api(api: httpx.AsyncClient) -> httpx.AsyncClient:
    """The `api` client already logged in, for tests of protected routes."""
    await log_in(api)
    return api
