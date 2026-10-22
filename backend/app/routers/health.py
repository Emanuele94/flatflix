"""Liveness of the portal and its qBittorrent link.

GET /api/health is the single intentional unauthenticated route (documented
exception to AUTH-01). The body has exactly two keys and never carries a
version, URL, path or credential.
"""

import asyncio
import logging

from fastapi import APIRouter, Request

from app.qbit.client import QbitError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

HEALTH_TIMEOUT_SECONDS = 3


@router.get("/health")
async def health(request: Request) -> dict[str, str]:
    try:
        await asyncio.wait_for(request.app.state.qbit.webapi_version(), HEALTH_TIMEOUT_SECONDS)
    except (QbitError, TimeoutError) as exc:
        # Class name only: the message of a lower-level error could carry a URL.
        logger.warning("qBittorrent health check failed: %s", type(exc).__name__)
        return {"status": "degraded", "qbittorrent": "down"}
    return {"status": "ok", "qbittorrent": "up"}
