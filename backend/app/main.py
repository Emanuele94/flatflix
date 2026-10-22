"""FastAPI application factory (run with `uvicorn app.main:create_app --factory`).

The API only: no docs, no OpenAPI schema and no static files (D-03). Caddy
serves the frontend and proxies /api/* here.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app.auth import SESSION_COOKIE, LoginThrottle
from app.config import Settings, get_settings
from app.qbit.client import QbitClient
from app.routers import auth, health

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
    # Built here, not in the lifespan: the limiter must exist for every request path.
    app.state.login_throttle = LoginThrottle(
        max_attempts=settings.login_max_attempts,
        window_seconds=settings.login_window_seconds,
    )
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key.get_secret_value(),
        session_cookie=SESSION_COOKIE,
        max_age=settings.session_max_age_seconds,
        same_site="lax",
        # Plain-HTTP LAN (T-01-17): the cookie is HttpOnly, SameSite=Lax and signed.
        https_only=False,
        path="/",
    )
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(auth.protected)
    return app
