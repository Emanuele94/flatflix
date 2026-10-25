#!/usr/bin/env python3
"""The measuring half of the TV gate: turn each play of a Compat clip into a matrix row.

Usage:
    python3 scripts/tv_gate.py selftest --row ID --profile remux [--base URL] [--out PATH]
    python3 scripts/tv_gate.py render [--results PATH] [--out PATH]

`selftest` drives one real playback of a Compat clip through Jellyfin's own streaming engine
(a stand-in client that signs in as the device "flatflix-tv-gate-selftest"), reads the evidence the
same way the TV session will, and prints `OK selftest <ID> <profile> -> <Method>` or a FAIL line
when the Method differs from the one the profile must give. Its results go to
jellyfin/tv-gate/selftest.json (replaced on every run) and never to results.json.

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
EXPECTED_METHOD = {"remux": "Remux"}
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
SUBTITLE_GROUPS = ("subs", "pgs")  # rows whose clip is only a test with its subtitles switched on
POLL_SECONDS = 1.0
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
        except (FileNotFoundError, ValueError):
            raw = {}
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


def replace_matrix(doc_text: str, matrix: str) -> str:
    """Put the matrix between the markers; exactly one begin and one end marker, else ValueError."""
    if doc_text.count(MATRIX_BEGIN) != 1 or doc_text.count(MATRIX_END) != 1:
        raise ValueError("the document needs exactly one matrix begin marker and one end marker")
    begin = doc_text.index(MATRIX_BEGIN)
    end = doc_text.index(MATRIX_END)
    if end < begin:
        raise ValueError("the matrix end marker comes before the begin marker")
    return doc_text[: begin + len(MATRIX_BEGIN)] + "\n\n" + matrix + "\n\n" + doc_text[end:]


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


def profile_body(profile: str) -> dict:
    """The PlaybackInfo body for a selftest profile: no direct play, one HLS transcoding profile."""
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
    return {
        "DeviceProfile": {
            "Name": f"flatflix-selftest-{profile}",
            "MaxStreamingBitrate": SELFTEST_BITRATE,
            "DirectPlayProfiles": [],
            "TranscodingProfiles": [transcoding],
            "CodecProfiles": [],
            "SubtitleProfiles": [],
        },
        "MaxStreamingBitrate": SELFTEST_BITRATE,
        "EnableDirectPlay": False,
        "EnableDirectStream": False,
        "AllowVideoStreamCopy": True,
        "AllowAudioStreamCopy": True,
    }


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
    if not sources or not sources[0].get("TranscodingUrl"):
        raise Fail("selftest", "Jellyfin offered no transcoding URL")
    source, play_session = sources[0], str(info.get("PlaySessionId"))
    master = source["TranscodingUrl"]
    folder = master.split("?", 1)[0].rsplit("/", 1)[0] + "/"
    variant = _first_uri(fetch(api, master))
    segment = _first_uri(fetch(api, folder + variant))
    fetch(api, folder + segment)
    api.call(
        "selftest",
        "POST",
        "/Sessions/Playing",
        body={
            "ItemId": item_id,
            "MediaSourceId": source["Id"],
            "PlaySessionId": play_session,
            "PlayMethod": "Transcode",
        },
    )
    seen: list[dict] = []
    try:
        for _ in range(SELFTEST_SECONDS):
            ours = [s for s in current_sessions(api) if s.get("DeviceId") == api.device]
            seen += tracker.observe(ours, time.time())
            time.sleep(POLL_SECONDS)
    finally:
        api.request(
            "POST",
            "/Sessions/Playing/Stopped",
            body={"ItemId": item_id, "MediaSourceId": source["Id"], "PlaySessionId": play_session},
        )
        api.request(
            "DELETE",
            "/Videos/ActiveEncodings",
            query={"deviceId": api.device, "playSessionId": play_session},
        )
    seen += tracker.finish_all()
    if not seen:
        raise Fail("selftest", "Jellyfin never listed the playback in its sessions")
    entry = seen[0]
    logs = log_types_for(entry["item_id"], started)
    entry["log_types"] = logs
    entry["method"] = classify(entry["play_method"], entry["transcoding"], logs)
    entry["flag"] = disagreement_note(logs, entry["transcoding"]) if signals_disagree(logs, entry["transcoding"]) else ""
    entry["ok"] = None
    entry["profile"] = profile
    return entry


def cmd_selftest(args: argparse.Namespace) -> int:
    profiles = [args.profile]
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


def cmd_render(args: argparse.Namespace) -> int:
    text = render_matrix(ResultStore(args.results).rows(), load_manifest())
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="The TV gate helper")
    sub = parser.add_subparsers(dest="command", required=True)
    selftest = sub.add_parser("selftest", help="prove the helper on real playbacks, without the TV")
    selftest.add_argument("--row", required=True, choices=mc.ROW_IDS, metavar="ID")
    selftest.add_argument("--profile", required=True, choices=sorted(EXPECTED_METHOD))
    selftest.add_argument("--base", default=js.DEFAULT_BASE)
    selftest.add_argument("--out", metavar="PATH")
    render = sub.add_parser("render", help="render the matrix of the results")
    render.add_argument("--results", default=str(RESULTS), metavar="PATH")
    render.add_argument("--out", metavar="PATH")
    args = parser.parse_args(argv[1:])
    try:
        return {"selftest": cmd_selftest, "render": cmd_render}[args.command](args)
    except Fail as exc:
        print(f"FAIL {exc.step}: {exc.reason}")
        return 1
    except (urllib.error.URLError, OSError) as exc:
        print(f"FAIL connect: {type(exc).__name__}")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
