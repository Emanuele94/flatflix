"""Search routes (SRCH-01..03, SEC-03, PUI-02).

The body carries only `q` and `type`. Responses are built from an explicit whitelist of fields:
no plugin page link, torrent link, byte size, category or path ever leaves the backend.
"""

import logging
import math
import unicodedata

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.auth import protected_router
from app.content_type import ContentType
from app.qbit.bootstrap import require_ready
from app.qbit.client import QbitError
from app.search.filters import FilteredResult
from app.search.service import SearchSnapshot

logger = logging.getLogger(__name__)

router = protected_router()

QUERY_MIN_CODE_POINTS = 2
QUERY_MAX_CODE_POINTS = 100
# Cheap cap on the raw body field, before the cleaned length is counted.
QUERY_MAX_RAW_CHARS = 1000
STRIPPED_CATEGORIES = frozenset({"Cc", "Cf"})


class SearchRequest(BaseModel):
    # Strict: `type` must be the exact string film or serie, and nothing else is accepted.
    model_config = ConfigDict(extra="forbid", strict=True)

    q: str = Field(max_length=QUERY_MAX_RAW_CHARS)
    type: ContentType

    @field_validator("q")
    @classmethod
    def _clean_query(cls, value: str) -> str:
        """Drop control and format characters, trim, then count Unicode code points."""
        cleaned = "".join(ch for ch in value if unicodedata.category(ch) not in STRIPPED_CATEGORIES)
        cleaned = cleaned.strip()
        if not QUERY_MIN_CODE_POINTS <= len(cleaned) <= QUERY_MAX_CODE_POINTS:
            raise ValueError(
                f"q must have {QUERY_MIN_CODE_POINTS} to {QUERY_MAX_CODE_POINTS} characters"
            )
        return cleaned


def result_row(result: FilteredResult) -> dict[str, object]:
    """The only fields of a result the browser may see (PUI-02, SEC-01)."""
    return {
        "result_id": result.result_id,
        "name": result.name,
        "size_human": result.size_human,
        "seeders": result.seeders,
        "leechers": result.leechers,
        "source": result.source,
        "quality": result.quality,
    }


def snapshot_body(snapshot: SearchSnapshot) -> dict[str, object]:
    return {
        "search_id": snapshot.search_id,
        "done": snapshot.done,
        "timed_out": snapshot.timed_out,
        "results": [result_row(result) for result in snapshot.results],
    }


def unavailable(exc: QbitError) -> HTTPException:
    # Class name and status only: the qBittorrent answer body never reaches a log or the browser.
    logger.warning("search failed: %s (HTTP %s)", type(exc).__name__, exc.status)
    return HTTPException(status_code=503, detail="search_unavailable")


@router.post("/search", dependencies=[Depends(require_ready)])
async def start_search(body: SearchRequest, request: Request) -> dict[str, str]:
    # The slot is taken only here: the session, readiness and body checks run as dependencies and
    # validation before the handler, so anonymous or malformed requests never use one (SEC-05).
    ip = request.client.host if request.client else "unknown"
    retry_in = request.app.state.search_throttle.try_acquire(ip)
    if retry_in is not None:
        raise HTTPException(
            status_code=429,
            detail="too_many_requests",
            headers={"Retry-After": str(max(1, math.ceil(retry_in)))},
        )
    try:
        search_id = await request.app.state.search.start(body.q, body.type)
    except QbitError as exc:
        raise unavailable(exc) from None
    return {"search_id": search_id}


@router.get("/search/{search_id}", dependencies=[Depends(require_ready)])
async def get_search(search_id: str, request: Request) -> dict[str, object]:
    try:
        snapshot = await request.app.state.search.snapshot(search_id)
    except QbitError as exc:
        raise unavailable(exc) from None
    if snapshot is None:
        raise HTTPException(status_code=404, detail="search_not_found")
    return snapshot_body(snapshot)
