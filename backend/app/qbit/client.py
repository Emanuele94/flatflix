"""Async qBittorrent WebAPI v2 client (SEC-01).

One `httpx.AsyncClient` holds the session cookie (`QBT_SID_<port>`) in its jar.
The client never sets Referer or Origin (qBittorrent rejects a foreign one) and
never logs or reprs the password.
"""

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
            return
        if status == 403:
            raise QbitBanned("qBittorrent refused the login (client IP banned)")
        if status == 401 or status == 200:
            raise QbitAuthError("qBittorrent rejected the configured credentials")
        raise QbitUnavailable(f"qBittorrent login answered HTTP {status}")

    async def _send(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            return await self._http.request(method, path, **kwargs)
        except httpx.TransportError as exc:
            raise QbitUnavailable("qBittorrent is unreachable") from exc

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        if not self._logged_in:
            await self._login()
        response = await self._send(method, path, **kwargs)
        if response.status_code == 403:
            await self._login()
            response = await self._send(method, path, **kwargs)
        return response

    async def webapi_version(self) -> str:
        response = await self._request("GET", "/api/v2/app/webapiVersion")
        if response.status_code != 200:
            raise QbitUnavailable(f"qBittorrent answered HTTP {response.status_code}")
        return response.text.strip()

    async def aclose(self) -> None:
        await self._http.aclose()
