"""Pure search-result normalization, filtering, dedupe, sort, badge and size (SRCH-02).

No I/O and no framework or config imports: thresholds and term lists arrive as arguments so the
search service (01-07) can feed them from Settings. Result names, sizes and URLs come from
third-party search plugins and are treated as untrusted text.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import ipaddress
import re
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

MB = 1024 * 1024

# D-08 discretion; one place. 01-07 lets the env SUSPICIOUS_TERMS replace it.
DEFAULT_SUSPICIOUS_TERMS: tuple[str, ...] = (
    ".exe",
    ".scr",
    ".bat",
    ".cmd",
    ".msi",
    ".lnk",
    ".ps1",
    ".vbs",
    "password",
    "codec",
    "keygen",
    "crack",
    "activator",
    "installer",
)

_HEX40 = re.compile(r"[0-9a-fA-F]{40}")
_BASE32_32 = re.compile(r"[A-Za-z2-7]{32}")

# (badge, pattern) in priority order; no letter or digit may touch the token on either side.
_BADGES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (badge, re.compile(rf"(?<![a-z0-9])(?:{alts})(?![a-z0-9])"))
    for badge, alts in (
        ("4K", "2160p|4k|uhd"),
        ("1080p", "1080p"),
        ("720p", "720p"),
        ("SD", "480p|576p|dvdrip"),
    )
)


def _number(row: dict, key: str) -> int:
    """Plugin spec: unknown numbers are -1; a missing or null value is treated the same."""
    value = row.get(key)
    return -1 if value is None else int(value)


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
        return cls(
            name=str(row.get("fileName", "")),
            size=_number(row, "fileSize"),
            seeders=_number(row, "nbSeeders"),
            leechers=_number(row, "nbLeechers"),
            engine=str(row.get("engineName", "")),
            file_url=str(row.get("fileUrl", "")),
            site_url=str(row.get("siteUrl", "")),
        )


@dataclass(frozen=True, slots=True)
class FilterConfig:
    min_seeders: int = 5
    min_size_bytes: int = 500 * MB
    suspicious_terms: tuple[str, ...] = DEFAULT_SUSPICIOUS_TERMS
    # Names of the installed search plugins; a row from any other engine is dropped. None means
    # no restriction (the pure filter tests); the search service always passes the real list.
    allowed_engines: frozenset[str] | None = None


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
    # Server-only: 01-07 never serializes engine or file_url to the browser.
    engine: str
    file_url: str


# Host names that point inside the household network or the compose networks, never at a tracker
# page. Single-label names (`qbittorrent`, `backend`, `web`) are refused too.
_INTERNAL_SUFFIXES = (
    ".localhost",
    ".local",
    ".localdomain",
    ".internal",
    ".lan",
    ".home",
    ".home.arpa",
    ".intranet",
    ".corp",
)


def is_safe_torrent_url(file_url: str) -> bool:
    """True for a magnet link or an http(s) URL that does not point at a private address.

    Plugin results are untrusted: a hostile indexer could hand back `http://qbittorrent:8080/...`,
    `file:///...` or a LAN address, and qBittorrent (or the plugin's downloader) would fetch it
    from inside the household network (WR-03). This is the static half of the check; the
    download pipeline also resolves the host name before it adds a non-magnet URL.
    """
    if (
        not file_url
        or file_url != file_url.strip()
        or any(ord(c) < 32 or ord(c) == 127 for c in file_url)
    ):
        return False
    try:
        parts = urlsplit(file_url)
        scheme = parts.scheme.lower()
        if scheme == "magnet":
            return True
        if scheme not in ("http", "https") or parts.username or parts.password:
            return False
        host = (parts.hostname or "").rstrip(".").lower()
        parts.port  # noqa: B018 - raises ValueError for a malformed port
    except ValueError:
        return False
    if not host:
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        pass  # a name, not an address
    if "." not in host or host == "localhost":
        return False
    return not host.endswith(_INTERNAL_SUFFIXES)


def is_public_address(address: str) -> bool:
    """True when a resolved IP address is a globally routable one."""
    try:
        return ipaddress.ip_address(address.split("%", 1)[0]).is_global
    except ValueError:
        return False


def min_size_bytes(content_type: str, min_film_mb: int, min_serie_mb: int) -> int:
    """Size floor in bytes; for series it is the per-episode threshold (D-08 discretion)."""
    if content_type == "film":
        return min_film_mb * MB
    if content_type == "serie":
        return min_serie_mb * MB
    raise ValueError(f"unknown content type: {content_type!r}")


def infohash(file_url: str) -> str | None:
    """Lower-case hex btih of a magnet URL (hex-40 or base32-32), else None."""
    parts = urlsplit(file_url)
    if parts.scheme.lower() != "magnet":
        return None
    for xt in parse_qs(parts.query).get("xt", []):
        if xt[:9].lower() != "urn:btih:":
            continue
        value = xt[9:]
        if _HEX40.fullmatch(value):
            return value.lower()
        if _BASE32_32.fullmatch(value):
            try:
                return base64.b32decode(value.upper()).hex()
            except binascii.Error:
                return None
    return None


def dedupe_key(engine: str, file_url: str) -> str:
    digest = infohash(file_url)
    if digest is not None:
        return "btih:" + digest
    return "url:" + engine + "\n" + file_url


def result_id(key: str) -> str:
    """Stable 16-hex id of a dedupe key (survives which engine wins the merge)."""
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def quality_badge(name: str) -> str | None:
    """Display-only badge (D-08); it never filters."""
    folded = name.casefold()
    for badge, pattern in _BADGES:
        if pattern.search(folded):
            return badge
    return None


def is_suspicious(name: str, terms: Iterable[str]) -> bool:
    folded = name.casefold()
    return any(term.casefold() in folded for term in terms)


def human_size(n: int) -> str:
    """1024-based size with one decimal from KB up ("4.2 GB"), integer bytes below 1 KB."""
    if n < 1024:
        return f"{n} B"
    value = float(n)
    for unit in ("KB", "MB", "GB", "TB"):
        value /= 1024
        if round(value, 1) < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
    raise AssertionError("unreachable")


def normalize_and_filter(rows: Iterable[RawResult], cfg: FilterConfig) -> list[FilteredResult]:
    """Drop dead, tiny, unknown and suspicious rows, merge duplicates, sort deterministically.

    Merging keeps the highest seeders (first seen wins ties). No row cap here.
    """
    merged: dict[str, RawResult] = {}
    for row in rows:
        if cfg.allowed_engines is not None and row.engine not in cfg.allowed_engines:
            continue
        if not is_safe_torrent_url(row.file_url):
            continue
        if row.seeders < 0 or row.seeders < cfg.min_seeders:
            continue
        if row.size < 0 or row.size < cfg.min_size_bytes:
            continue
        if is_suspicious(row.name, cfg.suspicious_terms):
            continue
        key = dedupe_key(row.engine, row.file_url)
        best = merged.get(key)
        if best is None or row.seeders > best.seeders:
            merged[key] = row

    results = [
        FilteredResult(
            result_id=result_id(key),
            name=row.name,
            size=row.size,
            size_human=human_size(row.size),
            seeders=row.seeders,
            leechers=row.leechers,
            source=row.engine,
            quality=quality_badge(row.name),
            engine=row.engine,
            file_url=row.file_url,
        )
        for key, row in merged.items()
    ]
    results.sort(key=lambda r: (-r.seeders, -r.leechers, r.name.casefold(), r.result_id))
    return results
