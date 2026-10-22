"""Downloads list route (DOWN-04, DOWN-06, PUI-02).

Every item comes from `listing.build_items`: no hash, save path, category name or qBittorrent
text reaches the browser, and the JSON key is `type`, never the category. A qBittorrent problem
answers 502 with a code and never 401, because the frontend treats any 401 as an expired portal
session and would log the person out for a fault that is not theirs (research Pitfall 4). The
route is read-only and deliberately not behind `require_ready`, so the list keeps working while
bootstrap retries.
"""

import logging
import time

from fastapi import HTTPException, Request

from app.auth import protected_router
from app.download.listing import build_items
from app.qbit.client import QbitAuthError, QbitBanned, QbitError

logger = logging.getLogger(__name__)

router = protected_router()


def qbit_failure(exc: QbitError) -> HTTPException:
    # Class name and status only: the qBittorrent answer body never reaches a log or the browser.
    logger.warning("downloads: qBittorrent failed: %s (HTTP %s)", type(exc).__name__, exc.status)
    if isinstance(exc, QbitAuthError | QbitBanned):
        return HTTPException(status_code=502, detail="qbit_refused")
    return HTTPException(status_code=502, detail="qbit_unreachable")


@router.get("/downloads")
async def list_downloads(request: Request) -> dict[str, list[dict]]:
    app = request.app
    settings = app.state.settings
    try:
        # One unfiltered call: qBittorrent's category filter also matches sub-categories.
        rows = await app.state.qbit.torrents_info()
    except QbitError as exc:
        raise qbit_failure(exc) from None
    return {
        "items": build_items(
            rows, settings, now=time.time(), secret=settings.secret_key.get_secret_value()
        )
    }
