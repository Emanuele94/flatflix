#!/usr/bin/env python3
"""End-to-end probe of the running stack through Caddy (standard library only).

Usage:
    python3 scripts/smoke.py [--base URL] login
    python3 scripts/smoke.py [--base URL] search --q TEXT --type film|serie [--expect-results]
    python3 scripts/smoke.py [--base URL] download --q TEXT --type film|serie
    python3 scripts/smoke.py [--base URL] cache
    python3 scripts/smoke.py [--base URL] downloads
    python3 scripts/smoke.py [--base URL] all

Steps of `login` (one `OK <step>` line each, exit 1 with `FAIL <step>: <reason>`):
    no-session-401, wrong-password-401, login-204-cookie, session-200, logout-204,
    session-401-again.

Steps of `search`: login, start a search, poll the snapshots every 700 ms for up to 30 s and
check each one (HTTP 200, whitelisted keys only, seeders non-increasing, done at the end).
It prints the result count and the time to the first rows, never a result name, and it never
starts a download.

Steps of `download`: login, search, pick the first row whose name is one of the Blender open
movies (CC BY: Big Buck Bunny, Sintel, Tears of Steel, Elephants Dream, Cosmos Laundromat),
start it with POST /api/download and poll the job until started or duplicate. No such row
prints `SKIP` and exits 2: nothing else is ever started.

Steps of `all` (the hand-off probe, Phase 2.1):
    1. handoff-threshold: MIN_FILM_DURATION_MINUTES in the env file (missing means 40) must be 5
       or less, because the Blender films run about 10-15 minutes. Above 5 it prints
       `FAIL handoff-threshold: set MIN_FILM_DURATION_MINUTES=5 in .env and run docker compose up
       -d backend; restore it afterwards ...` and exits 1, before anything is downloaded.
    2. login, a search, then the count of video files under DATA_ROOT/media/Film (a count only).
    3. download for "Big Buck Bunny", "Sintel" and "Tears of Steel" until one is `started`. A
       `duplicate` tries the next query. When none starts it prints `SKIP handoff: ...` and
       exits 2: never a silent pass.
    4. handoff-state: GET /api/downloads every 5 s (up to --ready-timeout, default 3600 s), the
       open-licensed film item it started (never printed), one `OK handoff-state <state>` line per
       new state (downloading, checking, ready); check_failed, problem or a timeout is a FAIL.
       At ready `skipped` must be 0. `OK handoff-checking-seen`, or `OK
       handoff-checking-not-observed` when the check finished between two polls.
    5. handoff-media: the media video count grew by at least one (`OK handoff-media (+N)`).
    6. remove-204: DELETE /api/downloads/<id> answers 204; ten seconds later the media count is
       unchanged, so Remove from list kept the film. Every run leaves one copy in media/Film.
    Then the list check, logout and the leak scan.

Steps of `cache` (no login): cache-index-no-cache (GET / revalidates), cache-spa-fallback-no-cache
(GET /downloads revalidates), cache-asset-immutable (the hashed JS asset index.html references is
cached for a year, immutable), cache-missing-asset-404 (a missing hashed asset is a plain 404, never
immutable and never the index page).

Steps of `downloads`: login, GET /api/downloads must answer 200 with a JSON object whose only key
is items (a list); every item has exactly the eight keys id, name, type, state, progress,
eta_seconds, action, skipped, a 16 hex id, a known state (preparing, downloading, stalled,
checking, ready, problem, check_failed, rejected, unsupported, unavailable, failed), an integer
progress from 0 to 100, an action of cancel, remove or null and a non-negative integer skipped.
It prints `OK downloads-list (<n> items)` (a count, never a name), then logs out.
`all` runs the same list check after its download step and requires at least one item.

Every response any step receives is scanned for leaks at the end (qBittorrent password, session
secret, password hash, qBittorrent host, save paths (media, incomplete, quarantine, rejected,
data), category names, magnet and plugin URLs): a hit prints `FAIL leak: <marker name>` and
never the value.

APP_USER is read from the local env file by key lookup (the file is never sourced)
and the password from .dev-portal-password. Neither is ever printed.
Later plans add more subcommands to this script.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import re
import secrets
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
PASSWORD_FILE = ROOT / ".dev-portal-password"
SESSION_COOKIE = "flatflix_session"
TIMEOUT = 15


class Recorded:
    """One response a probe received: where it came from and what the browser would see."""

    __slots__ = ("body", "headers", "label", "status")

    def __init__(
        self, label: str, status: int, headers: dict[str, list[str]], body: bytes
    ) -> None:
        self.label = label
        self.status = status
        self.headers = headers
        self.body = body


# Filled by every Probe.request; scan_for_leaks reads it.
RECORDED: list[Recorded] = []


class Fail(Exception):
    def __init__(self, step: str, reason: str) -> None:
        super().__init__(f"{step}: {reason}")
        self.step = step
        self.reason = reason


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return None


class Probe:
    """Tiny HTTP client with a cookie jar, so the session cookie is kept like a browser does."""

    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar), NoRedirect()
        )

    def request(
        self, method: str, path: str, body: dict | None = None
    ) -> tuple[int, dict[str, list[str]], bytes]:
        data = None
        headers = {}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            self.base + path, data=data, method=method, headers=headers
        )
        try:
            with self.opener.open(req, timeout=TIMEOUT) as resp:
                status, raw, payload = resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as exc:
            status, raw, payload = exc.code, exc.headers, exc.read()
        headers_out: dict[str, list[str]] = {}
        for key in set(raw):
            headers_out.setdefault(key.lower(), []).extend(raw.get_all(key) or [])
        RECORDED.append(Recorded(f"{method} {path}", status, headers_out, payload))
        return status, headers_out, payload


def read_env_value(key: str) -> str:
    """Look up KEY in the local env file without sourcing it; strips optional quotes."""
    if not ENV_FILE.exists():
        raise Fail("setup", "local env file missing: run scripts/dev_env.py")
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        if name.strip() == key:
            return value.strip().strip("'\"")
    raise Fail(
        "setup", f"{key} missing from the local env file: run scripts/dev_env.py"
    )


def read_env_optional(key: str) -> str | None:
    """Like read_env_value, but a missing file or key is None (the setting keeps its default)."""
    if not ENV_FILE.exists():
        return None
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        if name.strip() == key:
            return value.strip().strip("'\"")
    return None


def read_password() -> str:
    if not PASSWORD_FILE.exists():
        raise Fail("setup", ".dev-portal-password missing: run scripts/dev_env.py")
    return PASSWORD_FILE.read_text(encoding="utf-8").strip()


def expect(step: str, status: int, wanted: int) -> None:
    if status != wanted:
        raise Fail(step, f"expected HTTP {wanted}, got {status}")


def step_ok(step: str) -> None:
    print(f"OK {step}")


def check_cookie(headers: dict[str, list[str]]) -> None:
    cookies = [
        c for c in headers.get("set-cookie", []) if c.startswith(SESSION_COOKIE + "=")
    ]
    if not cookies:
        raise Fail("login-204-cookie", f"no {SESSION_COOKIE} Set-Cookie header")
    lowered = cookies[0].lower()
    for needed in ("httponly", "max-age=2592000", "samesite=lax"):
        if needed not in lowered:
            raise Fail("login-204-cookie", f"cookie attribute missing: {needed}")


def run_login(base: str) -> None:
    user = read_env_value("APP_USER")
    password = read_password()
    probe = Probe(base)

    status, _, _ = probe.request("GET", "/api/session")
    expect("no-session-401", status, 401)
    step_ok("no-session-401")

    status, _, _ = probe.request(
        "POST", "/api/login", {"username": user, "password": password + "-wrong"}
    )
    expect("wrong-password-401", status, 401)
    step_ok("wrong-password-401")

    status, headers, _ = probe.request(
        "POST", "/api/login", {"username": user, "password": password}
    )
    expect("login-204-cookie", status, 204)
    check_cookie(headers)
    step_ok("login-204-cookie")

    status, _, _ = probe.request("GET", "/api/session")
    expect("session-200", status, 200)
    step_ok("session-200")

    status, _, _ = probe.request("POST", "/api/logout")
    expect("logout-204", status, 204)
    step_ok("logout-204")

    status, _, _ = probe.request("GET", "/api/session")
    expect("session-401-again", status, 401)
    step_ok("session-401-again")


SEARCH_RESULT_KEYS = {
    "result_id",
    "name",
    "size_human",
    "seeders",
    "leechers",
    "source",
    "quality",
}
SEARCH_SNAPSHOT_KEYS = {"search_id", "done", "timed_out", "results"}
SEARCH_POLL_SECONDS = 0.7
SEARCH_MAX_SECONDS = 30


def check_snapshot(step: str, body: object) -> list[dict]:
    if not isinstance(body, dict) or set(body) != SEARCH_SNAPSHOT_KEYS:
        raise Fail(
            step, "snapshot keys differ from search_id, done, timed_out, results"
        )
    if not isinstance(body["done"], bool) or not isinstance(body["timed_out"], bool):
        raise Fail(step, "done and timed_out must be booleans")
    rows = body["results"]
    if not isinstance(rows, list):
        raise Fail(step, "results is not a list")
    previous = None
    for entry in rows:
        if not isinstance(entry, dict) or set(entry) != SEARCH_RESULT_KEYS:
            raise Fail(step, "a result row has keys outside the whitelist")
        seeders = entry["seeders"]
        if not isinstance(seeders, int):
            raise Fail(step, "seeders is not a number")
        if previous is not None and seeders > previous:
            raise Fail(step, "seeders are not sorted from high to low")
        previous = seeders
    return rows


def login_probe(base: str) -> Probe:
    """A probe with a live household session (the cookie is kept in its jar)."""
    probe = Probe(base)
    status, _, _ = probe.request(
        "POST",
        "/api/login",
        {"username": read_env_value("APP_USER"), "password": read_password()},
    )
    expect("login-204", status, 204)
    step_ok("login-204")
    return probe


def search_flow(
    probe: Probe, query: str, content_type: str, expect_results: bool
) -> list[dict]:
    """Start a search, poll it to the end, check every snapshot and return the final rows."""
    status, _, payload = probe.request(
        "POST", "/api/search", {"q": query, "type": content_type}
    )
    expect("search-start-200", status, 200)
    try:
        started = json.loads(payload)
        search_id = started["search_id"]
    except (ValueError, KeyError, TypeError):
        raise Fail("search-start-200", "no search_id in the answer") from None
    if set(started) != {"search_id"}:
        raise Fail("search-start-200", "the answer has keys besides search_id")
    step_ok("search-start-200")

    began = time.monotonic()
    first_rows_ms: int | None = None
    rows: list[dict] = []
    done = False
    polls = 0
    while time.monotonic() - began < SEARCH_MAX_SECONDS:
        status, _, payload = probe.request("GET", f"/api/search/{search_id}")
        expect("search-poll-200", status, 200)
        polls += 1
        body = json.loads(payload)
        rows = check_snapshot("search-snapshot", body)
        if rows and first_rows_ms is None:
            first_rows_ms = int((time.monotonic() - began) * 1000)
        if body["done"]:
            done = True
            break
        time.sleep(SEARCH_POLL_SECONDS)
    if not done:
        raise Fail("search-done", f"not done after {SEARCH_MAX_SECONDS} s")
    step_ok(f"search-snapshots ({polls} polls)")

    if expect_results and not rows:
        raise Fail("search-results", "expected at least one result, got none")
    if first_rows_ms is None:
        print(f"OK search {content_type}: 0 results")
    else:
        print(
            f"OK search {content_type}: {len(rows)} results, first rows after {first_rows_ms} ms"
        )
    return rows


def run_search(base: str, query: str, content_type: str, expect_results: bool) -> None:
    probe = login_probe(base)
    search_flow(probe, query, content_type, expect_results)
    status, _, _ = probe.request("POST", "/api/logout")
    expect("logout-204", status, 204)


# The only titles the smoke test may ever download: the Blender open movies (CC BY).
OPEN_LICENSED = re.compile(
    r"\b(big[ ._-]?buck[ ._-]?bunny|sintel|tears[ ._-]?of[ ._-]?steel"
    r"|elephants?[ ._-]?dream|cosmos[ ._-]?laundromat)\b",
    re.IGNORECASE,
)
DOWNLOAD_ANSWER_KEYS = {"status", "job_id"}
DOWNLOAD_START_STATUSES = {"started", "preparing", "duplicate"}
DOWNLOAD_POLL_SECONDS = 2
DOWNLOAD_MAX_SECONDS = 120
SKIP_EXIT = 2
ALL_QUERIES = ("Big Buck Bunny", "Sintel", "Tears of Steel")


def download_flow(
    probe: Probe, query: str, content_type: str, only_started: bool = False
) -> bool:
    """Search, start the first open-licensed row, poll its job. False means nothing matched.

    With `only_started`, a duplicate (the torrent is already in qBittorrent) is False too."""
    rows = search_flow(probe, query, content_type, expect_results=False)
    chosen = next((row for row in rows if OPEN_LICENSED.search(str(row["name"]))), None)
    if chosen is None:
        print("SKIP no open-licensed result passed the filters")
        return False
    title = OPEN_LICENSED.search(str(chosen["name"]))
    print(
        f"OK download picks an open-licensed result ({title.group(0).lower() if title else '?'})"
    )

    status, _, payload = probe.request(
        "POST",
        "/api/download",
        {"result_id": chosen["result_id"], "type": content_type},
    )
    expect("download-200", status, 200)
    try:
        answer = json.loads(payload)
    except ValueError:
        raise Fail("download-200", "the answer is not JSON") from None
    if not isinstance(answer, dict) or set(answer) != DOWNLOAD_ANSWER_KEYS:
        raise Fail("download-200", "the answer keys differ from status, job_id")
    if answer["status"] not in DOWNLOAD_START_STATUSES:
        raise Fail("download-200", f"unexpected status {answer['status']}")
    job_id = answer["job_id"]

    began = time.monotonic()
    final = answer["status"]
    while final == "preparing" and time.monotonic() - began < DOWNLOAD_MAX_SECONDS:
        time.sleep(DOWNLOAD_POLL_SECONDS)
        status, _, payload = probe.request("GET", f"/api/download/{job_id}")
        expect("download-poll-200", status, 200)
        job = json.loads(payload)
        if set(job) != DOWNLOAD_ANSWER_KEYS:
            raise Fail("download-poll-200", "the job keys differ from status, job_id")
        final = job["status"]
    if final not in {"started", "duplicate"}:
        raise Fail("download", f"the job ended as {final}")
    if only_started and final != "started":
        print(f"OK download {final} (not started here, trying the next film)")
        return False
    print(f"OK download {final}")
    return True


def run_download(base: str, query: str, content_type: str) -> int:
    probe = login_probe(base)
    matched = download_flow(probe, query, content_type)
    status, _, _ = probe.request("POST", "/api/logout")
    expect("logout-204", status, 204)
    return 0 if matched else SKIP_EXIT


DOWNLOAD_LIST_KEYS = {
    "id",
    "name",
    "type",
    "state",
    "progress",
    "eta_seconds",
    "action",
    "skipped",
}
DOWNLOAD_ITEM_STATES = {
    "preparing",
    "downloading",
    "stalled",
    "checking",
    "ready",
    "problem",
    "check_failed",
    "rejected",
    "unsupported",
    "unavailable",
    "failed",
}
DOWNLOAD_ITEM_ACTIONS = {"cancel", "remove", None}
HEX16 = re.compile(r"^[0-9a-f]{16}$")


def check_item(item: object) -> None:
    """One list item: exactly the eight keys, with a known state and action (raises Fail)."""
    if not isinstance(item, dict) or set(item) != DOWNLOAD_LIST_KEYS:
        raise Fail("downloads-list", "an item has keys outside the expected eight")
    if not isinstance(item["id"], str) or not HEX16.match(item["id"]):
        raise Fail("downloads-list", "an id is not 16 lower-case hex characters")
    if item["state"] not in DOWNLOAD_ITEM_STATES:
        raise Fail("downloads-list", "an item has an unknown state")
    progress = item["progress"]
    if isinstance(progress, bool) or not isinstance(progress, int) or not 0 <= progress <= 100:
        raise Fail("downloads-list", "progress is not an integer from 0 to 100")
    if item["action"] not in DOWNLOAD_ITEM_ACTIONS:
        raise Fail("downloads-list", "an item has an unknown action")
    skipped = item["skipped"]
    if isinstance(skipped, bool) or not isinstance(skipped, int) or skipped < 0:
        raise Fail("downloads-list", "skipped is not a non-negative integer")


def check_downloads_list(probe: Probe, require_items: bool) -> int:
    """GET /api/downloads through Caddy and check the shape; returns the item count, never a name."""
    status, _, payload = probe.request("GET", "/api/downloads")
    expect("downloads-list", status, 200)
    try:
        body = json.loads(payload)
    except ValueError:
        raise Fail("downloads-list", "the answer is not JSON") from None
    if not isinstance(body, dict) or set(body) != {"items"} or not isinstance(body["items"], list):
        raise Fail("downloads-list", "the answer is not an object whose only key is items")
    for item in body["items"]:
        check_item(item)
    count = len(body["items"])
    if require_items and count == 0:
        raise Fail("downloads-list", "expected at least one item after the download step, got none")
    print(f"OK downloads-list ({count} items)")
    return count


def run_downloads(base: str) -> None:
    """The live downloads list through Caddy: shape only, counts only (DOWN-04)."""
    probe = login_probe(base)
    check_downloads_list(probe, require_items=False)
    status, _, _ = probe.request("POST", "/api/logout")
    expect("logout-204", status, 204)


def _header(headers: dict[str, list[str]], name: str) -> str:
    return ", ".join(headers.get(name, [])).lower()


def run_cache(base: str) -> None:
    """Cache-Control through Caddy: a redeploy reaches phones, hashed assets are cached long (D-42)."""
    probe = Probe(base)

    status, headers, body = probe.request("GET", "/")
    expect("cache-index-no-cache", status, 200)
    if "no-cache" not in _header(headers, "cache-control"):
        raise Fail("cache-index-no-cache", "GET / is not served with Cache-Control: no-cache")
    step_ok("cache-index-no-cache")

    status, headers, fallback = probe.request("GET", "/downloads")
    expect("cache-spa-fallback-no-cache", status, 200)
    if b"<html" not in fallback.lower():
        raise Fail("cache-spa-fallback-no-cache", "GET /downloads did not return the index page")
    if "no-cache" not in _header(headers, "cache-control"):
        raise Fail("cache-spa-fallback-no-cache", "the SPA fallback is not served with no-cache")
    step_ok("cache-spa-fallback-no-cache")

    match = re.search(rb'/assets/[A-Za-z0-9._-]+\.js', body)
    if not match:
        raise Fail("cache-asset-immutable", "index.html references no /assets/*.js file")
    status, headers, _ = probe.request("GET", match.group(0).decode("ascii"))
    expect("cache-asset-immutable", status, 200)
    cache_control = _header(headers, "cache-control")
    if "immutable" not in cache_control or "max-age=31536000" not in cache_control:
        raise Fail("cache-asset-immutable", "the hashed asset is not cached for a year as immutable")
    step_ok("cache-asset-immutable")

    status, headers, _ = probe.request("GET", f"/assets/smoke-missing-{secrets.token_hex(4)}.js")
    expect("cache-missing-asset-404", status, 404)
    if "immutable" in _header(headers, "cache-control"):
        raise Fail("cache-missing-asset-404", "a missing asset carries an immutable Cache-Control")
    step_ok("cache-missing-asset-404")


REMOVE_KEEPS_STEP = "remove-keeps-film"
HANDOFF_MAX_MINUTES = 5
DEFAULT_MIN_FILM_MINUTES = 40
HANDOFF_POLL_SECONDS = 5
READY_TIMEOUT_SECONDS = 3600
REMOVE_SETTLE_SECONDS = 10
MEDIA_VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".m4v"}
TERMINAL_STATES = {"ready", "check_failed", "failed", "rejected", "unsupported", "unavailable"}
FAILED_STATES = {"check_failed", "problem", "failed", "rejected", "unsupported", "unavailable"}


def check_handoff_threshold() -> None:
    """The Blender films run about 10-15 minutes: a film minimum above 5 would reject them."""
    raw = read_env_optional("MIN_FILM_DURATION_MINUTES")
    minutes = int(raw) if raw is not None and raw.isdigit() else DEFAULT_MIN_FILM_MINUTES
    if minutes > HANDOFF_MAX_MINUTES:
        raise Fail(
            "handoff-threshold",
            "set MIN_FILM_DURATION_MINUTES=5 in .env and run docker compose up -d backend; "
            "restore it afterwards (the Blender open movies run about 10-15 minutes)",
        )


def media_film_folder() -> Path:
    raw = read_env_optional("DATA_ROOT") or "./data"
    root = Path(raw)
    return (root if root.is_absolute() else ROOT / root) / "media" / "Film"


def count_media_videos() -> int:
    """Video files below DATA_ROOT/media/Film on the host. A count, never a name."""
    folder = media_film_folder()
    if not folder.is_dir():
        raise Fail("setup", "DATA_ROOT/media/Film is missing: run scripts/init-host-dirs.sh")
    return sum(
        1
        for path in folder.rglob("*")
        if path.suffix.lower() in MEDIA_VIDEO_EXTENSIONS and path.is_file()
    )


def fetch_items(probe: Probe) -> list[dict]:
    """GET /api/downloads, shape-checked; the items as they came."""
    status, _, payload = probe.request("GET", "/api/downloads")
    expect("downloads-list", status, 200)
    try:
        body = json.loads(payload)
    except ValueError:
        raise Fail("downloads-list", "the answer is not JSON") from None
    if not isinstance(body, dict) or not isinstance(body.get("items"), list):
        raise Fail("downloads-list", "the answer is not an object whose only key is items")
    for item in body["items"]:
        check_item(item)
    return body["items"]


def open_film_states(items: list[dict]) -> dict[str, str]:
    """id -> state of every open-licensed film item (names are matched, never printed)."""
    return {
        item["id"]: item["state"]
        for item in items
        if item["type"] == "film" and OPEN_LICENSED.search(str(item["name"]))
    }


def pick_started_film(items: list[dict], before: dict[str, str]) -> dict | None:
    """The open-licensed film item this run started: an id the list did not hold before, or one
    that held only a finished entry and is active again."""
    for item in items:
        if item["type"] != "film" or not OPEN_LICENSED.search(str(item["name"])):
            continue
        earlier = before.get(item["id"])
        if earlier is None or (earlier in TERMINAL_STATES and item["state"] not in TERMINAL_STATES):
            return item
    return None


def follow_to_ready(probe: Probe, before: dict[str, str], ready_timeout: float) -> str:
    """Poll the list until the started film is ready; returns its id."""
    began = time.monotonic()
    seen: list[str] = []
    item_id: str | None = None
    state = "not listed yet"
    while True:
        items = fetch_items(probe)
        if item_id is not None:
            item = next((i for i in items if i["id"] == item_id), None)
        else:
            item = pick_started_film(items, before)
        if item is not None:
            item_id = item["id"]
            state = item["state"]
            if state not in seen:
                seen.append(state)
                print(f"OK handoff-state {state}")
            if state in FAILED_STATES:
                raise Fail("handoff", f"the film ended as {state}")
            if state == "ready":
                if item["skipped"] != 0:
                    raise Fail("handoff", f"ready with {item['skipped']} skipped file(s), wanted 0")
                break
        if time.monotonic() - began > ready_timeout:
            raise Fail("handoff", f"not ready after {int(ready_timeout)} s (last state {state})")
        time.sleep(HANDOFF_POLL_SECONDS)
    if "checking" in seen:
        step_ok("handoff-checking-seen")
    else:
        step_ok("handoff-checking-not-observed (the check finished between two polls)")
    assert item_id is not None
    return item_id


def run_all(base: str, ready_timeout: float = READY_TIMEOUT_SECONDS) -> int:
    check_handoff_threshold()
    run_login(base)
    probe = login_probe(base)
    search_flow(probe, "1080p", "film", expect_results=True)
    media_before = count_media_videos()
    print(f"OK handoff-media-before ({media_before} video files)")
    before = open_film_states(fetch_items(probe))
    started = False
    for query in ALL_QUERIES:
        if download_flow(probe, query, "film", only_started=True):
            started = True
            break
    if not started:
        print(
            "SKIP handoff: every open film is already in qBittorrent; "
            "remove it from the Downloads tab and run again"
        )
        status, _, _ = probe.request("POST", "/api/logout")
        expect("logout-204", status, 204)
        return SKIP_EXIT

    item_id = follow_to_ready(probe, before, ready_timeout)
    media_after = count_media_videos()
    if media_after - media_before < 1:
        raise Fail("handoff-media", "no new video file appeared in media/Film")
    print(f"OK handoff-media (+{media_after - media_before})")

    status, _, _ = probe.request("DELETE", f"/api/downloads/{item_id}")
    expect("remove-204", status, 204)
    step_ok("remove-204")
    time.sleep(REMOVE_SETTLE_SECONDS)
    if count_media_videos() != media_after:
        raise Fail(REMOVE_KEEPS_STEP, "the media video count changed after Remove from list")
    step_ok(REMOVE_KEEPS_STEP)

    check_downloads_list(probe, require_items=False)
    status, _, _ = probe.request("POST", "/api/logout")
    expect("logout-204", status, 204)
    return 0


def leak_markers() -> dict[str, str]:
    """Marker name -> forbidden text. Secret values come from the local env file, never printed."""
    markers = {
        "qBittorrent password": read_env_value("QBITTORRENT_PASS"),
        "session secret": read_env_value("SECRET_KEY"),
        "password hash": read_env_value("APP_PASS_HASH"),
        "qBittorrent host": "qbittorrent:8088",
        "qBittorrent session cookie": "QBT_SID",
        "save_path key": "save_path",
        "content_path key": "content_path",
        "media path": "/media/",
        "incomplete path": "/incomplete",
        "quarantine path": "/quarantine",
        "rejected path": "/rejected",
        "data path": "/data/",
        "magnet link": "magnet:",
        "fileUrl key": "fileUrl",
        "descrLink key": "descrLink",
        "category key": '"category"',
    }
    try:
        markers["serie category name"] = read_env_value("CATEGORY_TV")
    except Fail:
        markers["serie category name"] = "SerieTV"  # the built-in default
    return {name: text for name, text in markers.items() if text}


def scan_for_leaks(recorded: list[Recorded] | None = None) -> list[str]:
    """Names of the markers found in any recorded body or header, each once, never the value.

    The flatflix_session Set-Cookie is the one header allowed to carry opaque data.
    """
    markers = leak_markers()
    found: list[str] = []
    for item in recorded if recorded is not None else RECORDED:
        header_text = "\n".join(
            f"{name}: {value}"
            for name, values in item.headers.items()
            for value in values
            if not (name == "set-cookie" and value.startswith(SESSION_COOKIE + "="))
        )
        text = item.body.decode("utf-8", errors="replace") + "\n" + header_text
        for name, forbidden in markers.items():
            if forbidden in text and name not in found:
                found.append(name)
    return found


def report_leaks() -> int:
    leaks = scan_for_leaks()
    for name in leaks:
        print(f"FAIL leak: {name}")
    if not leaks:
        print(f"OK no-leaks ({len(RECORDED)} responses scanned)")
    return 1 if leaks else 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Probe the running Flatflix stack")
    parser.add_argument("--base", default="http://127.0.0.1")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("login", help="session lifecycle through Caddy")
    search = sub.add_parser("search", help="start a search and poll its snapshots")
    search.add_argument("--q", required=True, help="search text")
    search.add_argument("--type", required=True, choices=["film", "serie"])
    search.add_argument(
        "--expect-results", action="store_true", help="zero results is a FAIL"
    )
    download = sub.add_parser(
        "download", help="start one open-licensed (Blender) result"
    )
    download.add_argument("--q", required=True, help="search text")
    download.add_argument("--type", required=True, choices=["film", "serie"])
    sub.add_parser("cache", help="Cache-Control of index.html, SPA paths and hashed assets")
    sub.add_parser("downloads", help="the live downloads list through Caddy")
    everything = sub.add_parser(
        "all", help="login, search, one open-licensed film through Checking to Ready and Remove"
    )
    everything.add_argument(
        "--ready-timeout",
        type=float,
        default=READY_TIMEOUT_SECONDS,
        metavar="SECONDS",
        help="how long to wait for the film to become ready (default 3600)",
    )
    args = parser.parse_args(argv)

    code = 0
    try:
        if args.command == "login":
            run_login(args.base)
        elif args.command == "search":
            run_search(args.base, args.q, args.type, args.expect_results)
        elif args.command == "download":
            code = run_download(args.base, args.q, args.type)
        elif args.command == "cache":
            run_cache(args.base)
        elif args.command == "downloads":
            run_downloads(args.base)
        elif args.command == "all":
            code = run_all(args.base, args.ready_timeout)
        leak_code = report_leaks()
    except Fail as exc:
        print(f"FAIL {exc.step}: {exc.reason}")
        return 1
    except (urllib.error.URLError, OSError) as exc:
        print(f"FAIL connect: {type(exc).__name__}")
        return 1
    return leak_code or code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
