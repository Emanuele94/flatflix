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
prints `SKIP` and exits 2: nothing else is ever started. `all` runs login, a search and then
`download` for "Big Buck Bunny", "Sintel" and "Tears of Steel" until one does not skip.

Steps of `cache` (no login): cache-index-no-cache (GET / revalidates), cache-spa-fallback-no-cache
(GET /downloads revalidates), cache-asset-immutable (the hashed JS asset index.html references is
cached for a year, immutable), cache-missing-asset-404 (a missing hashed asset is a plain 404, never
immutable and never the index page).

Steps of `downloads`: login, GET /api/downloads must answer 200 with a JSON object whose only key
is items (a list); every item has exactly the keys id, name, type, state, progress, eta_seconds,
action, a 16 hex id, a known state, an integer progress from 0 to 100 and an action of cancel,
remove or null. It prints `OK downloads-list (<n> items)` (a count, never a name), then logs out.
`all` runs the same list check after its download step and requires at least one item.

Every response any step receives is scanned for leaks at the end (qBittorrent password, session
secret, password hash, qBittorrent host, save paths, category names, magnet and plugin URLs): a
hit prints `FAIL leak: <marker name>` and never the value.

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


def download_flow(probe: Probe, query: str, content_type: str) -> bool:
    """Search, start the first open-licensed row, poll its job. False means nothing matched."""
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
    print(f"OK download {final}")
    return True


def run_download(base: str, query: str, content_type: str) -> int:
    probe = login_probe(base)
    matched = download_flow(probe, query, content_type)
    status, _, _ = probe.request("POST", "/api/logout")
    expect("logout-204", status, 204)
    return 0 if matched else SKIP_EXIT


DOWNLOAD_LIST_KEYS = {"id", "name", "type", "state", "progress", "eta_seconds", "action"}
DOWNLOAD_ITEM_STATES = {
    "preparing",
    "downloading",
    "stalled",
    "ready",
    "problem",
    "rejected",
    "unsupported",
    "unavailable",
    "failed",
}
DOWNLOAD_ITEM_ACTIONS = {"cancel", "remove", None}
HEX16 = re.compile(r"^[0-9a-f]{16}$")


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
        if not isinstance(item, dict) or set(item) != DOWNLOAD_LIST_KEYS:
            raise Fail("downloads-list", "an item has keys outside the expected seven")
        if not isinstance(item["id"], str) or not HEX16.match(item["id"]):
            raise Fail("downloads-list", "an id is not 16 lower-case hex characters")
        if item["state"] not in DOWNLOAD_ITEM_STATES:
            raise Fail("downloads-list", "an item has an unknown state")
        progress = item["progress"]
        if isinstance(progress, bool) or not isinstance(progress, int) or not 0 <= progress <= 100:
            raise Fail("downloads-list", "progress is not an integer from 0 to 100")
        if item["action"] not in DOWNLOAD_ITEM_ACTIONS:
            raise Fail("downloads-list", "an item has an unknown action")
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


def run_all(base: str) -> int:
    run_login(base)
    probe = login_probe(base)
    search_flow(probe, "1080p", "film", expect_results=True)
    started = False
    for query in ALL_QUERIES:
        if download_flow(probe, query, "film"):
            started = True
            break
    if started:
        check_downloads_list(probe, require_items=True)
    status, _, _ = probe.request("POST", "/api/logout")
    expect("logout-204", status, 204)
    return 0 if started else SKIP_EXIT


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
    sub.add_parser(
        "all", help="login, search, download an open-licensed film, list check, leak scan"
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
            code = run_all(args.base)
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
