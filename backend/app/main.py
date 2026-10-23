"""FastAPI application factory (run with `uvicorn app.main:create_app --factory`).

The API only: no docs, no OpenAPI schema and no static files (D-03). Caddy
serves the frontend and proxies /api/* here.
"""

import asyncio
import contextlib
import logging
import sys
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app import audit
from app.auth import SESSION_COOKIE, LoginThrottle
from app.config import Settings, get_settings
from app.download.jobs import JobRegistry
from app.download.pipeline import DownloadPipeline
from app.proxy import TrustedProxyHeaders
from app.qbit.bootstrap import Bootstrapper, Readiness
from app.qbit.client import QbitClient
from app.quarantine.guard import HandoffGuard
from app.quarantine.runner_client import RunnerClient
from app.quarantine.verifier import Verifier
from app.routers import auth, download, downloads, health, search
from app.search.service import SearchService
from app.throttle import THROTTLE_WINDOW_SECONDS, SlidingWindowThrottle

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configure_logging(level: str, secrets: Sequence[str] = ()) -> None:
    # stdout of the container: Docker keeps and rotates it, there is no log file (D-40).
    logging.basicConfig(level=level, format=LOG_FORMAT, stream=sys.stdout)
    logging.getLogger().setLevel(level)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    # The audit trail survives LOG_LEVEL=WARNING: its own level, not the root's (SEC-06).
    logging.getLogger("app.audit").setLevel(logging.INFO)
    audit.install_redaction(secrets)


def create_app(
    settings: Settings | None = None,
    qbit: QbitClient | None = None,
    runner: RunnerClient | None = None,
) -> FastAPI:
    # Resolved eagerly: middleware added by later plans needs settings at build time.
    settings = settings or get_settings()
    configure_logging(
        settings.log_level,
        [
            settings.secret_key.get_secret_value(),
            settings.qbittorrent_pass.get_secret_value(),
            settings.app_pass_hash.get_secret_value(),
        ],
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings
        app.state.qbit = qbit or QbitClient.from_settings(settings)
        app.state.search = SearchService(app.state.qbit, settings)
        app.state.jobs = JobRegistry()
        app.state.pipeline = DownloadPipeline(
            app.state.qbit, settings, app.state.search, app.state.jobs
        )
        # One bootstrap per process; the strong reference keeps the task from being collected.
        app.state.bootstrap_task = asyncio.create_task(
            Bootstrapper(
                app.state.qbit,
                settings,
                app.state.readiness,
                # Looked up at call time so a replaced pipeline (tests) is the one that runs.
                on_ready=lambda: app.state.pipeline.reconcile(),
            ).run_forever()
        )
        app.state.runner = runner or RunnerClient(
            settings.sandbox_url, timeout=settings.probe_timeout_seconds
        )
        app.state.guard = HandoffGuard()
        app.state.verifier = Verifier(
            app.state.qbit,
            app.state.runner,
            settings,
            guard=app.state.guard,
            readiness=app.state.readiness,
        )
        # No phone needs to be open for a finished download to be checked (D-50). It starts
        # ticking only after bootstrap marked readiness ready, and the strong reference keeps the
        # task from being collected.
        app.state.verify_task = asyncio.create_task(app.state.verifier.run_forever())
        try:
            yield
        finally:
            app.state.bootstrap_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await app.state.bootstrap_task
            app.state.verify_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await app.state.verify_task
            # Running downloads stop here; whatever is still fx-pending is resumed next start.
            await app.state.jobs.shutdown()
            # Before the client closes, so running searches do not linger in qBittorrent.
            await app.state.search.close()
            await app.state.runner.aclose()
            await app.state.qbit.aclose()

    app = FastAPI(
        title="flatflix portal",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    # Built here, not in the lifespan: the limiter and readiness must exist for every request.
    app.state.readiness = Readiness()
    app.state.login_throttle = LoginThrottle(
        max_attempts=settings.login_max_attempts,
        window_seconds=settings.login_window_seconds,
        global_max_attempts=settings.login_global_max_attempts,
    )
    # Per address only: these routes already sit behind the login, and the limit targets a stuck
    # finger or a script, not password guessing, so there is no ceiling across addresses (D-38).
    app.state.search_throttle = SlidingWindowThrottle(
        max_attempts=settings.search_rate_per_minute, window_seconds=THROTTLE_WINDOW_SECONDS
    )
    app.state.download_throttle = SlidingWindowThrottle(
        max_attempts=settings.download_rate_per_minute, window_seconds=THROTTLE_WINDOW_SECONDS
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
    # Added last so it runs first: the client address is settled before anything reads it.
    app.add_middleware(TrustedProxyHeaders, hosts=settings.trusted_proxy_host_list)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(auth.protected)
    app.include_router(search.router)
    app.include_router(download.router)
    app.include_router(downloads.router)
    return app
