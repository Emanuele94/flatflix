"""Tests for the pure search-result filters (SRCH-02, D-07, D-08, D-09)."""

import base64
import random
import re

import pytest

from app.search.filters import (
    DEFAULT_SUSPICIOUS_TERMS,
    FilterConfig,
    RawResult,
    dedupe_key,
    human_size,
    infohash,
    is_public_address,
    is_safe_torrent_url,
    is_suspicious,
    min_size_bytes,
    normalize_and_filter,
    quality_badge,
    result_id,
)

MB = 1024 * 1024
GB = 1024**3

# Verbatim qBittorrent 5.2.4 search result row (research, Pattern 2).
LIME_ROW = {
    "descrLink": "https://www.limetorrents.lol/Big-Buck-Bunny-trailer-torrent-157833.html",
    "engineName": "limetorrents",
    "fileName": "Big Buck Bunny trailer",
    "fileSize": 4362076,
    "fileUrl": "https://www.limetorrents.lol/Big-Buck-Bunny-trailer-torrent-157833.html",
    "nbLeechers": 0,
    "nbSeeders": 7,
    "pubDate": 1761083074,
    "siteUrl": "https://www.limetorrents.lol",
}

HASH_A = "0123456789abcdef0123456789abcdef01234567"
HASH_B = "fedcba9876543210fedcba9876543210fedcba98"


def magnet(btih: str) -> str:
    return f"magnet:?xt=urn:btih:{btih}&dn=whatever"


def raw(
    name="Film 2010 1080p",
    size=2 * GB,
    seeders=50,
    leechers=3,
    engine="eng",
    file_url=None,
    site_url="https://site.example",
) -> RawResult:
    return RawResult(
        name=name,
        size=size,
        seeders=seeders,
        leechers=leechers,
        engine=engine,
        file_url=file_url if file_url is not None else magnet(HASH_A),
        site_url=site_url,
    )


CFG = FilterConfig()


# --- RawResult --------------------------------------------------------------------------


def test_raw_result_maps_the_verbatim_limetorrents_row():
    result = RawResult.from_qbit(LIME_ROW)

    assert result == RawResult(
        name="Big Buck Bunny trailer",
        size=4362076,
        seeders=7,
        leechers=0,
        engine="limetorrents",
        file_url=LIME_ROW["fileUrl"],
        site_url="https://www.limetorrents.lol",
    )


def test_raw_result_missing_numbers_become_minus_one():
    result = RawResult.from_qbit({"fileName": "x", "engineName": "e", "fileUrl": "u"})

    assert (result.size, result.seeders, result.leechers) == (-1, -1, -1)


def test_verbatim_row_passes_when_thresholds_allow_it():
    cfg = FilterConfig(min_seeders=5, min_size_bytes=1)

    [row] = normalize_and_filter([RawResult.from_qbit(LIME_ROW)], cfg)

    assert row.name == "Big Buck Bunny trailer"
    assert row.size == 4362076
    assert row.size_human == "4.2 MB"
    assert row.seeders == 7
    assert row.source == "limetorrents"
    assert row.quality is None
    assert row.engine == "limetorrents"
    assert row.file_url == LIME_ROW["fileUrl"]


# --- thresholds -------------------------------------------------------------------------


def test_min_seeders_boundary_four_dropped_five_kept():
    rows = [
        raw(name="four", seeders=4, file_url=magnet(HASH_A)),
        raw(name="five", seeders=5, file_url=magnet(HASH_B)),
    ]

    result = normalize_and_filter(rows, CFG)

    assert [r.name for r in result] == ["five"]


def test_unknown_seeders_and_unknown_size_are_dropped():
    rows = [
        raw(name="no-seeders", seeders=-1, file_url=magnet(HASH_A)),
        raw(name="no-size", size=-1, file_url=magnet(HASH_B)),
    ]

    assert normalize_and_filter(rows, CFG) == []


def test_min_size_boundary_uses_the_config_threshold():
    cfg = FilterConfig(min_size_bytes=500 * MB)
    rows = [
        raw(name="exact", size=500 * MB, file_url=magnet(HASH_A)),
        raw(name="short", size=500 * MB - 1, file_url=magnet(HASH_B)),
    ]

    assert [r.name for r in normalize_and_filter(rows, cfg)] == ["exact"]


def test_min_size_bytes_per_type():
    assert min_size_bytes("film", 500, 100) == 500 * MB
    assert min_size_bytes("serie", 500, 100) == 100 * MB


def test_min_size_bytes_rejects_unknown_type():
    with pytest.raises(ValueError):
        min_size_bytes("music", 500, 100)


@pytest.mark.parametrize(
    "name",
    [
        "Great Movie.exe",
        "Great Movie Password inside",
        "Great Movie CODEC required",
        "Great Movie keygen",
        "Great Movie crack",
        "Great Movie Activator",
        "Great Movie installer",
    ],
)
def test_suspicious_names_are_dropped(name):
    assert is_suspicious(name, DEFAULT_SUSPICIOUS_TERMS)
    assert normalize_and_filter([raw(name=name)], CFG) == []


def test_clean_name_is_kept():
    assert not is_suspicious("Sintel 2010 1080p", DEFAULT_SUSPICIOUS_TERMS)
    assert [r.name for r in normalize_and_filter([raw(name="Sintel 2010 1080p")], CFG)] == [
        "Sintel 2010 1080p"
    ]


def test_suspicious_matching_uses_casefold():
    assert is_suspicious("SETUP.EXE", (".exe",))
    assert is_suspicious("STRASSE KEYGEN", ("keygen",))


# --- dedupe -----------------------------------------------------------------------------


def test_same_btih_in_upper_and_lower_hex_merges_keeping_higher_seeders():
    rows = [
        raw(name="low", seeders=10, file_url=magnet(HASH_A.upper())),
        raw(name="high", seeders=90, file_url=magnet(HASH_A.lower()), engine="other"),
    ]

    [row] = normalize_and_filter(rows, CFG)

    assert row.seeders == 90
    assert row.name == "high"


def test_base32_btih_equals_its_hex_form():
    b32 = base64.b32encode(bytes.fromhex(HASH_A)).decode()
    assert len(b32) == 32

    assert infohash(magnet(b32)) == HASH_A
    assert infohash(magnet(HASH_A.upper())) == HASH_A
    assert dedupe_key("e1", magnet(b32)) == dedupe_key("e2", magnet(HASH_A))


def test_infohash_rejects_non_magnet_and_malformed_values():
    assert infohash("https://example.org/torrent/1") is None
    assert infohash("magnet:?xt=urn:btih:tooshort") is None
    assert infohash("magnet:?dn=no-xt") is None


def test_different_hashes_with_identical_names_both_stay():
    rows = [
        raw(name="Same Name", file_url=magnet(HASH_A)),
        raw(name="Same Name", file_url=magnet(HASH_B)),
    ]

    assert len(normalize_and_filter(rows, CFG)) == 2


def test_non_magnet_rows_with_same_engine_and_url_merge():
    url = "https://site.example/torrent/42"
    rows = [
        raw(seeders=10, engine="eng", file_url=url),
        raw(seeders=30, engine="eng", file_url=url),
        raw(seeders=20, engine="other", file_url=url),
    ]

    result = normalize_and_filter(rows, CFG)

    assert sorted(r.seeders for r in result) == [20, 30]


def test_equal_seeders_first_seen_wins_on_merge():
    rows = [
        raw(name="first", seeders=10, file_url=magnet(HASH_A)),
        raw(name="second", seeders=10, file_url=magnet(HASH_A)),
    ]

    [row] = normalize_and_filter(rows, CFG)

    assert row.name == "first"


def test_result_id_is_16_lower_hex_and_stable():
    key = dedupe_key("eng", magnet(HASH_A))

    rid = result_id(key)

    assert re.fullmatch(r"[0-9a-f]{16}", rid)
    assert result_id(key) == rid
    assert result_id(dedupe_key("eng", magnet(HASH_B))) != rid


def test_result_id_survives_a_change_of_winning_engine():
    first = normalize_and_filter([raw(engine="a", seeders=10)], CFG)[0].result_id
    second = normalize_and_filter([raw(engine="b", seeders=99)], CFG)[0].result_id

    assert first == second


# --- sort -------------------------------------------------------------------------------


def test_sort_is_seeders_then_leechers_then_name_then_result_id():
    rows = [
        raw(name="b", seeders=10, leechers=1, file_url=magnet("1" * 40)),
        raw(name="a", seeders=10, leechers=1, file_url=magnet("2" * 40)),
        raw(name="Z", seeders=10, leechers=5, file_url=magnet("3" * 40)),
        raw(name="top", seeders=99, leechers=0, file_url=magnet("4" * 40)),
        raw(name="a", seeders=10, leechers=1, file_url=magnet("5" * 40)),
    ]

    result = normalize_and_filter(rows, CFG)

    assert [r.name for r in result[:4]] == ["top", "Z", "a", "a"]
    assert result[-1].name == "b"
    tied = [r for r in result if r.name == "a"]
    assert [r.result_id for r in tied] == sorted(r.result_id for r in tied)


def test_shuffled_input_gives_identical_output():
    rows = [
        raw(name=f"n{i % 3}", seeders=10 + i % 4, leechers=i % 2, file_url=magnet(f"{i:040x}"))
        for i in range(12)
    ]
    expected = normalize_and_filter(rows, CFG)

    for seed in range(5):
        shuffled = rows[:]
        random.Random(seed).shuffle(shuffled)
        assert normalize_and_filter(shuffled, CFG) == expected


# --- badge, size, text ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "badge"),
    [
        ("Film 2160p", "4K"),
        ("Film 4K HDR", "4K"),
        ("UHD Remux", "4K"),
        ("x 1080p", "1080p"),
        ("x 720p", "720p"),
        ("DVDRip", "SD"),
        ("Film.576p.x264", "SD"),
        ("4kids show", None),
        ("Film 2010", None),
    ],
)
def test_quality_badge(name, badge):
    assert quality_badge(name) == badge


def test_badge_never_removes_a_row():
    rows = [raw(name="No badge here", file_url=magnet(HASH_A))]

    [row] = normalize_and_filter(rows, CFG)

    assert row.quality is None


def test_human_size():
    assert human_size(512) == "512 B"
    assert human_size(1023) == "1023 B"
    assert human_size(1024) == "1.0 KB"
    assert human_size(4509715660) == "4.2 GB"


def test_names_with_accents_and_emoji_are_returned_unchanged():
    name = "Città Perduta 🎬 2010 1080p"

    [row] = normalize_and_filter([raw(name=name)], CFG)

    assert row.name == name


def test_empty_input_returns_empty_list():
    assert normalize_and_filter([], CFG) == []


def test_every_row_carries_size_human():
    [row] = normalize_and_filter([raw(size=4509715660)], CFG)

    assert row.size_human == "4.2 GB"


# --- untrusted result URLs (WR-03) ---------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        magnet(HASH_A),
        "magnet:?xt=urn:btih:" + HASH_A + "&dn=Big Buck Bunny",
        "https://www.limetorrents.lol/Big-Buck-Bunny-trailer-torrent-157833.html",
        "http://tracker.example.org:8080/t/1.torrent",
        "https://93.184.216.34/t/1.torrent",
    ],
)
def test_magnets_and_public_http_urls_are_safe(url):
    assert is_safe_torrent_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "",
        "file:///etc/passwd",
        "ftp://example.org/t.torrent",
        "data:text/plain,x",
        "javascript:alert(1)",
        "//example.org/t.torrent",
        "http://localhost/t",
        "http://qbittorrent:8080/api/v2/app/shutdown",
        "http://backend:8000/api/health",
        "http://127.0.0.1:8080/",
        "http://[::1]/",
        "http://10.0.0.5/t",
        "http://192.168.1.10/t",
        "http://172.16.0.9/t",
        "http://169.254.169.254/latest/meta-data/",
        "http://nas.local/t",
        "http://printer.lan/t",
        "http://user:pass@example.org/t",
        "http://example.org:notaport/t",
        "https://example.org/t\nhttp://127.0.0.1/",
        " https://example.org/t",
    ],
)
def test_other_schemes_and_internal_hosts_are_not_safe(url):
    assert is_safe_torrent_url(url) is False


def test_a_row_with_an_unsafe_url_is_dropped_whatever_its_seeders():
    rows = [
        raw(name="evil", seeders=999, file_url="http://qbittorrent:8080/x"),
        raw(name="evil2", seeders=998, file_url="file:///etc/passwd"),
        raw(name="good", seeders=10, file_url=magnet(HASH_B)),
    ]
    assert [r.name for r in normalize_and_filter(rows, CFG)] == ["good"]


def test_a_row_from_an_engine_that_is_not_an_installed_plugin_is_dropped():
    cfg = FilterConfig(allowed_engines=frozenset({"limetorrents"}))
    rows = [
        raw(name="rogue", seeders=99, engine="rogue", file_url=magnet(HASH_A)),
        raw(name="lime", seeders=10, engine="limetorrents", file_url=magnet(HASH_B)),
    ]
    assert [r.name for r in normalize_and_filter(rows, cfg)] == ["lime"]


@pytest.mark.parametrize(
    ("address", "public"),
    [
        ("93.184.216.34", True),
        ("2606:2800:220:1:248:1893:25c8:1946", True),
        ("127.0.0.1", False),
        ("10.1.2.3", False),
        ("192.168.0.1", False),
        ("169.254.1.1", False),
        ("::1", False),
        ("fe80::1%eth0", False),
        ("not-an-address", False),
    ],
)
def test_is_public_address(address, public):
    assert is_public_address(address) is public
