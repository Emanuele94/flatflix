#!/usr/bin/env python3
"""End-to-end probe of the running stack through Caddy (standard library only).

Usage:
    python3 scripts/smoke.py [--base URL] login

Steps of `login` (one `OK <step>` line each, exit 1 with `FAIL <step>: <reason>`):
    no-session-401, wrong-password-401, login-204-cookie, session-200, logout-204,
    session-401-again.

APP_USER is read from the local env file by key lookup (the file is never sourced)
and the password from .dev-portal-password. Neither is ever printed.
Later plans add more subcommands to this script.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import sys
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
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
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
    raise Fail("setup", f"{key} missing from the local env file: run scripts/dev_env.py")


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
    cookies = [c for c in headers.get("set-cookie", []) if c.startswith(SESSION_COOKIE + "=")]
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


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Probe the running Flatflix stack")
    parser.add_argument("--base", default="http://127.0.0.1")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("login", help="session lifecycle through Caddy")
    args = parser.parse_args(argv)

    try:
        if args.command == "login":
            run_login(args.base)
    except Fail as exc:
        print(f"FAIL {exc.step}: {exc.reason}")
        return 1
    except (urllib.error.URLError, OSError) as exc:
        print(f"FAIL connect: {type(exc).__name__}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
