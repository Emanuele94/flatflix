"""Pure search-result filters (RED skeleton: behaviour not implemented yet)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

DEFAULT_SUSPICIOUS_TERMS: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RawResult:
    name: str
    size: int
    seeders: int
    leechers: int
    engine: str
    file_url: str
    site_url: str

    @classmethod
    def from_qbit(cls, row: dict) -> RawResult:
        return cls(name="", size=0, seeders=0, leechers=0, engine="", file_url="", site_url="")


@dataclass(frozen=True, slots=True)
class FilterConfig:
    min_seeders: int = 5
    min_size_bytes: int = 500 * 1024 * 1024
    suspicious_terms: tuple[str, ...] = DEFAULT_SUSPICIOUS_TERMS


@dataclass(frozen=True, slots=True)
class FilteredResult:
    result_id: str
    name: str
    size: int
    size_human: str
    seeders: int
    leechers: int
    source: str
    quality: str | None
    engine: str
    file_url: str


def min_size_bytes(content_type: str, min_film_mb: int, min_serie_mb: int) -> int:
    return 0


def infohash(file_url: str) -> str | None:
    return None


def dedupe_key(engine: str, file_url: str) -> str:
    return ""


def result_id(key: str) -> str:
    return ""


def quality_badge(name: str) -> str | None:
    return None


def is_suspicious(name: str, terms: Iterable[str]) -> bool:
    return False


def human_size(n: int) -> str:
    return ""


def normalize_and_filter(rows: Iterable[RawResult], cfg: FilterConfig) -> list[FilteredResult]:
    return [
        FilteredResult("", r.name, r.size, "", r.seeders, r.leechers, r.engine, None, "", "")
        for r in rows
    ]
