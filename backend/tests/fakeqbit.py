"""Stateful fake of the qBittorrent WebAPI for tests (auth, session, ban).

Later plans add endpoints with `register(method, path, handler)`. The handler
receives the `httpx.Request` and returns an `httpx.Response`; it may be sync or
async. Requests without a live session cookie get 403, like the real service.
"""

import asyncio
import inspect
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from http.cookies import SimpleCookie
from urllib.parse import parse_qsl

import httpx

SESSION_COOKIE = "QBT_SID_8088"
LOGIN_PATH = "/api/v2/auth/login"


@dataclass
class Call:
    method: str
    path: str
    params: dict[str, str] = field(default_factory=dict)
    form: dict[str, str] = field(default_factory=dict)


class FakeQbit:
    def __init__(self, username: str, password: str) -> None:
        self._username = username
        self._password = password
        self.calls: list[Call] = []
        self.logins = 0  # successful logins
        self.login_attempts = 0  # every POST to the login route
        self.webapi_version = "2.15.1"
        self.ban_after = 5  # failed logins before every login answers 403
        self._failed_logins = 0
        self._sessions: set[str] = set()
        self._routes: dict[tuple[str, str], Callable] = {}
        self.register("GET", "/api/v2/app/webapiVersion", self._serve_version)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    @property
    def banned(self) -> bool:
        return self._failed_logins >= self.ban_after

    def register(self, method: str, path: str, handler: Callable) -> None:
        self._routes[(method.upper(), path)] = handler

    def expire_sessions(self) -> None:
        self._sessions.clear()

    def _serve_version(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=self.webapi_version)

    def _has_session(self, request: httpx.Request) -> bool:
        cookie = SimpleCookie(request.headers.get("cookie", ""))
        morsel = cookie.get(SESSION_COOKIE)
        return morsel is not None and morsel.value in self._sessions

    def _login(self, form: dict[str, str]) -> httpx.Response:
        self.login_attempts += 1
        if self.banned:
            return httpx.Response(403, text="Your IP address has been banned.")
        if form.get("username") == self._username and form.get("password") == self._password:
            self._failed_logins = 0
            self.logins += 1
            sid = secrets.token_hex(8)
            self._sessions.add(sid)
            return httpx.Response(
                204, headers={"set-cookie": f"{SESSION_COOKIE}={sid}; HttpOnly; path=/"}
            )
        self._failed_logins += 1
        return httpx.Response(401, text="Unauthorized")

    async def handler(self, request: httpx.Request) -> httpx.Response:
        # One real suspension point so concurrent callers interleave like on a socket.
        await asyncio.sleep(0)
        path = request.url.path
        form: dict[str, str] = {}
        if request.headers.get("content-type", "").startswith("application/x-www-form-urlencoded"):
            form = dict(parse_qsl(request.content.decode()))
        self.calls.append(Call(request.method, path, dict(request.url.params), form))

        if path == LOGIN_PATH and request.method == "POST":
            return self._login(form)
        if not self._has_session(request):
            return httpx.Response(403, text="Forbidden")
        route = self._routes.get((request.method, path))
        if route is None:
            return httpx.Response(404, text="Not Found")
        response = route(request)
        if inspect.isawaitable(response):
            response = await response
        return response
