"""Idempotent qBittorrent configuration at backend start (DOWN-03, FILT-01).

`Bootstrapper.run_once` makes qBittorrent's preferences and categories match the server
config. Routes that start or search downloads depend on `require_ready`, which answers 503
until the whole sequence has succeeded, so no torrent is added before the exclusion list
and the category paths exist.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Literal

from fastapi import HTTPException, Request

from app.config import Settings
from app.download.allowlist import EXCLUDED_FILE_PATTERNS
from app.qbit.client import QbitAuthError, QbitBanned, QbitClient, QbitError

logger = logging.getLogger(__name__)

BACKOFF_CAP_SECONDS = 30


class QbitIncompatible(QbitError):
    """The qBittorrent WebAPI is older than the tested minimum (D-22)."""


class Readiness:
    """Whether qBittorrent is configured; read by health and by `require_ready`."""

    def __init__(self) -> None:
        self.state: Literal["starting", "ready", "failed"] = "starting"
        self.reason: str | None = None

    def mark_ready(self) -> None:
        self.state = "ready"
        self.reason = None

    def mark_failed(self, reason: str) -> None:
        self.state = "failed"
        self.reason = reason


def require_ready(request: Request) -> None:
    """FastAPI dependency: 503 until qBittorrent has been configured."""
    if request.app.state.readiness.state != "ready":
        raise HTTPException(status_code=503, detail="not_ready")


def parse_version(text: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in text.strip().split("."))
    except ValueError:
        raise QbitIncompatible("qBittorrent reported an unreadable WebAPI version") from None


def build_preferences(settings: Settings, current_excluded: str) -> dict:
    """The preferences the backend owns.

    The exclusion list is the FILT-01 patterns in their fixed order, then the patterns an admin
    added in the WebUI that are not already present (compared case-insensitively).
    """
    seen = {pattern.casefold() for pattern in EXCLUDED_FILE_PATTERNS}
    patterns = list(EXCLUDED_FILE_PATTERNS)
    for line in current_excluded.splitlines():
        pattern = line.strip()
        if pattern and pattern.casefold() not in seen:
            seen.add(pattern.casefold())
            patterns.append(pattern)
    return {
        "excluded_file_names_enabled": True,
        "excluded_file_names": "\n".join(patterns),
        "auto_tmm_enabled": True,
        "category_changed_tmm_enabled": True,
        "temp_path_enabled": True,
        "temp_path": settings.incomplete_path,
    }


def same_save_path(stored: str, wanted: str) -> bool:
    """Exact comparison, except that one trailing slash is ignored."""

    def strip(path: str) -> str:
        return path[:-1] if path.endswith("/") and len(path) > 1 else path

    return strip(stored) == strip(wanted)


class Bootstrapper:
    def __init__(
        self,
        qbit: QbitClient,
        settings: Settings,
        readiness: Readiness,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._qbit = qbit
        self._settings = settings
        self._readiness = readiness
        self._sleep = sleep

    async def run_once(self) -> None:
        await self._check_version()
        current = await self._qbit.get_preferences()
        excluded = str(current.get("excluded_file_names") or "")
        await self._qbit.set_preferences(build_preferences(self._settings, excluded))
        await self._sync_categories()
        self._readiness.mark_ready()

    async def _check_version(self) -> None:
        reported = await self._qbit.webapi_version()
        if parse_version(reported) < parse_version(self._settings.min_webapi_version):
            raise QbitIncompatible("qBittorrent WebAPI is older than the tested minimum")

    async def _sync_categories(self) -> None:
        existing = await self._qbit.categories()
        for name, save_path in self._settings.category_paths.items():
            # Names are compared exactly: an existing "film" does not satisfy "Film".
            stored = existing.get(name)
            if stored is None:
                if await self._qbit.create_category(name, save_path):
                    continue
                # 409: it appeared since the list was read. Compare its path, never assume.
                stored = (await self._qbit.categories()).get(name)
                if stored is None:
                    raise QbitError("qBittorrent refused to create a category")
            if not same_save_path(str(stored.get("savePath", "")), save_path):
                await self._qbit.edit_category(name, save_path)

    async def run_forever(self) -> None:
        """Retry until configured; stop for good on a fault only an admin can fix.

        Waits min(2 ** attempt, 30) seconds between attempts: 1, 2, 4, ... capped at 30.
        """
        attempt = 0
        while True:
            try:
                await self.run_once()
                return
            except (QbitAuthError, QbitBanned, QbitIncompatible) as exc:
                reason = type(exc).__name__
                self._readiness.mark_failed(reason)
                logger.error(
                    "qBittorrent bootstrap stopped: %s; fix .env or the image tag and restart",
                    reason,
                )
                return
            except QbitError as exc:
                # Unreachable or an unexpected answer: log the class only, never a body or URL.
                delay = min(2**attempt, BACKOFF_CAP_SECONDS)
                attempt += 1
                logger.warning(
                    "qBittorrent not ready (%s); retrying in %s s", type(exc).__name__, delay
                )
                await self._sleep(delay)
            except Exception as exc:  # noqa: BLE001 - a dead task would leave health unexplained
                reason = type(exc).__name__
                self._readiness.mark_failed(reason)
                logger.error("qBittorrent bootstrap crashed: %s", reason)
                return
