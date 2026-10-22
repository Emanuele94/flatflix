"""Live search against qBittorrent's plugins with a server-side result cache (SRCH-01..03).

The browser only ever sees an opaque `search_id` and `result_id`s. The qBittorrent search id,
the plugin engine and the torrent URL stay here: `get_result` hands them to the download
pipeline (01-08), which is the only code that may turn a result into a torrent. Nothing in this
module adds, starts or fetches a torrent; it only uses the `search/*` endpoints.

qBittorrent allows five searches at a time, so this service keeps at most
`max_active_searches` running, deletes every search as soon as it ends, and keeps the filtered
rows here for `result_cache_ttl` seconds.
"""

import asyncio
import logging
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from app.config import Settings
from app.content_type import PLUGIN_CATEGORY, ContentType
from app.qbit.client import QbitClient, QbitError
from app.search.filters import (
    FilterConfig,
    FilteredResult,
    RawResult,
    min_size_bytes,
    normalize_and_filter,
)

logger = logging.getLogger(__name__)

QBIT_STATUS_STOPPED = "Stopped"
HTTP_CONFLICT = 409
HTTP_NOT_FOUND = 404


@dataclass(frozen=True, slots=True)
class CachedResult:
    """What a download needs from a result; never serialized to the browser."""

    result_id: str
    engine: str
    file_url: str
    type: ContentType
    name: str
    expires_at: float


@dataclass(frozen=True, slots=True)
class SearchSnapshot:
    search_id: str
    done: bool
    timed_out: bool
    results: list[FilteredResult]


@dataclass(slots=True)
class SearchEntry:
    search_id: str
    qbit_id: int
    type: ContentType
    started_at: float
    expires_at: float
    done: bool = False
    timed_out: bool = False
    results: list[FilteredResult] = field(default_factory=list)
    # One poll at a time per search, so a search ends (and is deleted) exactly once.
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class SearchService:
    def __init__(
        self,
        qbit: QbitClient,
        settings: Settings,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._qbit = qbit
        self._settings = settings
        self._clock = clock
        self._entries: dict[str, SearchEntry] = {}
        self._cache: dict[str, CachedResult] = {}
        self._start_lock = asyncio.Lock()

    async def start(self, q: str, content_type: ContentType) -> str:
        """Start a plugin search for an already validated query; returns the opaque search id."""
        async with self._start_lock:
            await self._purge()
            await self._make_room()
            qbit_id = await self._begin(q, content_type)
            now = self._clock()
            entry = SearchEntry(
                search_id=secrets.token_hex(8),
                qbit_id=qbit_id,
                type=content_type,
                started_at=now,
                expires_at=now + self._settings.result_cache_ttl,
            )
            self._entries[entry.search_id] = entry
            return entry.search_id

    async def snapshot(self, search_id: str) -> SearchSnapshot | None:
        """Filtered, seeder-sorted rows received so far; None for an unknown or expired id."""
        await self._purge()
        entry = self._entries.get(search_id)
        if entry is None:
            return None
        if not entry.done:
            await self._refresh(entry)
        return SearchSnapshot(entry.search_id, entry.done, entry.timed_out, list(entry.results))

    def get_result(self, result_id: str) -> CachedResult | None:
        """The cached engine and URL of a result from a recent search, or None."""
        cached = self._cache.get(result_id)
        if cached is None or cached.expires_at <= self._clock():
            return None
        return cached

    async def close(self) -> None:
        """Stop and delete every running search (application shutdown)."""
        for entry in self._active():
            await self._end(entry, stop=True)

    # -- qBittorrent calls ---------------------------------------------------------------

    async def _begin(self, q: str, content_type: ContentType) -> int:
        category = PLUGIN_CATEGORY[content_type]
        try:
            return await self._qbit.search_start(q, category, "enabled")
        except QbitError as exc:
            if exc.status != HTTP_CONFLICT:
                raise
        # qBittorrent is at its limit: free every search it holds, then try exactly once more.
        await self._clear_qbittorrent()
        return await self._qbit.search_start(q, category, "enabled")

    async def _clear_qbittorrent(self) -> None:
        for entry in self._active():
            await self._end(entry, stop=True)
        # Searches left behind by a crashed backend are not tracked here; sweep them too.
        try:
            leftovers = await self._qbit.search_status()
        except QbitError as exc:
            logger.warning("search status sweep failed: %s", type(exc).__name__)
            return
        for row in leftovers:
            await self._drop(row.get("id"), stop=True)

    async def _drop(self, qbit_id: object, *, stop: bool) -> None:
        """Best-effort stop and delete; a failure leaves the search for the next sweep."""
        if not isinstance(qbit_id, int):
            return
        try:
            if stop:
                await self._qbit.search_stop(qbit_id)
            await self._qbit.search_delete(qbit_id)
        except QbitError as exc:
            logger.warning("search cleanup failed: %s", type(exc).__name__)

    # -- lifecycle -----------------------------------------------------------------------

    def _active(self) -> list[SearchEntry]:
        return sorted(
            (entry for entry in self._entries.values() if not entry.done),
            key=lambda entry: entry.started_at,
        )

    async def _make_room(self) -> None:
        """Stop and delete the oldest running searches until a new one fits."""
        active = self._active()
        while len(active) >= self._settings.max_active_searches:
            await self._end(active.pop(0), stop=True)

    async def _purge(self) -> None:
        now = self._clock()
        for search_id, entry in list(self._entries.items()):
            if entry.expires_at <= now:
                if not entry.done:  # abandoned: nobody polled it to the end
                    await self._end(entry, stop=True)
                self._entries.pop(search_id, None)
        for result_id, cached in list(self._cache.items()):
            if cached.expires_at <= now:
                del self._cache[result_id]

    async def _end(self, entry: SearchEntry, *, stop: bool, delete: bool = True) -> None:
        """Mark a search done and remove it from qBittorrent, once."""
        async with entry.lock:
            await self._finish(entry, stop=stop, delete=delete)

    async def _finish(self, entry: SearchEntry, *, stop: bool, delete: bool = True) -> None:
        # The caller holds entry.lock.
        if entry.done:
            return
        entry.done = True
        if stop:
            # Cut short (timeout, eviction, shutdown): with nothing to show, the UI says so.
            entry.timed_out = not entry.results
        entry.expires_at = self._clock() + self._settings.result_cache_ttl
        if stop or delete:
            await self._drop(entry.qbit_id, stop=stop)

    async def _refresh(self, entry: SearchEntry) -> None:
        async with entry.lock:
            if entry.done:
                return
            try:
                payload = await self._qbit.search_results(entry.qbit_id, limit=0, offset=0)
            except QbitError as exc:
                if exc.status != HTTP_NOT_FOUND:
                    raise
                # qBittorrent forgot the search (it restarted): end with the rows already seen.
                await self._finish(entry, stop=False, delete=False)
                return
            entry.results = self._filter(entry, payload.get("results") or [])
            self._remember(entry)
            if payload.get("status") == QBIT_STATUS_STOPPED:
                await self._finish(entry, stop=False)
            elif self._clock() - entry.started_at > self._settings.search_timeout:
                # A timeout is an ordinary end, never an error status.
                await self._finish(entry, stop=True)

    # -- results -------------------------------------------------------------------------

    def _filter(self, entry: SearchEntry, rows: list[dict]) -> list[FilteredResult]:
        settings = self._settings
        cfg = FilterConfig(
            min_seeders=settings.min_seeders,
            min_size_bytes=min_size_bytes(
                entry.type, settings.min_film_size_mb, settings.min_serie_size_mb
            ),
            suspicious_terms=settings.suspicious_term_list,
        )
        filtered = normalize_and_filter((RawResult.from_qbit(row) for row in rows), cfg)
        return filtered[: settings.max_results]

    def _remember(self, entry: SearchEntry) -> None:
        expires_at = self._clock() + self._settings.result_cache_ttl
        for result in entry.results:
            self._cache[result.result_id] = CachedResult(
                result_id=result.result_id,
                engine=result.engine,
                file_url=result.file_url,
                type=entry.type,
                name=result.name,
                expires_at=expires_at,
            )
