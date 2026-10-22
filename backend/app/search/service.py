"""Live search against qBittorrent's plugins with a server-side result cache (SRCH-01..03).

The browser only ever sees an opaque `search_id` and `result_id`s. The qBittorrent search id,
the plugin engine and the torrent URL stay here: `get_result` hands them to the download
pipeline (01-08), which is the only code that may turn a result into a torrent. Nothing in this
module adds, starts or fetches a torrent.
"""

import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from app.config import Settings
from app.content_type import PLUGIN_CATEGORY, ContentType
from app.qbit.client import QbitClient
from app.search.filters import (
    DEFAULT_SUSPICIOUS_TERMS,
    FilterConfig,
    FilteredResult,
    RawResult,
    min_size_bytes,
    normalize_and_filter,
)

QBIT_STATUS_STOPPED = "Stopped"


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
    done: bool = False
    timed_out: bool = False
    results: list[FilteredResult] = field(default_factory=list)


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

    async def start(self, q: str, content_type: ContentType) -> str:
        """Start a plugin search for an already validated query; returns the opaque search id."""
        qbit_id = await self._qbit.search_start(q, PLUGIN_CATEGORY[content_type], "enabled")
        entry = SearchEntry(
            search_id=secrets.token_hex(8),
            qbit_id=qbit_id,
            type=content_type,
            started_at=self._clock(),
        )
        self._entries[entry.search_id] = entry
        return entry.search_id

    async def snapshot(self, search_id: str) -> SearchSnapshot | None:
        """Filtered, seeder-sorted rows received so far; None for an unknown search id."""
        entry = self._entries.get(search_id)
        if entry is None:
            return None
        if not entry.done:
            await self._refresh(entry)
        return SearchSnapshot(entry.search_id, entry.done, entry.timed_out, list(entry.results))

    def get_result(self, result_id: str) -> CachedResult | None:
        """The cached engine and URL of a result from a recent search, or None."""
        return self._cache.get(result_id)

    async def _refresh(self, entry: SearchEntry) -> None:
        payload = await self._qbit.search_results(entry.qbit_id, limit=0, offset=0)
        entry.results = self._filter(entry, payload.get("results") or [])
        self._remember(entry)
        if payload.get("status") == QBIT_STATUS_STOPPED:
            entry.done = True

    def _filter(self, entry: SearchEntry, rows: list[dict]) -> list[FilteredResult]:
        settings = self._settings
        cfg = FilterConfig(
            min_seeders=settings.min_seeders,
            min_size_bytes=min_size_bytes(
                entry.type, settings.min_film_size_mb, settings.min_serie_size_mb
            ),
            suspicious_terms=DEFAULT_SUSPICIOUS_TERMS,
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
