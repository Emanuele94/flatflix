"""Async qBittorrent WebAPI v2 client (SEC-01).

One `httpx.AsyncClient` holds the session cookie (`QBT_SID_<port>`) in its jar.
The client never sets Referer or Origin (qBittorrent rejects a foreign one) and
never logs or reprs the password.
"""

import asyncio
import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import httpx
from pydantic import SecretStr

from app.config import Settings


class QbitError(Exception):
    """Base class for every qBittorrent access failure.

    `status` is the HTTP status when qBittorrent answered with one (never the body).
    """

    def __init__(self, *args: object, status: int | None = None) -> None:
        super().__init__(*args)
        self.status = status


class QbitUnavailable(QbitError):
    """qBittorrent cannot be reached or answered unexpectedly."""


class QbitAuthError(QbitError):
    """qBittorrent refused the configured credentials."""


class QbitBanned(QbitError):
    """qBittorrent banned this client's IP after too many failed logins."""


@dataclass(frozen=True, slots=True)
class AddResult:
    """qBittorrent's answer to `torrents/add`.

    `added_ids` holds the hashes of magnets added right away; a downloader-flow add (a plugin
    page URL) answers 202 with no hash and `pending` 1, so the caller finds it by tag.
    """

    status_code: int
    added_ids: tuple[str, ...]
    pending: int


def _pipe(values: str | Sequence[str]) -> str:
    return values if isinstance(values, str) else "|".join(values)


class QbitClient:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: SecretStr,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 10.0,
        login_cooldown_seconds: float = 900,
        ban_cooldown_seconds: float = 3600,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._login_cooldown = login_cooldown_seconds
        self._ban_cooldown = ban_cooldown_seconds
        self._clock = clock
        self._logged_in = False
        # Counts successful logins; a caller that waited on the lock uses it to see
        # that another caller already refreshed the session.
        self._session_epoch = 0
        self._login_lock = asyncio.Lock()
        # While blocked, no login (and so no request) leaves this process.
        self._login_blocked_until = 0.0
        self._blocked_error: type[QbitError] | None = None
        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            transport=transport,
            timeout=timeout,
            follow_redirects=False,
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> "QbitClient":
        return cls(
            settings.qbittorrent_url,
            settings.qbittorrent_user,
            settings.qbittorrent_pass,
        )

    def __repr__(self) -> str:
        return f"QbitClient(base_url={self._base_url!r}, username={self._username!r})"

    async def _login(self) -> None:
        try:
            response = await self._http.post(
                "/api/v2/auth/login",
                data={
                    "username": self._username,
                    "password": self._password.get_secret_value(),
                },
            )
        except httpx.TransportError as exc:
            raise QbitUnavailable("qBittorrent is unreachable") from exc
        status = response.status_code
        if status in (200, 204) and response.text.strip() != "Fails.":
            self._logged_in = True
            self._session_epoch += 1
            self._blocked_error = None
            return
        self._logged_in = False
        if status == 403:
            self._block(QbitBanned, self._ban_cooldown)
            raise QbitBanned("qBittorrent refused the login (client IP banned)")
        if status == 401 or status == 200:
            self._block(QbitAuthError, self._login_cooldown)
            raise QbitAuthError("qBittorrent rejected the configured credentials")
        raise QbitUnavailable(f"qBittorrent login answered HTTP {status}")

    def _block(self, error: type[QbitError], seconds: float) -> None:
        self._blocked_error = error
        self._login_blocked_until = self._clock() + seconds

    def _raise_if_blocked(self) -> None:
        if self._blocked_error is not None and self._clock() < self._login_blocked_until:
            raise self._blocked_error("qBittorrent login is paused after a refused login")

    async def _ensure_session(self, seen_epoch: int) -> None:
        """Log in at most once for all callers that saw the same stale session."""
        async with self._login_lock:
            if self._session_epoch != seen_epoch:
                return  # another caller refreshed the session while this one waited
            self._raise_if_blocked()
            await self._login()

    async def _send(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            return await self._http.request(method, path, **kwargs)
        except httpx.TransportError as exc:
            raise QbitUnavailable("qBittorrent is unreachable") from exc

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        epoch = self._session_epoch
        if not self._logged_in:
            await self._ensure_session(epoch)
        epoch = self._session_epoch
        response = await self._send(method, path, **kwargs)
        if response.status_code == 403:
            # Expired session: one shared re-login and one retry, never a loop.
            await self._ensure_session(epoch)
            response = await self._send(method, path, **kwargs)
        return response

    async def webapi_version(self) -> str:
        response = await self._request("GET", "/api/v2/app/webapiVersion")
        if response.status_code != 200:
            raise QbitUnavailable(f"qBittorrent answered HTTP {response.status_code}")
        return response.text.strip()

    async def _checked(self, method: str, path: str, **kwargs) -> httpx.Response:
        """Like `_request`, but a non-2xx answer raises `QbitError` without its body."""
        response = await self._request(method, path, **kwargs)
        if not response.is_success:
            raise QbitError(
                f"qBittorrent answered HTTP {response.status_code}", status=response.status_code
            )
        return response

    async def get_preferences(self) -> dict:
        response = await self._checked("GET", "/api/v2/app/preferences")
        return response.json()

    async def set_preferences(self, prefs: dict) -> None:
        await self._checked("POST", "/api/v2/app/setPreferences", data={"json": json.dumps(prefs)})

    async def categories(self) -> dict[str, dict]:
        response = await self._checked("GET", "/api/v2/torrents/categories")
        return response.json()

    async def create_category(self, name: str, save_path: str) -> bool:
        """Create a category; False when qBittorrent says it already exists (HTTP 409)."""
        response = await self._request(
            "POST",
            "/api/v2/torrents/createCategory",
            data={"category": name, "savePath": save_path},
        )
        if response.status_code == 409:
            return False
        if not response.is_success:
            raise QbitError(
                f"qBittorrent answered HTTP {response.status_code}", status=response.status_code
            )
        return True

    async def edit_category(self, name: str, save_path: str) -> None:
        await self._checked(
            "POST",
            "/api/v2/torrents/editCategory",
            data={"category": name, "savePath": save_path},
        )

    async def search_plugins(self) -> list[dict]:
        response = await self._checked("GET", "/api/v2/search/plugins")
        return response.json()

    async def install_search_plugin(self, url: str) -> None:
        await self._checked("POST", "/api/v2/search/installPlugin", data={"sources": url})

    async def search_start(self, pattern: str, category: str, plugins: str = "enabled") -> int:
        """Start a plugin search and return qBittorrent's integer search id."""
        response = await self._checked(
            "POST",
            "/api/v2/search/start",
            data={"pattern": pattern, "category": category, "plugins": plugins},
        )
        try:
            return int(response.json()["id"])
        except (ValueError, KeyError, TypeError) as exc:
            raise QbitUnavailable(
                "qBittorrent answered search/start with an unexpected body"
            ) from exc

    async def search_status(self, search_id: int | None = None) -> list[dict]:
        """Status rows of one search, or of every search when no id is given."""
        params = {} if search_id is None else {"id": search_id}
        response = await self._checked("GET", "/api/v2/search/status", params=params)
        return response.json()

    async def search_results(self, search_id: int, limit: int = 0, offset: int = 0) -> dict:
        """`{results, status, total}`; limit 0 means every row received so far."""
        response = await self._checked(
            "GET",
            "/api/v2/search/results",
            params={"id": search_id, "limit": limit, "offset": offset},
        )
        return response.json()

    async def search_stop(self, search_id: int) -> None:
        await self._search_idempotent("/api/v2/search/stop", search_id)

    async def search_delete(self, search_id: int) -> None:
        await self._search_idempotent("/api/v2/search/delete", search_id)

    async def _search_idempotent(self, path: str, search_id: int) -> None:
        """Stop or delete; a search qBittorrent no longer knows (404) is already gone."""
        response = await self._request("POST", path, data={"id": search_id})
        if response.status_code == 404:
            return
        if not response.is_success:
            raise QbitError(
                f"qBittorrent answered HTTP {response.status_code}", status=response.status_code
            )

    # -- torrents --------------------------------------------------------------------------
    # There is deliberately no method that changes the category of a torrent: the category is
    # chosen once, from the fixed server map, when the torrent is added (SEC-03).

    async def add_torrent(
        self,
        url: str,
        category: str,
        tags: Sequence[str],
        downloader: str | None = None,
    ) -> AddResult:
        """Add one URL, with nothing downloaded before the caller has filtered it (D-23).

        One form serves every route: `stopCondition=MetadataReceived`, never the stopped field.
        A magnet (direct, or printed by a plugin downloader, which reuses the add params of this
        request) fetches its file list and then stops itself. A torrent that already has its
        metadata at add (a .torrent the downloader or qBittorrent fetched) is added paused by
        qBittorrent itself under this condition (5.2.4 sessionimpl.cpp:2794-2801). A fully
        stopped add is never used: a plugin downloader may print a magnet, and a stopped magnet
        never fetches its metadata (research Pitfall 1, UAT gap G-01-3).
        `autoTMM=true` makes the category's save path apply (Pitfall 2). `downloader` names the
        search plugin for a URL that is not a magnet (Pitfall 5). Returns the status code
        without raising for 409 (already present) and 415 so the caller can word the outcome.
        """
        if "\n" in url or "\r" in url:
            raise ValueError("a torrent URL must be a single line")
        form = {
            "urls": url,
            "category": category,
            "autoTMM": "true",
            "tags": ",".join(tags),
            "stopCondition": "MetadataReceived",
        }
        if downloader is not None:
            form["downloader"] = downloader
        response = await self._request("POST", "/api/v2/torrents/add", data=form)
        added: tuple[str, ...] = ()
        pending = 0
        if response.is_success:
            try:
                body = response.json()
                added = tuple(str(h) for h in body.get("added_torrent_ids") or ())
                pending = int(body.get("pending_count") or 0)
            except (ValueError, AttributeError, TypeError):
                pass  # an old or odd body: the caller falls back to finding the torrent by tag
        return AddResult(response.status_code, added, pending)

    async def torrents_info(
        self,
        hashes: str | Sequence[str] | None = None,
        tag: str | None = None,
        category: str | None = None,
    ) -> list[dict]:
        params: dict[str, str] = {}
        if hashes is not None:
            params["hashes"] = _pipe(hashes)
        if tag is not None:
            params["tag"] = tag
        if category is not None:
            params["category"] = category
        response = await self._checked("GET", "/api/v2/torrents/info", params=params)
        return response.json()

    async def torrent_files(self, torrent_hash: str) -> list[dict]:
        """File rows of a torrent; an empty list means its metadata has not arrived yet."""
        response = await self._checked(
            "GET", "/api/v2/torrents/files", params={"hash": torrent_hash}
        )
        return response.json()

    async def set_file_priority(self, torrent_hash: str, ids: Sequence[int], priority: int) -> None:
        if not ids:
            return
        await self._checked(
            "POST",
            "/api/v2/torrents/filePrio",
            data={
                "hash": torrent_hash,
                "id": "|".join(str(i) for i in ids),
                "priority": str(priority),
            },
        )

    async def start(self, hashes: str | Sequence[str]) -> None:
        await self._checked("POST", "/api/v2/torrents/start", data={"hashes": _pipe(hashes)})

    async def delete(self, hashes: str | Sequence[str], delete_files: bool) -> None:
        # `deleteFiles` is always sent: qBittorrent answers 400 without it.
        await self._checked(
            "POST",
            "/api/v2/torrents/delete",
            data={"hashes": _pipe(hashes), "deleteFiles": "true" if delete_files else "false"},
        )

    async def remove_tags(self, hashes: str | Sequence[str], tags: Sequence[str]) -> None:
        await self._checked(
            "POST",
            "/api/v2/torrents/removeTags",
            data={"hashes": _pipe(hashes), "tags": ",".join(tags)},
        )

    async def delete_tags(self, tags: Sequence[str]) -> None:
        await self._checked("POST", "/api/v2/torrents/deleteTags", data={"tags": ",".join(tags)})

    async def aclose(self) -> None:
        await self._http.aclose()
