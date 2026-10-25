#!/usr/bin/env python3
"""The naming scan test (NAME-01): can stock Jellyfin identify raw torrent names on its own?

Usage:
    python3 scripts/name_scan.py run [--corpus PATH] [--base URL]

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

Privacy (D-101): the real corpus, the results and the per-name table live in the gitignored
jellyfin/name-scan folder. `run` prints counts and step lines only, never a name. The synthetic
sample (scripts/name_scan_sample.json) uses open-licensed titles only and may be published.

Standard library only; ffmpeg runs by argument list; Raw Movies and Raw TV never get household
access and only scratch/Raw/Movies and scratch/Raw/TV are rebuilt.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
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

Fail = js.Fail
ROOT = Path(js.ROOT)
SCRATCH = Path(mc.SCRATCH)
WORK = Path(js.JELLYFIN_DIR) / "name-scan"
CORPUS = WORK / "corpus.json"
QUERIES = WORK / "queries.txt"
RESULTS = WORK / "results.json"
SAMPLE_RESULTS = WORK / "sample-results.json"
TABLE = WORK / "table.md"
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


def layout(entry: dict) -> Path:
    """Where the Phase 2.1 hand-off would link this torrent, relative to the Raw folder."""
    root = "Movies" if entry["kind"] == "film" else "TV"
    name = str(entry["name"])
    if name.lower().endswith(VIDEO_EXTS):  # a single-file torrent: the file in the library root
        return Path(root) / safe_component(name)
    inner = entry.get("inner")
    if inner:
        file_name = safe_component(str(inner))
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
    write_atomic(RESULTS, json.dumps(document, indent=2, ensure_ascii=False) + "\n")
    if source == "sample":
        write_atomic(SAMPLE_RESULTS, json.dumps(document, indent=2, ensure_ascii=False) + "\n")
    write_atomic(TABLE, render_table(rows))
    print("OK scan-settled")
    counts = document["verdict"]
    print(result_line(counts))
    print(decision_line(counts))
    return 0


# --- command line ---------------------------------------------------------------------


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="The naming scan test (NAME-01)")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="build clips, scan with Jellyfin, classify, print the verdict")
    run.add_argument("--corpus", default=str(CORPUS))
    run.add_argument("--base", default=js.DEFAULT_BASE, help="Jellyfin URL through Caddy")
    run.set_defaults(func=cmd_run)
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
