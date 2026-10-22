"""Stateful fake of the qBittorrent WebAPI for tests (auth, session, ban).

Later plans add endpoints with `register(method, path, handler)`. The handler
receives the `httpx.Request` and returns an `httpx.Response`; it may be sync or
async. Requests without a live session cookie get 403, like the real service.
"""

import asyncio
import inspect
import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from http.cookies import SimpleCookie
from urllib.parse import parse_qsl

import httpx

SESSION_COOKIE = "QBT_SID_8088"
LOGIN_PATH = "/api/v2/auth/login"


@dataclass
class FakeSearch:
    """One search as qBittorrent keeps it until `search/delete`."""

    qbit_id: int
    batches: list[list[dict]]
    final_status: str
    polls: int = 0
    stopped: bool = False


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
        # Configuration state, as the real service keeps it (see 01-RESEARCH Pattern 7).
        self.preferences: dict = {
            "auto_tmm_enabled": False,
            "category_changed_tmm_enabled": False,
            "temp_path_enabled": False,
            "temp_path": "",
            "excluded_file_names_enabled": False,
            "excluded_file_names": "",
        }
        self.preference_payloads: list[str] = []  # raw `json` form values of setPreferences
        self.category_table: dict[str, dict] = {}
        self.register("GET", "/api/v2/app/preferences", self._serve_preferences)
        self.register("POST", "/api/v2/app/setPreferences", self._set_preferences)
        self.register("GET", "/api/v2/torrents/categories", self._serve_categories)
        self.register("POST", "/api/v2/torrents/createCategory", self._create_category)
        self.register("POST", "/api/v2/torrents/editCategory", self._edit_category)
        # Search plugins: qBittorrent ships with none. An installed plugin shows up in the
        # list only after `plugin_install_delay_calls` further GETs, like the real download.
        self.plugins: list[dict] = []
        self.plugin_install_delay_calls = 0
        self._pending_plugins: list[list] = []  # [remaining_gets, plugin]
        self.register("GET", "/api/v2/search/plugins", self._serve_plugins)
        self.register("POST", "/api/v2/search/installPlugin", self._install_plugin)
        # Live search. `script_search` decides what every search started afterwards returns.
        self.max_searches = 5  # qBittorrent answers 409 beyond this many undeleted searches
        self.searches: dict[int, FakeSearch] = {}
        self._script: tuple[list[list[dict]], str] = ([], "Stopped")
        self._next_search_id = 1962241670
        self.register("POST", "/api/v2/search/start", self._search_start)
        self.register("GET", "/api/v2/search/status", self._search_status)
        self.register("GET", "/api/v2/search/results", self._search_results)
        self.register("POST", "/api/v2/search/stop", self._search_stop)
        self.register("POST", "/api/v2/search/delete", self._search_delete)

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

    def _serve_preferences(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=self.preferences)

    def _set_preferences(self, request: httpx.Request) -> httpx.Response:
        raw = dict(parse_qsl(request.content.decode())).get("json")
        if raw is None:
            return httpx.Response(400, text="Bad Request")
        self.preference_payloads.append(raw)
        self.preferences.update(json.loads(raw))
        return httpx.Response(200)

    def _serve_categories(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=self.category_table)

    def _create_category(self, request: httpx.Request) -> httpx.Response:
        form = dict(parse_qsl(request.content.decode()))
        name = form.get("category", "")
        if not name:
            return httpx.Response(400, text="Bad Request")
        if name in self.category_table:
            return httpx.Response(409, text="Unable to create category")
        self.category_table[name] = {"name": name, "savePath": form.get("savePath", "")}
        return httpx.Response(200)

    def _edit_category(self, request: httpx.Request) -> httpx.Response:
        form = dict(parse_qsl(request.content.decode()))
        name = form.get("category", "")
        if name not in self.category_table:
            return httpx.Response(409, text="Unable to edit category")
        self.category_table[name]["savePath"] = form.get("savePath", "")
        return httpx.Response(200)

    def _serve_plugins(self, request: httpx.Request) -> httpx.Response:
        for pending in list(self._pending_plugins):
            if pending[0] > 0:
                pending[0] -= 1
            else:
                self._pending_plugins.remove(pending)
                self.plugins.append(pending[1])
        return httpx.Response(200, json=self.plugins)

    def _install_plugin(self, request: httpx.Request) -> httpx.Response:
        sources = dict(parse_qsl(request.content.decode())).get("sources", "")
        for url in filter(None, sources.split("|")):
            name = url.rsplit("/", 1)[-1].removesuffix(".py")
            plugin = {
                "name": name,
                "enabled": True,
                "version": "1.0",
                "url": url,
                "fullName": name,
                "supportedCategories": [{"id": "all", "name": "All categories"}],
            }
            self._pending_plugins.append([self.plugin_install_delay_calls, plugin])
        return httpx.Response(200)

    def script_search(self, batches: list[list[dict]], final_status: str = "Stopped") -> None:
        """Script every search started from now on.

        Each `search/results` call returns the cumulative rows of the next batch with status
        Running; once the batches run out it keeps returning the last batch with `final_status`
        (pass "Running" to model a search that never ends).
        """
        self._script = ([list(batch) for batch in batches], final_status)

    def _search_start(self, request: httpx.Request) -> httpx.Response:
        form = dict(parse_qsl(request.content.decode()))
        if not all(form.get(key) for key in ("pattern", "category", "plugins")):
            return httpx.Response(400, text="Bad Request")
        if len(self.searches) >= self.max_searches:
            return httpx.Response(409, text="Unable to create more than 5 searches")
        self._next_search_id += 1
        batches, final_status = self._script
        self.searches[self._next_search_id] = FakeSearch(
            self._next_search_id, batches, final_status
        )
        return httpx.Response(200, json={"id": self._next_search_id})

    def _search_for(self, request: httpx.Request) -> FakeSearch | None:
        raw = request.url.params.get("id") or dict(parse_qsl(request.content.decode())).get("id")
        return self.searches.get(int(raw)) if raw and raw.lstrip("-").isdigit() else None

    def _search_status(self, request: httpx.Request) -> httpx.Response:
        raw = request.url.params.get("id")
        if raw is None:
            found = list(self.searches.values())
        else:
            search = self._search_for(request)
            if search is None:
                return httpx.Response(404, text="Not Found")
            found = [search]
        rows = [
            {
                "id": search.qbit_id,
                "status": "Stopped" if search.stopped else "Running",
                "total": len(search.batches[-1]) if search.batches else 0,
            }
            for search in found
        ]
        return httpx.Response(200, json=rows)

    def _search_results(self, request: httpx.Request) -> httpx.Response:
        search = self._search_for(request)
        if search is None:
            return httpx.Response(404, text="Not Found")
        index = search.polls
        search.polls += 1
        if search.stopped:
            status = "Stopped"
            rows = search.batches[min(index, len(search.batches) - 1)] if search.batches else []
        elif index < len(search.batches):
            status, rows = "Running", search.batches[index]
        else:
            status = search.final_status
            rows = search.batches[-1] if search.batches else []
        return httpx.Response(200, json={"results": rows, "status": status, "total": len(rows)})

    def _search_stop(self, request: httpx.Request) -> httpx.Response:
        search = self._search_for(request)
        if search is None:
            return httpx.Response(404, text="Not Found")
        search.stopped = True
        return httpx.Response(200)

    def _search_delete(self, request: httpx.Request) -> httpx.Response:
        search = self._search_for(request)
        if search is None:
            return httpx.Response(404, text="Not Found")
        del self.searches[search.qbit_id]
        return httpx.Response(200)

    def calls_to(self, path: str) -> list[Call]:
        return [call for call in self.calls if call.path == path]

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
