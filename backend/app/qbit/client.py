"""Async qBittorrent WebAPI v2 client (SEC-01).

One `httpx.AsyncClient` holds the session cookie (`QBT_SID_<port>`) in its jar.
The client never sets Referer or Origin (qBittorrent rejects a foreign one) and
never logs or reprs the password.
"""

import asyncio
import json
import time
from collections.abc import Callable

import httpx
from pydantic import SecretStr

from app.config import Settings


class QbitError(Exception):
    """Base class for every qBittorrent access failure."""


class QbitUnavailable(QbitError):
    """qBittorrent cannot be reached or answered unexpectedly."""


class QbitAuthError(QbitError):
    """qBittorrent refused the configured credentials."""


class QbitBanned(QbitError):
    """qBittorrent banned this client's IP after too many failed logins."""


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
            raise QbitError(f"qBittorrent answered HTTP {response.status_code}")
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
            raise QbitError(f"qBittorrent answered HTTP {response.status_code}")
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

    async def aclose(self) -> None:
        await self._http.aclose()
