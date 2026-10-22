"""Shared fixtures. Settings are built from explicit kwargs, never from the environment."""

from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from app.config import Settings
from app.main import create_app
from app.qbit.client import QbitClient
from tests.fakeqbit import FakeQbit

QBIT_URL = "http://qbittorrent.test:8088"
QBIT_USER = "portal-test"
QBIT_PASS = "test-qbit-secret-1234"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        qbittorrent_url=QBIT_URL,
        qbittorrent_user=QBIT_USER,
        qbittorrent_pass=SecretStr(QBIT_PASS),
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
