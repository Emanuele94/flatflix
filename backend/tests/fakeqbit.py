"""Stateful fake of the qBittorrent WebAPI for tests (auth, session, ban).

Later plans add endpoints with `register(method, path, handler)`. The handler
receives the `httpx.Request` and returns an `httpx.Response`; it may be sync or
async. Requests without a live session cookie get 403, like the real service.
"""

import asyncio
import fnmatch
import hashlib
import inspect
import json
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from http.cookies import SimpleCookie
from urllib.parse import parse_qsl

import httpx

from app.search.filters import infohash

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
class FakeTorrent:
    """One torrent as qBittorrent keeps it. `files` is None until its metadata is released."""

    hash: str
    url: str
    category: str
    tags: list[str]
    added_on: float
    started: bool = False
    files: list[dict] | None = None
    polls_left: int = 0  # `torrents/files` answers [] this many more times
    downloaded: int = 0  # payload bytes fetched so far (a stopped torrent can still hold some)


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
        # Torrents. `set_metadata` says what a torrent's file list will be and when it arrives.
        self.torrents: dict[str, FakeTorrent] = {}
        self.deleted: list[tuple[str, bool]] = []  # (hash, deleteFiles) in call order
        self.clock: Callable[[], float] = time.time  # `added_on` comes from here
        self.ignore_prio_ids: set[int] = set()  # filePrio silently skips these file ids
        self.files_404_calls = 0  # `torrents/files` answers 404 this many times, then normally
        self.downloader_delay_calls = 0  # `torrents/info` calls before a downloader torrent shows
        self._metadata: dict[str, tuple[list[dict], int]] = {}
        self._pending_downloads: list[list] = []  # [remaining_info_calls, FakeTorrent]
        self.register("POST", "/api/v2/torrents/add", self._torrents_add)
        self.register("GET", "/api/v2/torrents/info", self._torrents_info)
        self.register("GET", "/api/v2/torrents/files", self._torrents_files)
        self.register("POST", "/api/v2/torrents/filePrio", self._torrents_file_prio)
        self.register("POST", "/api/v2/torrents/start", self._torrents_start)
        self.register("POST", "/api/v2/torrents/delete", self._torrents_delete)
        self.register("POST", "/api/v2/torrents/removeTags", self._torrents_remove_tags)
        self.register("POST", "/api/v2/torrents/deleteTags", self._torrents_delete_tags)

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

    @staticmethod
    def hash_for(url: str) -> str:
        """Hash qBittorrent would use: the btih of a magnet, else a digest of the URL."""
        return infohash(url) or hashlib.sha1(url.encode()).hexdigest()

    def set_metadata(
        self, torrent_hash: str, files: list[tuple[str, int]], delay_polls: int = 0
    ) -> None:
        """Say which files `torrents/files` will return, after `delay_polls` empty answers.

        Call it before or after the torrent is added. Files matching the exclusion list in
        `self.preferences` come out at priority 0, like the real engine does at add.
        """
        rows = [
            {"index": i, "name": name, "size": size, "priority": 1, "progress": 0.0}
            for i, (name, size) in enumerate(files)
        ]
        self._metadata[torrent_hash] = (rows, delay_polls)
        torrent = self.torrents.get(torrent_hash)
        if torrent is not None:
            self._attach_metadata(torrent)

    def _attach_metadata(self, torrent: FakeTorrent) -> None:
        known = self._metadata.get(torrent.hash)
        if known is None:
            return
        rows, delay = known
        patterns = []
        if self.preferences.get("excluded_file_names_enabled"):
            patterns = [
                p.strip().casefold() for p in self.preferences["excluded_file_names"].split("\n")
            ]
        torrent.files = [
            dict(row, priority=0)
            if any(fnmatch.fnmatchcase(row["name"].casefold(), p) for p in patterns if p)
            else dict(row)
            for row in rows
        ]
        torrent.polls_left = delay

    def _form(self, request: httpx.Request) -> dict[str, str]:
        return dict(parse_qsl(request.content.decode()))

    def _torrents_add(self, request: httpx.Request) -> httpx.Response:
        form = self._form(request)
        url = form.get("urls", "")
        category = form.get("category", "")
        if not url:
            return httpx.Response(400, text="Bad Request")
        is_magnet = url.lower().startswith("magnet:")
        torrent_hash = self.hash_for(url)
        if torrent_hash in self.torrents:
            return httpx.Response(409, text="Conflict")
        if category and category not in self.category_table:
            # The real engine creates any category it is given (research Pitfall 4).
            self.category_table[category] = {"name": category, "savePath": ""}
        tags = [t.strip() for t in form.get("tags", "").split(",") if t.strip()]
        torrent = FakeTorrent(torrent_hash, url, category, tags, self.clock())
        # A magnet added fully stopped never fetches its metadata (research Pitfall 1).
        stopped = form.get("stopped", "").lower() == "true"
        blocked = is_magnet and stopped
        if not is_magnet:
            if not form.get("downloader"):
                # Without the plugin's downloader a page URL never becomes a torrent.
                return httpx.Response(
                    202,
                    json={
                        "added_torrent_ids": [],
                        "failure_count": 0,
                        "pending_count": 1,
                        "success_count": 0,
                    },
                )
            self._pending_downloads.append([self.downloader_delay_calls, torrent])
            if not blocked:
                self._attach_metadata(torrent)
            return httpx.Response(
                202,
                json={
                    "added_torrent_ids": [],
                    "failure_count": 0,
                    "pending_count": 1,
                    "success_count": 0,
                },
            )
        self.torrents[torrent_hash] = torrent
        if not blocked:
            self._attach_metadata(torrent)
        return httpx.Response(
            200,
            json={
                "added_torrent_ids": [torrent_hash],
                "failure_count": 0,
                "pending_count": 0,
                "success_count": 1,
            },
        )

    def _release_downloads(self) -> None:
        for pending in list(self._pending_downloads):
            if pending[0] > 0:
                pending[0] -= 1
            else:
                self._pending_downloads.remove(pending)
                self.torrents[pending[1].hash] = pending[1]

    def _info_row(self, torrent: FakeTorrent) -> dict:
        return {
            "hash": torrent.hash,
            "name": torrent.hash,
            "category": torrent.category,
            "tags": ", ".join(torrent.tags),
            "added_on": int(torrent.added_on),
            "state": "downloading" if torrent.started else "stoppedDL",
            "downloaded": torrent.downloaded,
        }

    def _torrents_info(self, request: httpx.Request) -> httpx.Response:
        self._release_downloads()
        params = request.url.params
        wanted = params.get("hashes")
        rows = []
        for torrent in self.torrents.values():
            if wanted is not None and torrent.hash not in wanted.split("|"):
                continue
            if "tag" in params and params["tag"] not in torrent.tags:
                continue
            if "category" in params and params["category"] != torrent.category:
                continue
            rows.append(self._info_row(torrent))
        return httpx.Response(200, json=rows)

    def _torrents_files(self, request: httpx.Request) -> httpx.Response:
        torrent = self.torrents.get(request.url.params.get("hash", ""))
        if torrent is None or self.files_404_calls > 0:
            self.files_404_calls = max(0, self.files_404_calls - 1)
            return httpx.Response(404, text="Not Found")
        if torrent.files is None:
            return httpx.Response(200, json=[])
        if torrent.polls_left > 0:
            torrent.polls_left -= 1
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=torrent.files)

    def _torrents_file_prio(self, request: httpx.Request) -> httpx.Response:
        form = self._form(request)
        torrent = self.torrents.get(form.get("hash", ""))
        if torrent is None:
            return httpx.Response(404, text="Not Found")
        ids = [i for i in form.get("id", "").split("|") if i]
        files = torrent.files or []
        if not ids or not all(i.isdigit() and int(i) < len(files) for i in ids):
            return httpx.Response(409, text="File ID is not valid")
        for raw in ids:
            if int(raw) not in self.ignore_prio_ids:
                files[int(raw)]["priority"] = int(form.get("priority", "1"))
        return httpx.Response(200)

    def _torrents_start(self, request: httpx.Request) -> httpx.Response:
        for torrent_hash in self._form(request).get("hashes", "").split("|"):
            if torrent_hash in self.torrents:
                self.torrents[torrent_hash].started = True
        return httpx.Response(200)

    def _torrents_delete(self, request: httpx.Request) -> httpx.Response:
        form = self._form(request)
        if "deleteFiles" not in form:
            return httpx.Response(400, text="Bad Request")
        for torrent_hash in form.get("hashes", "").split("|"):
            if self.torrents.pop(torrent_hash, None) is not None:
                self.deleted.append((torrent_hash, form["deleteFiles"] == "true"))
        return httpx.Response(200)

    def _torrents_remove_tags(self, request: httpx.Request) -> httpx.Response:
        form = self._form(request)
        gone = {t.strip() for t in form.get("tags", "").split(",")}
        for torrent_hash in form.get("hashes", "").split("|"):
            torrent = self.torrents.get(torrent_hash)
            if torrent is not None:
                torrent.tags = [t for t in torrent.tags if t not in gone]
        return httpx.Response(200)

    def _torrents_delete_tags(self, request: httpx.Request) -> httpx.Response:
        gone = {t.strip() for t in self._form(request).get("tags", "").split(",")}
        for torrent in self.torrents.values():
            torrent.tags = [t for t in torrent.tags if t not in gone]
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
