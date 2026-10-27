#!/usr/bin/env python3
"""The naming scan test (NAME-01): can stock Jellyfin identify raw torrent names on its own?

Usage:
    python3 scripts/name_scan.py capture [--base URL] [--queries PATH] [--out PATH]
                                         [--films N] [--series N]
    python3 scripts/name_scan.py label [--corpus PATH]
    python3 scripts/name_scan.py run [--corpus PATH] [--base URL]
    python3 scripts/name_scan.py report [--results PATH] [--sample-results PATH] [--out PATH]
                                        [--decision TEXT]
    python3 scripts/name_scan.py validate-report [--doc PATH]

`capture` signs in to the portal like the household does and runs the searches listed in the
queries file (lines `film: <query>` or `serie: <query>`; blank lines and # comments are ignored),
7 seconds apart so the portal's 10 searches per minute are never hit. It keeps the torrent names
of the results, attaches a draft truth label and writes them to the corpus with
`"confirmed": false`. It reads search results only: no download is ever started. It prints counts.

`label` walks the unconfirmed entries in the admin's own terminal: Enter accepts the draft,
`title|year` or `series|season|episode` replaces it, `x` drops the entry, `q` saves and stops.
It saves after every answer.

`run` turns every labelled torrent name of a corpus into a 1-second clip at the path the Phase 2.1
hand-off would create (D-46: a single-file torrent sits in the library root, a folder torrent keeps
its folder with the file inside), lets Jellyfin scan them with its own parser and TheMovieDb in the
admin-only "Raw Movies" and "Raw TV" libraries, and classifies each name against its truth label:

    identified    Jellyfin's title and year (or series, season and episode) equal the label
    unidentified  no provider id, or an episode with no series or no season and episode number
    wrong title   Jellyfin matched something else (a 1982 film for a 2017 label)

The D-92 bar: relaxed naming meets the bar only when identified is at least 90 % (inclusive) and
wrong title is 0. Otherwise the rename step wins (D-90). The verdict is data, so `run` exits 0
either way; any FAIL line means no table and no verdict were written.

`report` writes docs/naming-scan.md: the method, the bar, the full table of the synthetic sample
and, for the real corpus, counts and failure classes only. It refuses to write when the text
carries a real name; `validate-report` runs the same check on the committed file.

Privacy (D-101): the real corpus, the results and the per-name table live in the gitignored
jellyfin/name-scan folder. `run` prints counts and step lines only, never a name. The synthetic
sample (scripts/name_scan_sample.json) uses open-licensed titles only and may be published.

Standard library only; ffmpeg runs by argument list; Raw Movies and Raw TV never get household
access and only scratch/Raw/Movies and scratch/Raw/TV are rebuilt.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
import urllib.error
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

SCRIPTS = Path(__file__).resolve().parent


def _load(name: str, filename: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses looks its own module up here
    spec.loader.exec_module(module)
    return module


js = _load("flatflix_ns_jellyfin_setup", "jellyfin_setup.py")
mc = _load("flatflix_ns_make_compat_clips", "make_compat_clips.py")
sm = _load("flatflix_ns_smoke", "smoke.py")

Fail = js.Fail
ROOT = Path(js.ROOT)
SCRATCH = Path(mc.SCRATCH)
WORK = Path(js.JELLYFIN_DIR) / "name-scan"
CORPUS = WORK / "corpus.json"
QUERIES = WORK / "queries.txt"
RESULTS = WORK / "results.json"
SAMPLE_RESULTS = WORK / "sample-results.json"
TABLE = WORK / "table.md"
SAMPLE_TABLE = WORK / "sample-table.md"
RAW = SCRATCH / "Raw"
SAMPLE = ROOT / "scripts" / "name_scan_sample.json"
REPORT = ROOT / "docs" / "naming-scan.md"

BAR_PERCENT = 90
VIDEO_EXTS = (".mkv", ".mp4", ".avi", ".m4v")
MAX_COMPONENT_BYTES = 200
KINDS = ("film", "episode")

RAW_MOVIES = "Raw Movies"
RAW_MOVIES_PATH = "/scratch/Raw/Movies"
RAW_TV = "Raw TV"
RAW_TV_PATH = "/scratch/Raw/TV"
CONTAINER_RAW = "/scratch/Raw"
PROVIDER_KEYS = ("tmdb", "imdb", "tvdb")

SEARCH_SPACING = 7.0  # seconds between portal searches: 10 per minute is the limit (SEC-05)
PATTERNS = (
    "flat episode file",
    "season pack",
    "absolute episode number",
    "year in title",
    "bracket group tag",
    "plain",
)
HEADINGS = (
    "# Naming scan test (NAME-01)",
    "## Real corpus",
    "## Synthetic sample",
    "## Decision",
)
PENDING_DECISION = "Pending: recorded in .planning/PROJECT.md after the real scan (plan 03-09)."
MIN_TITLE_CHARS = 8  # a draft title this long counts as a real name in the privacy check

INTRO_PARAGRAPHS = (
    (
        "Who gives downloaded files their library names: stock Jellyfin on the raw torrent "
        "names, or a rename step in the portal? The scan test answers it with data. Raw "
        "torrent-style names become 1-second clips at the paths the Phase 2.1 hand-off would "
        "create (a single-file torrent in the library root, a folder torrent as "
        "`<name>/<file>`), stock Jellyfin scans them with its own parser and TheMovieDb in "
        "admin-only Raw Movies and Raw TV libraries, and every name is classified against a "
        "hand-confirmed truth label as identified, unidentified or wrong title."
    ),
    (
        "The bar (D-92): relaxed naming is accepted only when at least 90 % of the names are "
        "identified and none is a wrong title. Otherwise the rename step wins (D-90 leans "
        "that way). TheMovieDb answers change over time, so a table is evidence of the method "
        "on the day it ran."
    ),
    (
        "Real torrent names carry scene and site tags and are never published (D-101): only "
        "counts and failure classes of the real corpus appear here, and the full table is "
        "shown for the synthetic sample of open-licensed titles."
    ),
    (
        "Run it with `python3 scripts/name_scan.py run --corpus <file>`; "
        "`report` rewrites this file and `validate-report` checks it."
    ),
)

SETTLE_POLL = 4.0
SETTLE_ROUNDS = 15


# --- pure rules -----------------------------------------------------------------------


def normalise(text: str) -> str:
    """NFKC, casefold, every non-alphanumeric character folded to a space, spaces collapsed."""
    folded = unicodedata.normalize("NFKC", str(text)).casefold()
    folded = unicodedata.normalize("NFKC", folded)
    spaced = "".join(ch if ch.isalnum() else " " for ch in folded)
    return " ".join(spaced.split())


def safe_component(name: str, reserve: int = 0) -> str:
    """A name that is safe as one path component: no separator, NUL or control character, no
    leading dot, at most MAX_COMPONENT_BYTES (minus `reserve`) UTF-8 bytes, never split mid-char."""
    cleaned = "".join(
        "_" if ch in "/\\" or unicodedata.category(ch).startswith("C") else ch for ch in str(name)
    )
    cleaned = cleaned.lstrip(". ").rstrip()
    budget = max(1, MAX_COMPONENT_BYTES - reserve)
    cleaned = cleaned.encode("utf-8")[:budget].decode("utf-8", errors="ignore")
    return cleaned or "unnamed"


def file_component(name: str) -> str:
    """safe_component for a file name: a video extension survives the byte cap, because ffmpeg picks
    the output format from it and a cut `.mkv` would fail the whole scan (WR-06)."""
    for ext in VIDEO_EXTS:
        if name.lower().endswith(ext):
            return safe_component(name[: -len(ext)], reserve=len(ext)) + name[-len(ext) :]
    return safe_component(name)


def layout(entry: dict) -> Path:
    """Where the Phase 2.1 hand-off would link this torrent, relative to the Raw folder."""
    root = "Movies" if entry["kind"] == "film" else "TV"
    name = str(entry["name"])
    if name.lower().endswith(VIDEO_EXTS):  # a single-file torrent: the file in the library root
        return Path(root) / file_component(name)
    inner = entry.get("inner")
    if inner:
        file_name = file_component(str(inner))
    else:
        file_name = safe_component(name, reserve=len(".mkv")) + ".mkv"
    return Path(root) / safe_component(name) / file_name


def _truth_problems(entry: dict) -> str | None:
    truth = entry.get("truth")
    if not isinstance(truth, dict):
        return "truth label is missing"
    if entry.get("kind") == "film":
        title, year = truth.get("title"), truth.get("year")
        if not isinstance(title, str) or not title.strip() or not isinstance(year, int):
            return "truth label is incomplete (title and year)"
    else:
        series = truth.get("series")
        if (
            not isinstance(series, str)
            or not series.strip()
            or not isinstance(truth.get("season"), int)
            or not isinstance(truth.get("episode"), int)
        ):
            return "truth label is incomplete (series, season and episode)"
    return None


def validate_corpus(entries: object) -> list[str]:
    """Every reason the corpus cannot be run. Messages carry an entry index, never a name."""
    if not isinstance(entries, list) or not entries:
        return ["corpus is empty"]
    problems: list[str] = []
    seen_names: dict[str, int] = {}
    seen_paths: dict[str, int] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            problems.append(f"entry {index}: not an object")
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            problems.append(f"entry {index}: name is missing")
            continue
        if entry.get("kind") not in KINDS:
            problems.append(f"entry {index}: kind must be film or episode")
            continue
        if entry.get("confirmed") is not True:
            problems.append(f"entry {index}: truth label is not confirmed")
        else:
            reason = _truth_problems(entry)
            if reason:
                problems.append(f"entry {index}: {reason}")
        if name in seen_names:
            problems.append(f"entry {index}: duplicate name (same as entry {seen_names[name]})")
            continue
        seen_names[name] = index
        path = layout(entry).as_posix()
        if path in seen_paths:
            problems.append(f"entry {index}: same path as entry {seen_paths[path]}")
        else:
            seen_paths[path] = index
    return problems


def _int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def has_provider_id(ids: object) -> bool:
    if not isinstance(ids, dict):
        return False
    return any(str(key).lower() in PROVIDER_KEYS and value for key, value in ids.items())


def classify(entry: dict, item: dict | None, series: dict | None = None) -> str:
    """identified, unidentified or wrong title (D-92); see the module docstring."""
    truth = entry["truth"]
    if item is None:
        return "unidentified"
    if entry["kind"] == "film":
        if not has_provider_id(item.get("ProviderIds")):
            return "unidentified"
        same_title = normalise(item.get("Name") or "") == normalise(truth["title"])
        same_year = _int(item.get("ProductionYear")) == _int(truth["year"])
        return "identified" if same_title and same_year else "wrong title"
    if not item.get("SeriesId") or series is None:
        return "unidentified"
    if not has_provider_id(series.get("ProviderIds")):
        return "unidentified"
    if normalise(series.get("Name") or "") != normalise(truth["series"]):
        return "wrong title"
    season, number = _int(item.get("ParentIndexNumber")), _int(item.get("IndexNumber"))
    if season is None or number is None:
        return "unidentified"
    same = season == _int(truth["season"]) and number == _int(truth["episode"])
    return "identified" if same else "wrong title"


def verdict(results: list[dict]) -> dict:
    """Counts and the D-92 bar from the three result words alone."""
    total = len(results)
    identified = sum(1 for r in results if r.get("result") == "identified")
    unidentified = sum(1 for r in results if r.get("result") == "unidentified")
    wrong = sum(1 for r in results if r.get("result") == "wrong title")
    return {
        "total": total,
        "identified": identified,
        "unidentified": unidentified,
        "wrong": wrong,
        "percent": identified * 100 // total if total else 0,
        "meets_bar": total > 0 and identified * 100 >= BAR_PERCENT * total and wrong == 0,
    }


def result_line(counts: dict) -> str:
    return (
        f"RESULT {counts['total']} names: identified {counts['identified']}, "
        f"unidentified {counts['unidentified']}, wrong title {counts['wrong']} "
        f"({counts['percent']} %)"
    )


def decision_line(counts: dict) -> str:
    if counts["meets_bar"]:
        return "VERDICT relaxed naming meets the bar"
    return "VERDICT relaxed naming does not meet the bar: the rename step wins (D-90, D-92)"


def _cell(text: object) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def render_table(results: list[dict]) -> str:
    """One row per name; written only after the scan has settled, so it is never empty."""
    lines = [
        "| Name | Expected | Jellyfin matched | Result |",
        "| --- | --- | --- | --- |",
    ]
    for row in results:
        cells = (row["name"], row["expected"], row["matched"], row["result"])
        lines.append("| " + " | ".join(_cell(c) for c in cells) + " |")
    return "\n".join(lines) + "\n"


def expected_text(entry: dict) -> str:
    truth = entry["truth"]
    if entry["kind"] == "film":
        return f"{truth['title']} ({truth['year']})"
    return f"{truth['series']} S{int(truth['season']):02d}E{int(truth['episode']):02d}"


def matched_text(entry: dict, item: dict | None, series: dict | None) -> str:
    if item is None:
        return "not listed"
    if entry["kind"] == "film":
        year = item.get("ProductionYear")
        name = item.get("Name") or "?"
        suffix = f" ({year})" if year else ""
        return name + suffix if has_provider_id(item.get("ProviderIds")) else f"{name} (no id)"
    if not item.get("SeriesId") or series is None:
        return "no series"
    season, number = _int(item.get("ParentIndexNumber")), _int(item.get("IndexNumber"))
    numbers = "no season or episode" if season is None or number is None else f"S{season:02d}E{number:02d}"
    return f"{series.get('Name') or '?'} {numbers}"


# --- labels and shapes ----------------------------------------------------------------

_YEAR = re.compile(r"^(?:19|20)\d{2}$")
_MARKER = re.compile(
    r"^(?:\d{3,4}p|web|webrip|web-dl|webdl|bluray|bdrip|brrip|dvdrip|hdtv|hdrip|hdr|hevc|x264"
    r"|x265|h264|h265|xvid|imax|remux|proper|repack|extended|uhd|dvdscr|cam)$",
    re.IGNORECASE,
)
_EXT = re.compile(r"\.(?:mkv|mp4|avi|m4v)$", re.IGNORECASE)
_LEADING_TAGS = re.compile(r"^(?:\s*\[[^\]]*\])+\s*")
_SEASON_EPISODE = re.compile(r"\bS(\d{1,2})\s?E(\d{1,3})\b", re.IGNORECASE)
_SEASON_ONLY = re.compile(r"\b(?:S|Season\s?)(\d{1,2})\b(?!\s?E\d)", re.IGNORECASE)
_CROSS = re.compile(r"\b(\d{1,2})x(\d{2,3})\b", re.IGNORECASE)
_ABSOLUTE = re.compile(r"\s-\s(\d{1,3})(?:v\d)?\b")
_PACK_WORDS = re.compile(r"\b(?:complete|season)\b", re.IGNORECASE)


def _plain(name: str) -> str:
    """The name without extension and leading group tags, dots and underscores as spaces."""
    text = _LEADING_TAGS.sub("", _EXT.sub("", str(name).strip()))
    return text.replace(".", " ").replace("_", " ")


def _series_text(text: str) -> str | None:
    tokens = text.replace("-", " ").split()
    if len(tokens) > 1 and _YEAR.match(tokens[-1]):
        tokens = tokens[:-1]
    return " ".join(tokens) or None


def draft_label(name: str, kind: str) -> dict | None:
    """A first guess at the truth label from the torrent name; the admin confirms it."""
    text = _plain(name)
    if kind == "film":
        tokens = text.replace("(", " ").replace(")", " ").replace("[", " ").replace("]", " ").split()
        cut = next((i for i, t in enumerate(tokens) if _MARKER.match(t)), len(tokens))
        years = [i for i, t in enumerate(tokens[:cut]) if i > 0 and _YEAR.match(t)]
        if not years:
            return None
        index = years[-1]
        title = " ".join(tokens[:index]).strip(" -")
        return {"title": title, "year": int(tokens[index])} if title else None
    found = _SEASON_EPISODE.search(text) or _CROSS.search(text)
    if found:
        series = _series_text(text[: found.start()])
        season, number = int(found.group(1)), int(found.group(2))
    elif (found := _SEASON_ONLY.search(text)) is not None:
        series = _series_text(text[: found.start()])
        season, number = int(found.group(1)), None
    elif (found := _ABSOLUTE.search(text)) is not None:
        series = _series_text(text[: found.start()])
        season, number = 1, int(found.group(1))
    else:
        return None
    if series is None:
        return None
    return {"series": series, "season": season, "episode": number}


def truth_from_text(kind: str, text: str) -> dict:
    """`title|year` for a film, `series|season|episode` for an episode; ValueError when malformed."""
    parts = [part.strip() for part in text.split("|")]
    if kind == "film":
        if len(parts) != 2 or not parts[0]:
            raise ValueError("expected title|year")
        return {"title": parts[0], "year": int(parts[1])}
    if len(parts) != 3 or not parts[0]:
        raise ValueError("expected series|season|episode")
    return {"series": parts[0], "season": int(parts[1]), "episode": int(parts[2])}


def apply_answer(entry: dict, answer: str) -> str:
    """One answer of `label`: returns next, again, drop or quit and updates the entry."""
    text = answer.strip()
    if text.lower() == "x":
        return "drop"
    if text.lower() == "q":
        return "quit"
    if not text:
        draft = entry.get("draft")
        if isinstance(draft, dict) and _truth_problems({"kind": entry.get("kind"), "truth": draft}) is None:
            entry["truth"], entry["confirmed"] = dict(draft), True
            return "next"
        return "again"
    try:
        entry["truth"] = truth_from_text(str(entry.get("kind")), text)
    except ValueError:
        return "again"
    entry["confirmed"] = True
    return "next"


def draft_text(entry: dict) -> str:
    draft = entry.get("draft")
    if not isinstance(draft, dict):
        return "no draft"
    if entry.get("kind") == "film":
        return f"{draft.get('title')} ({draft.get('year')})"
    number = draft.get("episode")
    tail = "no episode number" if number is None else f"E{int(number):02d}"
    return f"{draft.get('series')} S{int(draft.get('season') or 0):02d} {tail}"


def pattern_of(entry: dict) -> str:
    """The shape of a raw name, used to group failures without naming them."""
    name = str(entry["name"])
    text = _plain(name)
    if entry["kind"] == "episode":
        single = _SEASON_EPISODE.search(text) is not None
        if not single and (
            entry.get("inner") or _SEASON_ONLY.search(text) or _PACK_WORDS.search(text)
        ):
            return "season pack"
        if not single and _ABSOLUTE.search(text):
            return "absolute episode number"
        return "flat episode file"
    if name.lstrip().startswith("["):
        return "bracket group tag"
    label = (entry.get("truth") if isinstance(entry.get("truth"), dict) else None) or draft_label(
        name, "film"
    )
    title = str((label or {}).get("title") or "")
    if re.search(r"\b(?:19|20)\d{2}\b", title):
        return "year in title"
    return "plain"


def parse_queries(text: str) -> list[tuple[str, str]]:
    """Lines `film: <query>` or `serie: <query>`; blank lines and # comments are ignored."""
    queries: list[tuple[str, str]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        kind, sep, query = stripped.partition(":")
        kind, query = kind.strip().lower(), query.strip()
        if not sep or kind not in ("film", "serie"):
            raise Fail("queries", f"line {number}: start with film: or serie:")
        if not query:
            raise Fail("queries", f"line {number}: the query is empty")
        queries.append((kind, query))
    return queries


# --- the committed report -------------------------------------------------------------


def _failure_classes(rows: list[dict]) -> list[tuple[str, int, int]]:
    out = []
    for pattern in PATTERNS:
        group = [r for r in rows if str(r.get("pattern") or "plain") == pattern]
        unidentified = sum(1 for r in group if r.get("result") == "unidentified")
        wrong = sum(1 for r in group if r.get("result") == "wrong title")
        if unidentified or wrong:
            out.append((pattern, unidentified, wrong))
    return out


def _real_section(real: dict | None) -> list[str]:
    if not real:
        return ["Not run yet."]
    counts = verdict(real["rows"])
    lines = [
        "| Result | Names |",
        "| --- | --- |",
        f"| identified | {counts['identified']} |",
        f"| unidentified | {counts['unidentified']} |",
        f"| wrong title | {counts['wrong']} |",
        f"| total | {counts['total']} |",
        "",
        f"Identified: {counts['percent']} %",
        "",
        f"Meets the D-92 bar: {'yes' if counts['meets_bar'] else 'no'}",
        "",
    ]
    classes = _failure_classes(real["rows"])
    if classes:
        lines += ["Failure classes (counts only):", ""]
        lines += ["| Shape of the name | Unidentified | Wrong title |", "| --- | --- | --- |"]
        lines += [f"| {pattern} | {un} | {wrong} |" for pattern, un, wrong in classes]
    else:
        lines.append("No failures.")
    return lines


def _sample_section(sample: dict | None) -> list[str]:
    if not sample:
        return ["Not run yet."]
    return [result_line(verdict(sample["rows"])), "", render_table(sample["rows"]).rstrip("\n")]


def render_report(real: dict | None, sample: dict | None, decision: str | None = None) -> str:
    """docs/naming-scan.md. The real corpus contributes counts and failure classes only."""
    intro = ["# Naming scan test (NAME-01)", ""]
    for paragraph in INTRO_PARAGRAPHS:
        intro += [paragraph, ""]
    lines = intro + ["## Real corpus", ""] + _real_section(real) + [""]
    lines += ["## Synthetic sample", ""] + _sample_section(sample) + [""]
    lines += ["## Decision", "", (decision or "").strip() or PENDING_DECISION, ""]
    return "\n".join(lines)


def _published() -> tuple[set[str], set[str]]:
    """Names and normalised titles of the committed synthetic sample (already public)."""
    try:
        sample = json.loads(SAMPLE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set(), set()
    names = {str(e.get("name")) for e in sample if isinstance(e, dict)}
    titles = set()
    for e in sample:
        truth = e.get("truth") if isinstance(e, dict) else None
        if isinstance(truth, dict):
            titles.add(normalise(str(truth.get("title") or truth.get("series") or "")))
    return names, titles


def validate_report(text: str, corpus: list[dict] | None) -> list[str]:
    """Missing headings, and any real corpus name (raw, folded, or a long draft title) in the
    text. Messages never repeat a name."""
    lines = set(text.splitlines())
    problems = [f"heading missing: {heading}" for heading in HEADINGS if heading not in lines]
    published_names, published_titles = _published()
    folded = f" {normalise(text)} "
    for index, entry in enumerate(corpus or []):
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            continue
        name = entry["name"]
        if name in published_names:
            continue
        needles = [normalise(name)]
        draft = draft_label(name, str(entry.get("kind")))
        title = normalise(str((draft or {}).get("title") or (draft or {}).get("series") or ""))
        if len(title) >= MIN_TITLE_CHARS and title not in published_titles:
            needles.append(title)
        leaked = name in text or any(n and f" {n} " in folded for n in needles)
        if leaked:
            problems.append(f"entry {index}: a real name appears in the report")
    return problems


# --- files ----------------------------------------------------------------------------


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    part.write_text(text, encoding="utf-8")
    os.chmod(part, 0o644)
    os.replace(part, path)


def load_entries(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise Fail("corpus", "the corpus file is missing or is not valid JSON") from None


def _inside(path: Path, folder: Path) -> bool:
    resolved, base = path.resolve(), folder.resolve()
    return resolved != base and base in resolved.parents


def _clean_folder(folder: Path) -> None:
    if folder.is_symlink():
        raise Fail("corpus", f"{folder.name} is a symlink; not touched")
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)


def build_raw(entries: list[dict], raw: Path | None = None) -> int:
    """Rebuild only Raw/Movies and Raw/TV from the corpus, one 1-second clip per name."""
    raw = RAW if raw is None else raw
    if not _inside(raw, SCRATCH):
        raise Fail("corpus", "the raw folder is outside the scratch folder; nothing written")
    targets = []
    for entry in entries:
        target = raw / layout(entry)
        if not _inside(target, raw):
            raise Fail("corpus", "a clip path would leave the raw folder; nothing written")
        targets.append(target)
    for sub in ("Movies", "TV"):
        _clean_folder(raw / sub)
    for target in targets:
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            mc.ffmpeg(
                "-f", "lavfi", "-i", "color=c=0x305070:s=160x90:r=25:d=1",
                "-t", "1", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                "-an", str(target),
                timeout=120,
            )
        except subprocess.CalledProcessError:
            raise Fail("ffmpeg", "a clip could not be written") from None
        except subprocess.TimeoutExpired:
            raise Fail("ffmpeg", "a clip took too long") from None
        os.chmod(target, 0o644)
    for folder, dirs, _ in os.walk(raw):
        os.chmod(folder, 0o755)
        for sub in dirs:
            os.chmod(Path(folder) / sub, 0o755)
    return len(targets)


# --- Jellyfin -------------------------------------------------------------------------


def ensure_raw_libraries(api: object) -> dict:
    """The two admin-only libraries. Household access is never touched."""
    return {
        "movies": js.ensure_library(api, RAW_MOVIES, "movies", RAW_MOVIES_PATH, internet=True),
        "tv": js.ensure_library(api, RAW_TV, "tvshows", RAW_TV_PATH, internet=True),
    }


def _id(value: object) -> str:
    return str(value or "").replace("-", "").lower()


def collect(api: object, user_id: str, libraries: dict) -> tuple[dict[str, dict], dict[str, dict]]:
    """Movie and Episode items by container path, and the Series items by id."""
    fields = "ProviderIds,Path,ProductionYear"
    items: dict[str, dict] = {}
    for item in js.library_items(api, user_id, libraries["movies"], "Movie", fields):
        items[str(item.get("Path"))] = item
    for item in js.library_items(api, user_id, libraries["tv"], "Episode", fields):
        items[str(item.get("Path"))] = item
    series: dict[str, dict] = {}
    for item in js.library_items(api, user_id, libraries["tv"], "Series", "ProviderIds"):
        series[_id(item.get("Id"))] = item
    return items, series


def container_path(entry: dict) -> str:
    return f"{CONTAINER_RAW}/{layout(entry).as_posix()}"


def match(entries: list[dict], items: dict[str, dict]) -> list[dict | None]:
    return [items.get(container_path(entry)) for entry in entries]


def _signature(items: dict[str, dict], series: dict[str, dict]) -> str:
    rows = sorted(
        (path, item.get("Name"), bool(item.get("ProviderIds")), item.get("IndexNumber"))
        for path, item in items.items()
    )
    names = sorted((sid, s.get("Name"), bool(s.get("ProviderIds"))) for sid, s in series.items())
    return json.dumps([rows, names], default=str)


def settled_collect(
    api: object, user_id: str, libraries: dict, *, poll: float = SETTLE_POLL, rounds: int = SETTLE_ROUNDS
) -> tuple[dict[str, dict], dict[str, dict]]:
    """Metadata arrives a little after the scan task ends: read until two reads agree."""
    previous: str | None = None
    for _ in range(rounds):
        items, series = collect(api, user_id, libraries)
        current = _signature(items, series)
        if current == previous:
            return items, series
        previous = current
        time.sleep(poll)
    raise Fail("scan", "the Raw libraries kept changing; no table and no verdict written")


def build_rows(entries: list[dict], items: dict[str, dict], series: dict[str, dict]) -> list[dict]:
    rows = []
    for entry, item in zip(entries, match(entries, items), strict=True):
        linked = series.get(_id(item.get("SeriesId"))) if item else None
        rows.append(
            {
                "name": entry["name"],
                "kind": entry["kind"],
                "expected": expected_text(entry),
                "matched": matched_text(entry, item, linked),
                "result": classify(entry, item, linked),
                "pattern": pattern_of(entry),
            }
        )
    return rows


# --- run ------------------------------------------------------------------------------


def results_document(source: str, rows: list[dict]) -> dict:
    return {
        "source": source,
        "settled_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "verdict": verdict(rows),
        "rows": rows,
    }


def cmd_run(args: argparse.Namespace) -> int:
    corpus = Path(args.corpus)
    entries = load_entries(corpus)
    problems = validate_corpus(entries)
    if problems:
        raise Fail("corpus", "; ".join(problems))
    assert isinstance(entries, list)
    source = "sample" if corpus.resolve() == SAMPLE.resolve() else "real"

    count = build_raw(entries)
    print(f"OK raw-built ({count} clips)")
    api, user_id = js.admin_api(args.base)
    libraries = ensure_raw_libraries(api)
    print("OK raw-libraries")
    js.wait_for_scan(api, user_id)
    items, series = settled_collect(api, user_id, libraries)

    rows = build_rows(entries, items, series)
    document = results_document(source, rows)
    # The real files hold real runs only: a run of the synthetic sample must never replace the
    # evidence of the real corpus (WR-04).
    text = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    write_atomic(SAMPLE_RESULTS if source == "sample" else RESULTS, text)
    write_atomic(SAMPLE_TABLE if source == "sample" else TABLE, render_table(rows))
    print("OK scan-settled")
    counts = document["verdict"]
    print(result_line(counts))
    print(decision_line(counts))
    return 0


# --- capture and label ----------------------------------------------------------------


def _lenient_entries(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [e for e in data if isinstance(e, dict)] if isinstance(data, list) else []


def cmd_capture(args: argparse.Namespace) -> int:
    queries_path, out = Path(args.queries), Path(args.out)
    try:
        queries = parse_queries(queries_path.read_text(encoding="utf-8"))
    except OSError:
        raise Fail("queries", "the queries file is missing") from None
    if not queries:
        raise Fail("queries", "the queries file has no queries")
    if any(e.get("confirmed") for e in _lenient_entries(out)):
        raise Fail("capture", "the corpus already holds confirmed labels; move it away first")

    quiet = io.StringIO()  # smoke prints step lines; this script prints counts only
    films: list[str] = []
    episodes: list[str] = []
    try:
        with contextlib.redirect_stdout(quiet):
            probe = sm.login_probe(args.base)
        for number, (kind, query) in enumerate(queries, start=1):
            if number > 1:
                time.sleep(SEARCH_SPACING)
            with contextlib.redirect_stdout(quiet):
                rows = sm.search_flow(probe, query, kind, False)
            names = [str(r["name"]) for r in rows if isinstance(r.get("name"), str)]
            bucket = films if kind == "film" else episodes
            bucket.extend(n for n in names if n not in bucket)
            print(f"OK query {number} of {len(queries)}: {len(names)} names")
        probe.request("POST", "/api/logout")
    except sm.Fail as exc:
        raise Fail(exc.step, exc.reason) from None

    chosen = [("film", n) for n in films[: args.films]]
    chosen += [("episode", n) for n in episodes[: args.series]]
    if not chosen:
        raise Fail("capture", "no names captured")
    entries = [
        {
            "name": name,
            "kind": kind,
            "draft": draft_label(name, kind),
            "truth": None,
            "confirmed": False,
        }
        for kind, name in chosen
    ]
    write_atomic(out, json.dumps(entries, indent=2, ensure_ascii=False) + "\n")
    print(
        f"OK captured {len(entries)} names "
        f"({sum(1 for k, _ in chosen if k == 'film')} film, "
        f"{sum(1 for k, _ in chosen if k == 'episode')} episode) into {out}"
    )
    return 0


def cmd_label(args: argparse.Namespace) -> int:
    path = Path(args.corpus)
    entries = load_entries(path)
    if not isinstance(entries, list):
        raise Fail("corpus", "the corpus file is not a list")
    pending = [e for e in entries if isinstance(e, dict) and not e.get("confirmed")]
    print(f"{len(pending)} names to label (Enter = accept the draft, x = drop, q = save and stop)")
    for number, entry in enumerate(pending, start=1):
        while True:
            print(f"[{number}/{len(pending)}] {entry.get('name')}")
            print(f"  draft: {draft_text(entry)}")
            hint = "title|year" if entry.get("kind") == "film" else "series|season|episode"
            try:
                answer = input(f"  label ({hint}): ")
            except EOFError:
                answer = "q"
            action = apply_answer(entry, answer)
            if action != "again":
                break
            print("  not understood; try again")
        if action == "drop":
            entries = [e for e in entries if e is not entry]
        write_atomic(path, json.dumps(entries, indent=2, ensure_ascii=False) + "\n")
        if action == "quit":
            break
    left = sum(1 for e in entries if isinstance(e, dict) and not e.get("confirmed"))
    print(f"OK {len(entries)} names, {left} still unconfirmed")
    return 0


# --- report ---------------------------------------------------------------------------


def _read_results(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise Fail("results", "a results file is not valid JSON") from None
    if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
        raise Fail("results", "a results file has no rows")
    return data


def _corpus_for_check(real: dict | None) -> list[dict]:
    entries = _lenient_entries(CORPUS)
    entries += [{"name": r["name"], "kind": r.get("kind")} for r in (real or {}).get("rows", [])]
    return entries


def _section(text: str, heading: str, next_heading: str | None) -> str | None:
    """The body of one `## ` section of a report, or None when the heading is absent."""
    start = text.find(f"\n{heading}\n")
    if start < 0:
        return None
    start += len(heading) + 2
    end = text.find(f"\n{next_heading}\n", start) if next_heading else -1
    return text[start : end if end >= 0 else len(text)].strip()


def _existing_report(path: Path) -> tuple[bool, str | None]:
    """(the report already holds real counts, its Decision text unless it is the pending line)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False, None
    real = _section(text, "## Real corpus", "## Synthetic sample")
    decision = _section(text, "## Decision", None)
    return bool(real) and real != "Not run yet.", (None if decision == PENDING_DECISION else decision) or None


def cmd_report(args: argparse.Namespace) -> int:
    real = _read_results(Path(args.results))
    if real is not None and real.get("source") != "real":
        real = None  # an old results file written by a sample run
    sample = _read_results(Path(args.sample_results))
    out = Path(args.out)
    had_real, kept_decision = _existing_report(out)
    if real is None and had_real:
        raise Fail("report", "not written: the report holds real counts but there are no real results to rebuild them")
    # Rewriting the report must not wipe a recorded decision (WR-04).
    text = render_report(real, sample, args.decision if args.decision is not None else kept_decision)
    problems = validate_report(text, _corpus_for_check(real))
    if problems:
        raise Fail("report", "not written: " + "; ".join(problems))
    write_atomic(out, text)
    print(f"OK report written ({'real counts' if real else 'real corpus not run yet'})")
    return 0


def cmd_validate_report(args: argparse.Namespace) -> int:
    try:
        text = Path(args.doc).read_text(encoding="utf-8")
    except OSError:
        raise Fail("report", "the report file is missing") from None
    problems = validate_report(text, _lenient_entries(CORPUS))
    if problems:
        raise Fail("report", "; ".join(problems))
    print("OK report")
    return 0


# --- command line ---------------------------------------------------------------------


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="The naming scan test (NAME-01)")
    sub = parser.add_subparsers(dest="command", required=True)
    capture = sub.add_parser("capture", help="collect real torrent names from the portal search")
    capture.add_argument("--base", default="http://127.0.0.1", help="portal URL (Caddy)")
    capture.add_argument("--queries", default=str(QUERIES))
    capture.add_argument("--out", default=str(CORPUS))
    capture.add_argument("--films", type=int, default=20)
    capture.add_argument("--series", type=int, default=10)
    capture.set_defaults(func=cmd_capture)
    label = sub.add_parser("label", help="confirm or correct the truth label of each name")
    label.add_argument("--corpus", default=str(CORPUS))
    label.set_defaults(func=cmd_label)
    run = sub.add_parser("run", help="build clips, scan with Jellyfin, classify, print the verdict")
    run.add_argument("--corpus", default=str(CORPUS))
    run.add_argument("--base", default=js.DEFAULT_BASE, help="Jellyfin URL through Caddy")
    run.set_defaults(func=cmd_run)
    report = sub.add_parser("report", help="write docs/naming-scan.md (no real names)")
    report.add_argument("--results", default=str(RESULTS))
    report.add_argument("--sample-results", default=str(SAMPLE_RESULTS))
    report.add_argument("--out", default=str(REPORT))
    report.add_argument("--decision", default=None, help="the decision text (plan 03-09)")
    report.set_defaults(func=cmd_report)
    check = sub.add_parser("validate-report", help="check the committed report for real names")
    check.add_argument("--doc", default=str(REPORT))
    check.set_defaults(func=cmd_validate_report)
    args = parser.parse_args(argv[1:])
    try:
        return args.func(args)
    except Fail as exc:
        print(f"FAIL {exc.step}: {exc.reason}")
        return 1
    except mc.MissingFfmpeg:
        print("FAIL ffmpeg: host ffmpeg missing")
        return 3
    except (urllib.error.URLError, OSError) as exc:
        print(f"FAIL connect: {type(exc).__name__}")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
