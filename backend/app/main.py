"""FastAPI application factory (run with `uvicorn app.main:create_app --factory`).

The API only: no docs, no OpenAPI schema and no static files (D-03). Caddy
serves the frontend and proxies /api/* here.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import Settings, get_settings
from app.qbit.client import QbitClient
from app.routers import health

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configure_logging(level: str) -> None:
    logging.basicConfig(level=level, format=LOG_FORMAT)
    logging.getLogger().setLevel(level)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def create_app(settings: Settings | None = None, qbit: QbitClient | None = None) -> FastAPI:
    # Resolved eagerly: middleware added by later plans needs settings at build time.
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings
        app.state.qbit = qbit or QbitClient.from_settings(settings)
        try:
            yield
        finally:
            await app.state.qbit.aclose()

    app = FastAPI(
        title="flatflix portal",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.include_router(health.router)
    return app
