"""Search routes (SRCH-01..03, SEC-03, PUI-02).

The body carries only `q` and `type`. Responses are built from an explicit whitelist of fields:
no plugin page link, torrent link, byte size, category or path ever leaves the backend.
"""

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from app.auth import protected_router
from app.content_type import ContentType
from app.qbit.bootstrap import require_ready
from app.search.filters import FilteredResult
from app.search.service import SearchSnapshot

router = protected_router()


class SearchRequest(BaseModel):
    # Strict: `type` must be the exact string film or serie, and nothing else is accepted.
    model_config = ConfigDict(extra="forbid", strict=True)

    q: str
    type: ContentType


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


@router.post("/search", dependencies=[Depends(require_ready)])
async def start_search(body: SearchRequest, request: Request) -> dict[str, str]:
    search_id = await request.app.state.search.start(body.q, body.type)
    return {"search_id": search_id}


@router.get("/search/{search_id}", dependencies=[Depends(require_ready)])
async def get_search(search_id: str, request: Request) -> dict[str, object]:
    snapshot = await request.app.state.search.snapshot(search_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="search_not_found")
    return snapshot_body(snapshot)
