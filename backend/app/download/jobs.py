"""Download jobs and the registry that keeps their tasks alive (DOWN-01, D-11, D-12).

A job outlives the HTTP request that created it: the request waits a few seconds for the
outcome and then answers "preparing" while the task keeps going. The registry therefore holds a
strong reference to every `asyncio.Task` (the event loop only keeps weak ones, and FastAPI's
request-scoped background helper dies with the request), logs a task that crashes, and maps a
result to its active job so a double tap cannot add a torrent twice.
"""

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from enum import Enum

from app.content_type import ContentType

logger = logging.getLogger(__name__)

# Finished jobs are kept for polling; the oldest go first once there are more than this.
MAX_JOBS = 500


class JobState(str, Enum):
    PREPARING = "preparing"  # waiting for metadata or for the allowlist to finish
    STARTED = "started"  # filtered and running
    REJECTED = "rejected"  # no usable video inside: deleted with its files (D-13)
    # only videos in a format outside the allowlist (e.g. .webm): deleted with its files (D-13
    # amended 2026-10-22). Not an active state.
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"  # no metadata before METADATA_TIMEOUT: deleted (D-12)
    DUPLICATE = "duplicate"  # qBittorrent already has it
    FAILED = "failed"  # anything else: nothing was started


ACTIVE_STATES = frozenset({JobState.PREPARING, JobState.STARTED})
# The outcomes the downloads list shows for FAILED_VISIBLE_HOURS after the job ended (D-29).
FAILED_STATES = frozenset(
    {JobState.REJECTED, JobState.UNSUPPORTED, JobState.UNAVAILABLE, JobState.FAILED}
)


@dataclass(slots=True)
class Job:
    job_id: str
    # None for a job resumed after a restart: the search result is long gone.
    result_id: str | None
    type: ContentType | None
    state: JobState
    torrent_hash: str | None
    created_at: float
    # The search result's name, so a magnet still named by its hash reads as the film (D-27).
    name: str | None = None
    # Epoch seconds, stamped once when the job task ends (normally, by error or by cancellation).
    finished_at: float | None = None


class JobRegistry:
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        # Epoch seconds, like qBittorrent's timestamps and the downloads list's `now`.
        self._clock = clock
        self._jobs: dict[str, Job] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}  # strong references

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def all(self) -> list[Job]:
        """A snapshot of the registered jobs, in insertion order."""
        return list(self._jobs.values())

    def task(self, job_id: str) -> asyncio.Task[None] | None:
        return self._tasks.get(job_id)

    def active_for_result(self, result_id: str) -> Job | None:
        """The newest preparing or started job of a result, if any."""
        for job in reversed(self._jobs.values()):
            if job.result_id == result_id and job.state in ACTIVE_STATES:
                return job
        return None

    def spawn(self, job: Job, coro: Coroutine[object, object, None]) -> asyncio.Task[None]:
        """Register a job and start its task. Synchronous, so it cannot interleave with a check."""
        self._prune()
        self._jobs[job.job_id] = job
        task = asyncio.create_task(self._guard(job, coro), name=f"download-{job.job_id}")
        self._tasks[job.job_id] = task
        return task

    async def _guard(self, job: Job, coro: Coroutine[object, object, None]) -> None:
        try:
            await self._run(job, coro)
        finally:
            # Every ending is stamped exactly once: a job that sat Preparing for minutes ages
            # from here, not from its creation (D-29, research Pitfall 3).
            job.finished_at = self._clock()

    async def _run(self, job: Job, coro: Coroutine[object, object, None]) -> None:
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - a dead task must never leave a job preparing
            # Class name only: an exception text could carry a URL or a hash.
            logger.error("download job %s crashed: %s", job.job_id, type(exc).__name__)
            if job.state is JobState.PREPARING:
                job.state = JobState.FAILED
            return
        if job.state is JobState.PREPARING:  # a pipeline path forgot to settle the job
            logger.error("download job %s ended without an outcome", job.job_id)
            job.state = JobState.FAILED

    def _prune(self) -> None:
        """Make room for one more job by dropping the oldest finished ones."""
        excess = len(self._jobs) - MAX_JOBS + 1
        for job_id in list(self._jobs):
            if excess <= 0:
                return
            task = self._tasks.get(job_id)
            if task is not None and task.done():
                del self._jobs[job_id]
                del self._tasks[job_id]
                excess -= 1

    async def shutdown(self) -> None:
        """Cancel running jobs (application shutdown); reconcile finishes them next start."""
        tasks = [task for task in self._tasks.values() if not task.done()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
