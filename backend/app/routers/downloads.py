"""Downloads list route (DOWN-04, DOWN-06, PUI-02).

Every item comes from `listing.build_items`: no hash, save path, category name or qBittorrent
text reaches the browser, and the JSON key is `type`, never the category. A qBittorrent problem
answers 502 with a code and never 401, because the frontend treats any 401 as an expired portal
session and would log the person out for a fault that is not theirs (research Pitfall 4). The
route is read-only and deliberately not behind `require_ready`, so the list keeps working while
bootstrap retries.

DELETE names a download only by its opaque id. The server re-reads the torrent, re-checks that
its category is Film or SerieTV and decides on its own whether the files go (D-32, D-35); the
request carries no body, flag, hash, path or category.
"""

import logging
import time

from fastapi import HTTPException, Path, Request, Response

from app import audit
from app.auth import protected_router
from app.download.listing import build_items
from app.qbit.client import QbitAuthError, QbitBanned, QbitError
from app.routers.download import RESULT_ID_PATTERN

logger = logging.getLogger(__name__)

router = protected_router()


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def qbit_failure(exc: QbitError, where: str, ip: str) -> HTTPException:
    # Class name and status only: the qBittorrent answer body never reaches a log or the browser.
    logger.warning("downloads: qBittorrent failed: %s (HTTP %s)", type(exc).__name__, exc.status)
    audit.error(where, type(exc).__name__, exc.status, ip)
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
        raise qbit_failure(exc, "downloads", client_ip(request)) from None
    return {
        "items": build_items(
            rows,
            settings,
            now=time.time(),
            secret=settings.secret_key.get_secret_value(),
            jobs=app.state.jobs.all(),
        )
    }


@router.delete("/downloads/{download_id}", status_code=204)
async def cancel_download(
    request: Request, download_id: str = Path(pattern=RESULT_ID_PATTERN)
) -> Response:
    """Cancel an in-progress download or remove a finished one from the list (DOWN-05)."""
    ip = client_ip(request)
    try:
        outcome = await request.app.state.pipeline.cancel(download_id)
    except QbitError as exc:
        raise qbit_failure(exc, "cancel", ip) from None
    if outcome is None:
        audit.removed(ip, "cancel", None, "not_found")
        raise HTTPException(status_code=404, detail="download_not_found")
    audit.removed(ip, outcome.action, outcome.name, "done")
    return Response(status_code=204)
