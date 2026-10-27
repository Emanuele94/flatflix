#!/usr/bin/env python3
"""The measuring half of the TV gate: turn each play of a Compat clip into a matrix row.

Usage:
    python3 scripts/tv_gate.py watch [--no-prompt] [--base URL] [--results PATH]
    python3 scripts/tv_gate.py selftest --row ID (--profile remux|audio|video|direct | --all)
                                        [--base URL] [--out PATH]
    python3 scripts/tv_gate.py render [--results PATH] [--out PATH | --doc PATH]
    python3 scripts/tv_gate.py validate [--doc PATH]
    python3 scripts/tv_gate.py verdict [--results PATH]
    python3 scripts/tv_gate.py forget ID [--results PATH]

`watch` is the TV session (D-88): sign in as the device "flatflix-tv-gate", poll Jellyfin's Sessions
API every second and, each time a Compat clip stops playing, print `<ID> <Method> (<reasons>)`, ask
once whether picture and sound were fine and save at once to jellyfin/tv-gate/results.json. Clips
played by our own clients (Client starts with "flatflix-") and items with no row id are ignored.
Ctrl-C saves and exits 0. A row keeps all its plays: its Method is the worst of them and its answer
is the last one given; `forget ID` drops a row for a re-test.

`render --doc PATH` puts the matrix of the results between the markers of docs/tv-compatibility.md
(the rest of the document is written by hand; with no results every row reads `not tested`, and
rendering twice gives the same bytes). `validate` checks that document: the five group headings and
the three sections in order, one table of the nine UI-SPEC columns per group with one row per
catalogue clip, only the allowed Method and answer values, no dotted IPv4 address, MAC address or
serial/ESN/device-id value, and the verdict block rules; it prints OK or each violation (exit 1).

`verdict` prints the candidate headline from the results: CANDIDATE GO, CANDIDATE NO-GO or GO with
conditions (with the failing rows), or INCOMPLETE (exit 1) while a gating row is not tested, then
the 1080p transcoding line. The human chooses the final headline (D-87).

`selftest` drives real playbacks of a Compat clip through Jellyfin's own streaming engine (a
stand-in client that signs in as the device "flatflix-tv-gate-selftest") and prints
`OK selftest <ID> <profile> -> <Method>` or a FAIL line when the Method differs from the one the
profile must give: remux -> Remux, audio -> Audio transcode, video -> Video transcode, direct ->
Direct play (`--all` runs the four in turn). Its results go to jellyfin/tv-gate/selftest.json
(replaced on every run) and never to results.json.

The Method comes from server evidence (RESEARCH Pattern 5): the ffmpeg log type of that item
(Transcode -> Video transcode, DirectStream -> Audio transcode, Remux -> Remux), then the last
non-null TranscodingInfo of the play session, and Direct play only when no ffmpeg job ran and the
session reports DirectPlay. When the log and the session disagree the row says so in its Reason.
The client-reported PlayMethod is never trusted when the server ran an ffmpeg job.

Privacy (D-89, T-03-13, T-03-14): the helper stores Client and ApplicationVersion only, never a
device id, a device name, an address, a user name or any URL (stream URLs carry access tokens).
Results live under the gitignored jellyfin/ folder. Standard library only.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
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


js = _load("flatflix_tg_run_jellyfin_setup", "jellyfin_setup.py")
mc = _load("flatflix_tg_run_make_compat_clips", "make_compat_clips.py")

Fail = js.Fail
ROOT = mc.ROOT
JELLYFIN_DIR = js.JELLYFIN_DIR

RESULTS = JELLYFIN_DIR / "tv-gate" / "results.json"
SELFTEST_RESULTS = JELLYFIN_DIR / "tv-gate" / "selftest.json"
MANIFEST = mc.MANIFEST
LOG_DIR = JELLYFIN_DIR / "config" / "log"
DOC = ROOT / "docs" / "tv-compatibility.md"

METHODS = ("Direct play", "Remux", "Audio transcode", "Video transcode")
NOT_TESTED = "not tested"
MATRIX_BEGIN = "<!-- tv-gate:matrix:begin -->"
MATRIX_END = "<!-- tv-gate:matrix:end -->"
HEADER = (
    "| ID | Container | Video | Audio | Subtitles | Resolution | Method | Reason "
    "| Picture and sound OK |"
)
SEPARATOR = "| " + " | ".join(["---"] * 9) + " |"
DEVICE = "flatflix-tv-gate"
SELFTEST_DEVICE = "flatflix-tv-gate-selftest"
INTERNAL_PREFIX = "flatflix-"

LOG_METHOD = {"Remux": "Remux", "DirectStream": "Audio transcode", "Transcode": "Video transcode"}
EXPECTED_METHOD = {
    "remux": "Remux",
    "audio": "Audio transcode",
    "video": "Video transcode",
    "direct": "Direct play",
}
SAFE_TRANSCODING_KEYS = (
    "IsVideoDirect",
    "IsAudioDirect",
    "VideoCodec",
    "AudioCodec",
    "Container",
    "Width",
    "Height",
    "Bitrate",
)
ENTRY_KEYS = (
    "row",
    "item_id",
    "start",
    "end",
    "transcoding",
    "reasons",
    "play_method",
    "subtitles_on",
    "client",
    "version",
    "log_types",
    "method",
    "flag",
    "ok",
    "profile",
)
PENDING_LINE = "**Pending**: the real-TV session has not run yet."
PHASE5_LINE = "Phase 5 builds its device profile from the rows marked Direct play or Remux above."
TRANSCODING_PREFIX = "1080p content needed video transcoding: "
VERSION_PREFIX = "Jellyfin version tested: "
MITIGATIONS = ("re-encode", "plan b stick", "stronger hardware")
SECTION_HEADINGS = ("Address check", "Streaming bitrate", "Verdict")
FIRMWARE = "V0003.09.60A.Q0707"
IPV4 = re.compile(r"(?<![\w.])\d{1,3}(?:\.\d{1,3}){3}(?!\w|\.\d)")
MAC = re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{2}([:-])[0-9A-Fa-f]{2}(?:\1[0-9A-Fa-f]{2}){4}(?![0-9A-Fa-f])")
DEVICE_VALUE = re.compile(
    r"\b(serial(?:\s+number)?|esn|device[\s_-]*id|mac(?:\s+address)?)\b\s*[:=|]\s*\S", re.IGNORECASE
)
HEADLINE = re.compile(r"^\*\*(Pending|GO with conditions|GO|NO-GO)\*\*")
SEPARATOR_ROW = re.compile(r"^\|(\s*:?-+:?\s*\|){9}$")
SUBTITLE_GROUPS = ("subs", "pgs")  # rows whose clip is only a test with its subtitles switched on
POLL_SECONDS = 1.0
PRE_PLAY_SLACK = 30.0  # ffmpeg starts before the session lists the item
MAX_POLL_ERRORS = 10
SELFTEST_SECONDS = 10
READ_LIMIT = 2_000_000
SELFTEST_BITRATE = 120_000_000


# --- the pure parts -------------------------------------------------------------------


def row_id_of(name: object) -> str | None:
    """The catalogue row id an item name starts with (`A01 MKV H264 AAC` -> `A01`), else None."""
    if not isinstance(name, str):
        return None
    token = name.split(maxsplit=1)[0] if name.strip() else ""
    return token if token in mc.ROW_IDS else None


def log_type_of(filename: str) -> str | None:
    """`Remux`, `DirectStream` or `Transcode` for an `FFmpeg.<Type>-...` log name, else None."""
    if not filename.startswith("FFmpeg."):
        return None
    kind = filename[len("FFmpeg.") :].split("-", 1)[0]
    return kind if kind in LOG_METHOD else None


def worst(methods: list[str] | tuple[str, ...]) -> str:
    """Video transcode > Audio transcode > Remux > Direct play; `not tested` only when nothing else."""
    known = [m for m in methods if m in METHODS]
    return max(known, key=METHODS.index) if known else NOT_TESTED


def _info_method(info: dict | None) -> str | None:
    if not info or "IsVideoDirect" not in info:
        return None
    if not info["IsVideoDirect"]:
        return "Video transcode"
    return "Remux" if info.get("IsAudioDirect") else "Audio transcode"


def _log_method(log_types: list[str]) -> str:
    return worst([LOG_METHOD[t] for t in log_types if t in LOG_METHOD])


def classify(play_method: str | None, info: dict | None, log_types: list[str]) -> str:
    """RESEARCH Pattern 5: the server's evidence first, the client's PlayMethod only for Direct play."""
    from_logs = _log_method(log_types)
    if from_logs != NOT_TESTED:
        return from_logs
    from_info = _info_method(info)
    if from_info:
        return from_info
    return "Direct play" if play_method == "DirectPlay" else NOT_TESTED


def signals_disagree(log_types: list[str], info: dict | None) -> bool:
    """True when the ffmpeg log and the session's TranscodingInfo name different methods."""
    from_info = _info_method(info)
    from_logs = _log_method(log_types)
    return bool(from_info) and from_logs != NOT_TESTED and from_info != from_logs


def disagreement_note(log_types: list[str], info: dict | None) -> str:
    kind = max((t for t in log_types if t in LOG_METHOD), key=lambda t: METHODS.index(LOG_METHOD[t]))
    direct = (info or {}).get("IsVideoDirect")
    return f"[signals disagree: log {kind}, session IsVideoDirect={direct}]"


def finalize(entry: dict, log_types: list[str]) -> dict:
    """Add the server evidence to a finished play: log types, Method, and the disagreement flag."""
    info = entry.get("transcoding")
    entry["log_types"] = list(log_types)
    entry["method"] = classify(entry.get("play_method"), info, log_types)
    entry["flag"] = disagreement_note(log_types, info) if signals_disagree(log_types, info) else ""
    entry.setdefault("ok", None)
    return entry


def clean_entry(entry: dict) -> dict:
    """Keep only the known keys; the TranscodingInfo keeps only its codec and direct flags; a value
    that is a URL is dropped (T-03-13, T-03-14)."""
    out: dict = {}
    for key in ENTRY_KEYS:
        if key not in entry:
            continue
        value = entry[key]
        if key == "transcoding" and isinstance(value, dict):
            value = {k: value[k] for k in SAFE_TRANSCODING_KEYS if k in value}
        if isinstance(value, str) and value.lower().startswith(("http:", "https:")):
            continue
        out[key] = value
    return out


class Tracker:
    """Follows the play sessions of Compat clips across polls of GET /Sessions.

    A play session is a Jellyfin session id plus the item it is playing. TranscodingInfo is present
    only while ffmpeg runs, so the last non-null sample is kept. Sessions of our own clients
    (Client starts with `ignore_prefix`) are skipped when a prefix is set."""

    def __init__(self, ignore_prefix: str | None = INTERNAL_PREFIX) -> None:
        self.ignore_prefix = ignore_prefix
        self.active: dict[tuple[str, str], dict] = {}

    def observe(self, sessions: list[dict], now: float) -> list[dict]:
        seen: set[tuple[str, str]] = set()
        for s in sessions:
            item = s.get("NowPlayingItem") or {}
            row = row_id_of(item.get("Name"))
            client = str(s.get("Client") or "")
            if row is None or not item.get("Id"):
                continue
            if self.ignore_prefix and client.startswith(self.ignore_prefix):
                continue
            key = (str(s.get("Id") or ""), str(item["Id"]))
            seen.add(key)
            entry = self.active.setdefault(
                key,
                {
                    "row": row,
                    "item_id": str(item["Id"]).replace("-", "").lower(),
                    "start": now,
                    "transcoding": None,
                    "reasons": [],
                    "play_method": None,
                    "subtitles_on": False,
                    "client": client,
                    "version": str(s.get("ApplicationVersion") or ""),
                },
            )
            state = s.get("PlayState") or {}
            if state.get("PlayMethod"):
                entry["play_method"] = state["PlayMethod"]
            index = state.get("SubtitleStreamIndex")
            if isinstance(index, int) and index >= 0:
                entry["subtitles_on"] = True
            info = s.get("TranscodingInfo")
            if info:
                entry["transcoding"] = {k: info[k] for k in SAFE_TRANSCODING_KEYS if k in info}
                for reason in info.get("TranscodeReasons") or []:
                    if reason not in entry["reasons"]:
                        entry["reasons"].append(reason)
        return [self._close(key, now) for key in list(self.active) if key not in seen]

    def _close(self, key: tuple[str, str], now: float) -> dict:
        entry = self.active.pop(key)
        entry["end"] = now
        return entry

    def finish_all(self) -> list[dict]:
        now = time.time()
        return [self._close(key, now) for key in list(self.active)]


class ResultStore:
    """The play results of one session file: {row id: [session entries]}; saved atomically."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.data: dict[str, list[dict]] = {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raw = {}  # no file yet: a first session starts empty
        except ValueError:
            # A hand edit or a half-written file must not read as "no results": the next save would
            # replace it and lose every play recorded on the real TV (WR-03).
            raise Fail("results", f"{self.path.name} is not valid JSON: fix it or move it away") from None
        rows = raw.get("rows") if isinstance(raw, dict) else None
        if isinstance(rows, dict):
            self.data = {k: [e for e in v if isinstance(e, dict)] for k, v in rows.items() if isinstance(v, list)}

    def add(self, row_id: str, entry: dict) -> None:
        self.data.setdefault(row_id, []).append(clean_entry(entry))

    def forget(self, row_id: str) -> bool:
        return self.data.pop(row_id, None) is not None

    def rows(self) -> dict[str, list[dict]]:
        return {k: list(v) for k, v in self.data.items()}

    def save(self) -> None:
        """Write beside the old file and replace it, so a failed write leaves the old one intact."""
        text = json.dumps({"rows": self.data}, indent=2, ensure_ascii=False) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp = tempfile.mkstemp(dir=self.path.parent, prefix=".results-", suffix=".tmp")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(text)
            os.chmod(temp, 0o644)
            os.replace(temp, self.path)
        except BaseException:
            try:
                os.unlink(temp)
            except FileNotFoundError:
                pass
            raise


def _cell(text: str) -> str:
    return " ".join(str(text).replace("|", "/").split()) or "-"


def summarise(row, sessions: list[dict], manifest_entry: dict | None) -> tuple[str, str, str]:
    """(Method, Reason, Picture and sound OK) of one catalogue row, all non-empty strings."""
    na = (manifest_entry or {}).get("na")
    if na:
        return str(na), "-", NOT_TESTED
    note = row.note
    played = list(sessions)
    if row.group in SUBTITLE_GROUPS and played:
        played = [s for s in played if s.get("subtitles_on")]
        if not played:
            return NOT_TESTED, "subtitles were off", NOT_TESTED
    if not played:
        return NOT_TESTED, _cell(note), NOT_TESTED
    method = worst([s.get("method", NOT_TESTED) for s in played])
    reasons: list[str] = []
    flags: list[str] = []
    for s in played:
        reasons += [r for r in s.get("reasons") or [] if r not in reasons]
        if s.get("flag") and s["flag"] not in flags:
            flags.append(s["flag"])
    parts = [", ".join(reasons) if reasons else "-", *flags]
    reason = " ".join(parts)
    if note:
        reason += f" — {note}"
    answers = [s["ok"] for s in played if s.get("ok") in ("yes", "no")]
    return method, _cell(reason), answers[-1] if answers else NOT_TESTED


def render_matrix(results: dict, manifest: dict) -> str:
    """The five group sections, each one table of the nine UI-SPEC columns, in catalogue order.

    Nothing here depends on the clock or on the order the clips were played in."""
    sections: list[str] = []
    for key, heading, _ in mc.GROUPS:
        lines = [f"## {heading}", "", HEADER, SEPARATOR]
        group_rows = [r for r in mc.CATALOGUE if r.group == key]
        for r in group_rows:
            method, reason, ok = summarise(r, results.get(r.id) or [], manifest.get(r.id))
            cells = [r.id, r.container, r.video, r.audio, r.subtitles, r.resolution, method, reason, ok]
            lines.append("| " + " | ".join(_cell(c) for c in cells) + " |")
        if key == "pgs":
            burned = [
                r for r in group_rows
                if summarise(r, results.get(r.id) or [], manifest.get(r.id))[0] == "Video transcode"
            ]
            tested = any(results.get(r.id) for r in group_rows)
            lines += ["", f"burn-in forced: {('yes' if burned else 'no') if tested else NOT_TESTED}"]
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


def verdict_of(results: dict, manifest: dict) -> tuple[str, list[str]]:
    """The candidate outcome from the two gating groups only (D-85, D-86, D-99).

    ("GO", []) when every gating row is Direct play, Remux or Audio transcode answered `yes`;
    ("INCOMPLETE", ids) while a gating row is not tested or has no answer;
    ("NO-GO-OR-CONDITIONS", ids) when a row ended in Video transcode or was answered `no`.
    A gating row marked n/a and every information row never change the outcome."""
    missing: list[str] = []
    failing: list[str] = []
    for r in mc.CATALOGUE:
        if not r.gating:
            continue
        method, _, ok = summarise(r, results.get(r.id) or [], manifest.get(r.id))
        if method.startswith("n/a"):
            continue
        if method == "Video transcode" or ok == "no":
            failing.append(r.id)
        elif method == NOT_TESTED or ok == NOT_TESTED:
            missing.append(r.id)
    if missing:
        return "INCOMPLETE", missing
    if failing:
        return "NO-GO-OR-CONDITIONS", failing
    return "GO", []


def transcoding_line(results: dict) -> str:
    """The roadmap's 1080p line: which 1080p rows needed video transcoding."""
    rows = [
        r.id
        for r in mc.CATALOGUE
        if r.resolution == "1080p" and summarise(r, results.get(r.id) or [], None)[0] == "Video transcode"
    ]
    return "1080p content needed video transcoding: " + ("for rows " + ", ".join(rows) if rows else "never")


def verdict_lines(results: dict, manifest: dict) -> list[str]:
    headline, ids = verdict_of(results, manifest)
    if headline == "GO":
        first = "CANDIDATE GO"
    elif headline == "INCOMPLETE":
        first = "INCOMPLETE rows not tested: " + ", ".join(ids)
    else:
        first = "CANDIDATE NO-GO or GO with conditions; failing rows: " + ", ".join(ids)
    return [first, transcoding_line(results)]


def replace_matrix(doc_text: str, matrix: str) -> str:
    """Put the matrix between the markers; exactly one begin and one end marker, else ValueError."""
    if doc_text.count(MATRIX_BEGIN) != 1 or doc_text.count(MATRIX_END) != 1:
        raise ValueError("the document needs exactly one matrix begin marker and one end marker")
    begin = doc_text.index(MATRIX_BEGIN)
    end = doc_text.index(MATRIX_END)
    if end < begin:
        raise ValueError("the matrix end marker comes before the begin marker")
    return doc_text[: begin + len(MATRIX_BEGIN)] + "\n\n" + matrix + "\n\n" + doc_text[end:]


# --- the committed document --------------------------------------------------------------

CLIP_COLUMNS = (("ID", "id"), ("Container", "container"), ("Video", "video"), ("Audio", "audio"),
                ("Subtitles", "subtitles"), ("Resolution", "resolution"))


def _split_cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _method_ok(value: str) -> bool:
    return value in METHODS or value == NOT_TESTED or value.startswith("n/a \u2014 ")


def _check_group(lines: list[str], key: str, heading: str, manifest: dict, parsed: dict) -> list[str]:
    """Problems of one group's section: exactly one table of the right shape and rows."""
    problems: list[str] = []
    blocks: list[list[str]] = []
    previous_was_table = False
    for line in lines:
        is_table = line.startswith("|")
        if is_table and not previous_was_table:
            blocks.append([])
        if is_table:
            blocks[-1].append(line)
        previous_was_table = is_table
    if len(blocks) != 1:
        return [f"{heading}: expected one table, found {len(blocks)}"]
    block = blocks[0]
    if block[0] != HEADER:
        problems.append(f"{heading}: the header row is not the nine UI-SPEC columns")
    if len(block) < 2 or not SEPARATOR_ROW.match(block[1]):
        problems.append(f"{heading}: the header is not followed by a separator row")
    rows = block[2:]
    wanted = [r for r in mc.CATALOGUE if r.group == key]
    got_ids = [_split_cells(line)[0] for line in rows]
    for r in wanted:
        if r.id not in got_ids:
            problems.append(f"{heading}: row {r.id} is missing")
    for rid in got_ids:
        if rid not in [r.id for r in wanted]:
            problems.append(f"{heading}: unexpected row {rid}")
    if sorted(got_ids) == sorted(r.id for r in wanted) and got_ids != [r.id for r in wanted]:
        problems.append(f"{heading}: the rows are not in catalogue order")
    by_id = {r.id: r for r in wanted}
    for line in rows:
        cells = _split_cells(line)
        rid = cells[0]
        if len(cells) != 9:
            problems.append(f"row {rid}: {len(cells)} cells instead of 9")
            continue
        for index, name in enumerate(HEADER.strip("|").split("|")):
            if not cells[index]:
                problems.append(f"row {rid}: the {name.strip()} cell is empty")
        row = by_id.get(rid)
        if row is not None:
            for index, (name, attr) in enumerate(CLIP_COLUMNS):
                if cells[index] != getattr(row, attr):
                    problems.append(f"row {rid}: the {name} cell differs from the catalogue")
        if cells[6] and not _method_ok(cells[6]):
            problems.append(f"row {rid}: Method {cells[6]!r} is not one of the four values, not tested or n/a")
        if cells[8] and cells[8] not in ("yes", "no", NOT_TESTED):
            problems.append(f"row {rid}: Picture and sound OK must be yes, no or not tested")
        expected_na = (manifest.get(rid) or {}).get("na")
        if expected_na and cells[6] != expected_na:
            problems.append(f"row {rid}: the manifest says {expected_na!r} but Method differs")
        parsed[rid] = cells
    return problems


def _check_verdict(verdict_lines_: list[str], parsed: dict) -> list[str]:
    problems: list[str] = []
    first = next((ln.strip() for ln in verdict_lines_ if ln.strip()), "")
    match = HEADLINE.match(first)
    if not match:
        return ["Verdict: the first line must be **Pending**, **GO**, **GO with conditions** or **NO-GO**"]
    headline = match.group(1)
    if headline == "Pending":
        return [] if first == PENDING_LINE else [f"Verdict: the pending line must read: {PENDING_LINE}"]
    gating = [r for r in mc.CATALOGUE if r.gating and r.id in parsed and not parsed[r.id][6].startswith("n/a")]
    for r in gating:
        if NOT_TESTED in (parsed[r.id][6], parsed[r.id][8]):
            problems.append(f"Verdict: gating row {r.id} reads not tested but a headline is set")
    body = [ln.strip() for ln in verdict_lines_]
    video = [r.id for r in mc.CATALOGUE if r.id in parsed and r.resolution == "1080p" and parsed[r.id][6] == "Video transcode"]
    expected = TRANSCODING_PREFIX + ("for rows " + ", ".join(video) if video else "never")
    if expected not in body:
        problems.append(f"Verdict: the line must read: {expected}")
    if not any(ln.startswith(VERSION_PREFIX) and len(ln) > len(VERSION_PREFIX) for ln in body):
        problems.append(f"Verdict: a line starting {VERSION_PREFIX!r} and naming the version is missing")
    if headline == "GO":
        if PHASE5_LINE not in body:
            problems.append(f"Verdict: GO needs the line: {PHASE5_LINE}")
        for r in gating:
            if parsed[r.id][6] == "Video transcode" or parsed[r.id][8] == "no":
                problems.append(f"Verdict: GO but gating row {r.id} failed")
    elif headline == "NO-GO":
        lines = [ln for ln in body if ln.startswith("Mitigation chosen:")]
        if not any(any(m in ln.lower() for m in MITIGATIONS) for ln in lines):
            problems.append("Verdict: NO-GO needs 'Mitigation chosen:' naming re-encode, plan B stick or stronger hardware")
    else:
        bullets = [ln for ln in body if ln.startswith(("- ", "* "))]
        if not any(any(re.search(rf"\b{rid}\b", ln) for rid in mc.ROW_IDS) for ln in bullets):
            problems.append("Verdict: GO with conditions needs a bullet naming a row id")
        lines = [ln for ln in body if ln.startswith("Mitigation for the rest:")]
        if not any(any(m in ln.lower() for m in MITIGATIONS) for ln in lines):
            problems.append("Verdict: GO with conditions needs 'Mitigation for the rest:' naming re-encode, plan B stick or stronger hardware")
    return problems


def validate_doc(text: str, manifest: dict | None = None) -> list[str]:
    """Every way `text` breaks the layout, vocabulary or privacy rule of docs/tv-compatibility.md."""
    manifest = manifest or {}
    lines = text.splitlines()
    problems: list[str] = []
    if [ln for ln in lines if ln.startswith("# ")] != ["# TV compatibility"]:
        problems.append("the document must have exactly one H1: '# TV compatibility'")
    headings = [(n, ln[3:]) for n, ln in enumerate(lines) if ln.startswith("## ")]
    wanted = [h for _, h, _ in mc.GROUPS] + list(SECTION_HEADINGS)
    if [h for _, h in headings] != wanted:
        problems.append("the H2 headings must be, in order: " + "; ".join(wanted))
    if text.count(MATRIX_BEGIN) != 1 or text.count(MATRIX_END) != 1:
        problems.append("the matrix needs exactly one begin marker and one end marker")
    elif not text.index(MATRIX_BEGIN) < text.index(MATRIX_END):
        problems.append("the matrix end marker comes before the begin marker")
    else:
        inside = text[text.index(MATRIX_BEGIN) : text.index(MATRIX_END)]
        for _, heading in headings[: len(mc.GROUPS)]:
            if f"## {heading}\n" not in inside:
                problems.append(f"the group {heading!r} is outside the matrix markers")
    parsed: dict[str, list[str]] = {}
    if [h for _, h in headings] == wanted:
        bounds = [n for n, _ in headings] + [len(lines)]
        for index, (key, heading, _) in enumerate(mc.GROUPS):
            section = lines[bounds[index] + 1 : bounds[index + 1]]
            problems += _check_group(section, key, heading, manifest, parsed)
        verdict_section = lines[bounds[len(mc.GROUPS) + 2] + 1 :]
        problems += _check_verdict(verdict_section, parsed)
        opening = "\n".join(lines[: bounds[0]])
        if FIRMWARE not in opening:
            problems.append(f"the opening paragraph must name the firmware {FIRMWARE}")
    for number, line in enumerate(lines, start=1):
        if IPV4.search(line):
            problems.append(f"line {number}: a dotted IPv4 address (use <laptop-ip>)")
        if MAC.search(line):
            problems.append(f"line {number}: a MAC address")
        if DEVICE_VALUE.search(line):
            problems.append(f"line {number}: a serial number, ESN, device id or MAC with a value")
    return problems


# --- evidence from the server -----------------------------------------------------------


def log_types_for(item_id: str, since: float) -> list[str]:
    """The ffmpeg log types of an item's jobs (log file modified at or after `since`)."""
    wanted = item_id.replace("-", "").lower()
    found: list[str] = []
    try:
        names = sorted(os.listdir(LOG_DIR))
    except FileNotFoundError:
        return found
    for name in names:
        kind = log_type_of(name)
        if kind is None or wanted not in name.lower():
            continue
        try:
            if (LOG_DIR / name).stat().st_mtime >= since:
                found.append(kind)
        except FileNotFoundError:
            continue
    return found


def load_manifest() -> dict:
    return mc.read_manifest()


def sign_in(base: str, device: str):
    """Sign in as admin under its own device name; returns (client, user id)."""
    admin_password, _ = js.passwords()
    token, user_id = js.login(js.Api(base, device=device), js.ADMIN_USER, admin_password, step="admin-login")
    return js.Api(base, token, device=device), user_id


def current_sessions(api) -> list[dict]:
    payload = api.call("sessions", "GET", "/Sessions", query={"activeWithinSeconds": 30})
    return [s for s in payload if isinstance(s, dict)] if isinstance(payload, list) else []


def find_clip(api, user_id: str, row_id: str) -> dict:
    """The Compat library item whose name starts with the row id."""
    folder = js.find_library(api, js.COMPAT_LIBRARY)
    if folder is None:
        raise Fail("selftest", "the Compat library does not exist: run jellyfin_setup.py setup")
    for item in js.library_items(api, user_id, folder["ItemId"], "Video", ""):
        if row_id_of(item.get("Name")) == row_id:
            return item
    raise Fail("selftest", f"no Compat item for {row_id}: run jellyfin_setup.py setup")


def fetch(api, path: str, limit: int = READ_LIMIT) -> bytes:
    """GET a stream path (never printed), reading at most `limit` bytes. The access token goes in
    the Authorization header, so an ApiKey in the path is dropped first."""
    parts = urllib.parse.urlsplit(path)
    query = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True) if k != "ApiKey"]
    url = api.base + parts.path + ("?" + urllib.parse.urlencode(query) if query else "")
    request = urllib.request.Request(url, headers={"Authorization": js.auth_header(api.token, api.device)})
    try:
        with api.opener.open(request, timeout=js.TIMEOUT) as response:
            return response.read(limit)
    except urllib.error.HTTPError as exc:
        raise Fail("selftest", f"stream request answered HTTP {exc.code}") from None


def _first_uri(playlist: bytes) -> str:
    for line in playlist.decode("utf-8", "replace").splitlines():
        if line.strip() and not line.startswith("#"):
            return line.strip()
    raise Fail("selftest", "the playlist lists nothing")


DIRECT_PLAY_PROFILE = {"Container": "mkv", "Type": "Video", "VideoCodec": "h264", "AudioCodec": "aac"}


def profile_body(profile: str) -> dict:
    """The PlaybackInfo body for a selftest profile.

    remux, audio and video offer no direct play and one HLS transcoding profile; they differ in what
    may be copied. direct offers one direct-play profile (MKV, H.264, AAC)."""
    transcoding = {
        "Container": "ts",
        "Type": "Video",
        "Protocol": "hls",
        "Context": "Streaming",
        "VideoCodec": "h264,hevc",
        "AudioCodec": "aac,ac3,eac3,mp3",
        "MaxAudioChannels": "6",
        "MinSegments": 1,
        "BreakOnNonKeyFrames": True,
    }
    direct = profile == "direct"
    return {
        "DeviceProfile": {
            "Name": f"flatflix-selftest-{profile}",
            "MaxStreamingBitrate": SELFTEST_BITRATE,
            "DirectPlayProfiles": [dict(DIRECT_PLAY_PROFILE)] if direct else [],
            "TranscodingProfiles": [transcoding],
            "CodecProfiles": [],
            "SubtitleProfiles": [],
        },
        "MaxStreamingBitrate": SELFTEST_BITRATE,
        "EnableDirectPlay": direct,
        "EnableDirectStream": False,
        "AllowVideoStreamCopy": profile != "video",
        "AllowAudioStreamCopy": profile != "audio",
    }


def _start_stream(api, item_id: str, source: dict, play_session: str, profile: str) -> str:
    """Make the server start its job (or serve the file) and return the PlayMethod to report."""
    if profile == "direct":
        if not source.get("SupportsDirectPlay"):
            raise Fail("selftest", "Jellyfin did not offer direct play for this clip")
        query = urllib.parse.urlencode(
            {"static": "true", "mediaSourceId": source["Id"], "playSessionId": play_session}
        )
        fetch(api, f"/Videos/{item_id}/stream?{query}")
        return "DirectPlay"
    master = source.get("TranscodingUrl")
    if not master:
        raise Fail("selftest", "Jellyfin offered no transcoding URL")
    folder = master.split("?", 1)[0].rsplit("/", 1)[0] + "/"
    variant = _first_uri(fetch(api, master))
    segment = _first_uri(fetch(api, folder + variant))
    fetch(api, folder + segment)
    return "Transcode"


def play_once(api, user_id: str, item: dict, profile: str, tracker: Tracker) -> dict:
    """One real playback through Jellyfin's streaming engine; returns the finished session entry."""
    started = time.time()
    item_id = str(item["Id"])
    info = api.call(
        "selftest",
        "POST",
        f"/Items/{item_id}/PlaybackInfo",
        query={"userId": user_id},
        body=profile_body(profile),
    )
    sources = info.get("MediaSources") if isinstance(info, dict) else None
    if not sources:
        raise Fail("selftest", "Jellyfin returned no media source")
    source, play_session = sources[0], str(info.get("PlaySessionId"))
    play_method = _start_stream(api, item_id, source, play_session, profile)
    api.call(
        "selftest",
        "POST",
        "/Sessions/Playing",
        body={
            "ItemId": item_id,
            "MediaSourceId": source["Id"],
            "PlaySessionId": play_session,
            "PlayMethod": play_method,
        },
    )
    seen: list[dict] = []
    try:
        for _ in range(SELFTEST_SECONDS):
            ours = [s for s in current_sessions(api) if s.get("DeviceId") == api.device]
            seen += tracker.observe(ours, time.time())
            time.sleep(POLL_SECONDS)
    finally:
        stopped = {"ItemId": item_id, "MediaSourceId": source["Id"], "PlaySessionId": play_session}
        api.request("POST", "/Sessions/Playing/Stopped", body=stopped)
        api.request(
            "DELETE",
            "/Videos/ActiveEncodings",
            query={"deviceId": api.device, "playSessionId": play_session},
        )
    seen += tracker.finish_all()
    if not seen:
        raise Fail("selftest", "Jellyfin never listed the playback in its sessions")
    entry = finalize(seen[0], log_types_for(seen[0]["item_id"], started))
    entry["profile"] = profile
    return entry


def cmd_selftest(args: argparse.Namespace) -> int:
    profiles = list(EXPECTED_METHOD) if args.all else [args.profile]
    api, user_id = sign_in(args.base, SELFTEST_DEVICE)
    item = find_clip(api, user_id, args.row)
    store = ResultStore(SELFTEST_RESULTS)
    store.data = {}  # a self-test file holds the last invocation only
    failures = 0
    for profile in profiles:
        entry = play_once(api, user_id, item, profile, Tracker(ignore_prefix=None))
        store.add(args.row, entry)
        store.save()
        want = EXPECTED_METHOD[profile]
        if entry["method"] == want:
            print(f"OK selftest {args.row} {profile} -> {entry['method']}")
        else:
            failures += 1
            print(f"FAIL selftest {args.row} {profile}: expected {want}, got {entry['method']}")
    if args.out:
        Path(args.out).write_text(render_matrix(store.rows(), load_manifest()) + "\n", encoding="utf-8")
    return 1 if failures else 0


def ask_ok() -> str | None:
    """`yes` or `no` from the person at the TV; Enter, anything else or no terminal skips."""
    try:
        answer = input("Picture and sound OK? [y/n, Enter to skip] ").strip().lower()
    except EOFError:
        return None
    return {"y": "yes", "yes": "yes", "n": "no", "no": "no"}.get(answer)


def record_play(entry: dict, store: ResultStore, last_end: dict[str, float], *, prompt: bool) -> None:
    """Finalize a finished play with the server's evidence, show it, ask, and save at once."""
    since = max(entry["start"] - PRE_PLAY_SLACK, last_end.get(entry["item_id"], 0.0))
    finalize(entry, log_types_for(entry["item_id"], since))
    last_end[entry["item_id"]] = entry["end"]
    row = next(r for r in mc.CATALOGUE if r.id == entry["row"])
    reasons = ", ".join(entry["reasons"]) or "-"
    print(f"{entry['row']} {entry['method']} ({reasons})")
    if row.group in SUBTITLE_GROUPS and not entry["subtitles_on"]:
        print(f"{entry['row']} subtitles were off: play it again with subtitles on")
    if entry["flag"]:
        print(f"{entry['row']} {entry['flag']}")
    if prompt:
        entry["ok"] = ask_ok()
    store.add(entry["row"], entry)
    store.save()


def cmd_watch(args: argparse.Namespace) -> int:
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    api, _ = sign_in(args.base, DEVICE)
    store = ResultStore(args.results)
    tracker = Tracker()
    last_end: dict[str, float] = {}
    errors = 0
    print("Watching Jellyfin. Press play on a Compat clip on the TV. Ctrl-C to stop.")
    try:
        while True:
            try:
                sessions = current_sessions(api)
                errors = 0
            except (urllib.error.URLError, OSError, Fail) as exc:
                errors += 1
                print(f"WARN sessions: {type(exc).__name__}")
                if errors >= MAX_POLL_ERRORS:
                    print("FAIL sessions: Jellyfin does not answer")
                    return 1
                time.sleep(POLL_SECONDS)
                continue
            known = set(tracker.active)
            finished = tracker.observe(sessions, time.time())
            for key in tracker.active:
                if key not in known:
                    print(f"PLAYING {tracker.active[key]['row']}")
            for entry in finished:
                record_play(entry, store, last_end, prompt=not args.no_prompt)
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        for entry in tracker.finish_all():
            record_play(entry, store, last_end, prompt=False)
        print("\nOK saved")
        return 0


def cmd_verdict(args: argparse.Namespace) -> int:
    results = ResultStore(args.results).rows()
    lines = verdict_lines(results, load_manifest())
    print("\n".join(lines))
    return 1 if lines[0].startswith("INCOMPLETE") else 0


def cmd_forget(args: argparse.Namespace) -> int:
    store = ResultStore(args.results)
    if store.forget(args.row):
        store.save()
        print(f"OK forget {args.row}")
    else:
        print(f"OK forget {args.row} (nothing recorded)")
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    text = render_matrix(ResultStore(args.results).rows(), load_manifest())
    if args.doc:
        path = Path(args.doc)
        path.write_text(replace_matrix(path.read_text(encoding="utf-8"), text), encoding="utf-8")
    elif args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    problems = validate_doc(Path(args.doc).read_text(encoding="utf-8"), load_manifest())
    print("\n".join(problems) if problems else "OK")
    return 1 if problems else 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="The TV gate helper")
    sub = parser.add_subparsers(dest="command", required=True)
    watch = sub.add_parser("watch", help="record the plays of the TV session")
    watch.add_argument("--no-prompt", action="store_true", help="do not ask for the answer")
    watch.add_argument("--base", default=js.DEFAULT_BASE)
    watch.add_argument("--results", default=str(RESULTS), metavar="PATH")
    selftest = sub.add_parser("selftest", help="prove the helper on real playbacks, without the TV")
    selftest.add_argument("--row", required=True, choices=mc.ROW_IDS, metavar="ID")
    which = selftest.add_mutually_exclusive_group(required=True)
    which.add_argument("--profile", choices=sorted(EXPECTED_METHOD))
    which.add_argument("--all", action="store_true", help="run the four profiles in turn")
    selftest.add_argument("--base", default=js.DEFAULT_BASE)
    selftest.add_argument("--out", metavar="PATH")
    render = sub.add_parser("render", help="render the matrix of the results")
    render.add_argument("--results", default=str(RESULTS), metavar="PATH")
    target = render.add_mutually_exclusive_group()
    target.add_argument("--out", metavar="PATH")
    target.add_argument("--doc", metavar="PATH", help="replace the matrix inside this document")
    validate = sub.add_parser("validate", help="check the layout, vocabulary and privacy of the doc")
    validate.add_argument("--doc", default=str(DOC), metavar="PATH")
    verdict = sub.add_parser("verdict", help="print the candidate headline")
    verdict.add_argument("--results", default=str(RESULTS), metavar="PATH")
    forget = sub.add_parser("forget", help="drop a row's plays for a re-test")
    forget.add_argument("--results", default=str(RESULTS), metavar="PATH")
    forget.add_argument("row", choices=mc.ROW_IDS, metavar="ID")
    args = parser.parse_args(argv[1:])
    handlers = {
        "watch": cmd_watch,
        "selftest": cmd_selftest,
        "render": cmd_render,
        "validate": cmd_validate,
        "verdict": cmd_verdict,
        "forget": cmd_forget,
    }
    try:
        return handlers[args.command](args)
    except Fail as exc:
        print(f"FAIL {exc.step}: {exc.reason}")
        return 1
    except (urllib.error.URLError, OSError) as exc:
        print(f"FAIL connect: {type(exc).__name__}")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
