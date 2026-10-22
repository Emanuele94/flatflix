#!/usr/bin/env python3
"""End-to-end probe of the running stack through Caddy (standard library only).

Usage:
    python3 scripts/smoke.py [--base URL] login
    python3 scripts/smoke.py [--base URL] search --q TEXT --type film|serie [--expect-results]

Steps of `login` (one `OK <step>` line each, exit 1 with `FAIL <step>: <reason>`):
    no-session-401, wrong-password-401, login-204-cookie, session-200, logout-204,
    session-401-again.

Steps of `search`: login, start a search, poll the snapshots every 700 ms for up to 30 s and
check each one (HTTP 200, whitelisted keys only, seeders non-increasing, done at the end).
It prints the result count and the time to the first rows, never a result name, and it never
starts a download.

APP_USER is read from the local env file by key lookup (the file is never sourced)
and the password from .dev-portal-password. Neither is ever printed.
Later plans add more subcommands to this script.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
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


def run_search(base: str, query: str, content_type: str, expect_results: bool) -> None:
    user = read_env_value("APP_USER")
    password = read_password()
    probe = Probe(base)

    status, _, _ = probe.request(
        "POST", "/api/login", {"username": user, "password": password}
    )
    expect("login-204", status, 204)
    step_ok("login-204")

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

    status, _, _ = probe.request("POST", "/api/logout")
    expect("logout-204", status, 204)


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
    args = parser.parse_args(argv)

    try:
        if args.command == "login":
            run_login(args.base)
        elif args.command == "search":
            run_search(args.base, args.q, args.type, args.expect_results)
    except Fail as exc:
        print(f"FAIL {exc.step}: {exc.reason}")
        return 1
    except (urllib.error.URLError, OSError) as exc:
        print(f"FAIL connect: {type(exc).__name__}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
