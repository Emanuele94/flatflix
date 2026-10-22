"""GET /api/health: minimal, leak-free body and no API docs (INFRA-01, SEC-01, D-03)."""

from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
import respx

from app.config import Settings
from app.main import create_app
from tests.conftest import QBIT_PASS, QBIT_URL, QBIT_USER


@pytest.fixture
def qbit_router() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=QBIT_URL, assert_all_called=False) as router:
        yield router


@pytest.fixture
async def portal(
    settings: Settings, qbit_router: respx.MockRouter
) -> AsyncIterator[httpx.AsyncClient]:
    # Real QbitClient transport: respx intercepts the qBittorrent calls.
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://portal.test") as client:
            yield client


async def test_health_ok_once_qbittorrent_is_reachable_and_bootstrapped(
    api: httpx.AsyncClient,
) -> None:
    response = await api.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "qbittorrent": "up"}


async def test_health_degraded_with_http_200_when_qbittorrent_is_unreachable(
    portal: httpx.AsyncClient, qbit_router: respx.MockRouter
) -> None:
    qbit_router.post("/api/v2/auth/login").mock(side_effect=httpx.ConnectError("refused"))

    response = await portal.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "degraded", "qbittorrent": "down"}


async def test_health_body_leaks_no_version_host_or_credentials(
    api: httpx.AsyncClient,
) -> None:
    response = await api.get("/api/health")

    assert set(response.json()) == {"status", "qbittorrent"}
    for secret in ("2.15.1", "qbittorrent.test", QBIT_PASS, QBIT_USER):
        assert secret not in response.text


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
async def test_api_docs_are_not_served(api: httpx.AsyncClient, path: str) -> None:
    assert (await api.get(path)).status_code == 404
