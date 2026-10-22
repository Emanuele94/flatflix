"""Download routes (DOWN-01..03, SEC-03, SEC-01, PUI-02).

The body carries only `result_id` and `type`. The URL, engine and category are resolved on the
server from the search cache and the fixed type map. Every response is exactly
`{status, job_id}`: no hash, save path, category or URL ever reaches the browser.
"""

import asyncio
import math

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.auth import protected_router
from app.content_type import ContentType
from app.download.jobs import Job
from app.download.pipeline import ResultExpired, TypeMismatch
from app.qbit.bootstrap import require_ready

router = protected_router()

RESULT_ID_PATTERN = r"^[0-9a-f]{16}$"


class DownloadRequest(BaseModel):
    # Anything but result_id and type is a 422: the browser cannot name a URL, category or path.
    model_config = ConfigDict(extra="forbid", strict=True)

    result_id: str = Field(pattern=RESULT_ID_PATTERN)
    type: ContentType


def job_body(job: Job) -> dict[str, str]:
    return {"status": job.state.value, "job_id": job.job_id}


@router.post("/download", dependencies=[Depends(require_ready)])
async def start_download(body: DownloadRequest, request: Request) -> dict[str, str]:
    app = request.app
    # The slot is taken only here: the session, readiness and body checks run as dependencies and
    # validation before the handler, so anonymous or malformed requests never use one (SEC-05).
    ip = request.client.host if request.client else "unknown"
    retry_in = app.state.download_throttle.try_acquire(ip)
    if retry_in is not None:
        raise HTTPException(
            status_code=429,
            detail="too_many_requests",
            headers={"Retry-After": str(max(1, math.ceil(retry_in)))},
        )
    try:
        job = app.state.pipeline.submit(body.result_id, body.type)
    except ResultExpired:
        raise HTTPException(status_code=410, detail="search_expired") from None
    except TypeMismatch:
        raise HTTPException(status_code=422, detail="type_mismatch") from None
    task = app.state.jobs.task(job.job_id)
    if task is not None:
        # `wait` never cancels the task: on timeout the job simply keeps running (D-11).
        await asyncio.wait({task}, timeout=app.state.settings.download_wait_seconds)
    return job_body(job)


@router.get("/download/{job_id}")
async def get_download(job_id: str, request: Request) -> dict[str, str]:
    job = request.app.state.jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job_not_found")
    return job_body(job)
