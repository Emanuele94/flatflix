"""Access control for the portal (AUTH-01, D-15..D-18).

One shared household account from the environment. Every feature router must be
built with `protected_router()` so it is born behind `require_user`; the only
public routes are POST /api/login and GET /api/health (guarded by a test).
"""

import hmac
import time
from collections import deque
from collections.abc import Callable
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from app.config import Settings

SESSION_COOKIE = "flatflix_session"
SESSION_VALUE = {"v": 1}

_hasher = PasswordHasher()


def require_user(request: Request) -> None:
    """Deny unless the signed session carries the login marker."""
    if request.session.get("auth") != SESSION_VALUE:
        raise HTTPException(status_code=401, detail="not_authenticated")


def protected_router(**kwargs: Any) -> APIRouter:
    """Router under /api where every route requires a logged-in session."""
    return APIRouter(prefix="/api", dependencies=[Depends(require_user)], **kwargs)


def _verify_hash(stored_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(stored_hash, password)
    except (VerificationError, InvalidHashError):
        return False


async def verify_credentials(settings: Settings, username: str, password: str) -> bool:
    """Check the shared account.

    The argon2 verify ALWAYS runs, whichever field is wrong, so timing does not
    reveal whether the username exists. It runs in a thread to keep the event
    loop free.
    """
    user_ok = hmac.compare_digest(username.encode("utf-8"), settings.app_user.encode("utf-8"))
    password_ok = await run_in_threadpool(
        _verify_hash, settings.app_pass_hash.get_secret_value(), password
    )
    return user_ok and password_ok


class LoginThrottle:
    """Sliding-window limit on login attempts: per address, plus one ceiling for all (D-18).

    `try_acquire` checks and records in one synchronous step with no `await`
    in between, so concurrent requests cannot all slip past the limit: a slot is
    reserved BEFORE the slow argon2 check runs. State is in memory; a restart
    clears it, which is acceptable for a one-account household LAN portal.

    Two limits apply (WR-07):

    - per address, `max_attempts` per window. When every client shows up as the same address
      (a NAT or a proxy that hides the real one), that address is the whole household, and one
      person typing the wrong password `max_attempts` times blocks everybody until the window
      ends. A correct login clears the counter of its address.
    - across all addresses, `global_max_attempts` per window, so guesses spread over many
      addresses (or a proxy header that cannot be trusted) stay bounded. Only attempts that are
      allowed are recorded, so the state never holds more than this many entries.
    """

    def __init__(
        self,
        max_attempts: int = 5,
        window_seconds: float = 900,
        clock: Callable[[], float] = time.monotonic,
        global_max_attempts: int | None = None,
    ) -> None:
        self.max_attempts = max_attempts
        self.global_max_attempts = global_max_attempts
        self.window_seconds = window_seconds
        self._clock = clock
        self._attempts: dict[str, deque[float]] = {}
        self._all: deque[tuple[float, str]] = deque()

    def try_acquire(self, ip: str) -> float | None:
        """None: allowed and the slot is recorded. A float: seconds until a slot frees up."""
        now = self._clock()
        cutoff = now - self.window_seconds
        while self._all and self._all[0][0] <= cutoff:
            self._all.popleft()
        attempts = self._attempts.get(ip)
        if attempts is not None:
            while attempts and attempts[0] <= cutoff:
                attempts.popleft()
            if not attempts:
                del self._attempts[ip]
                attempts = None
        waits = []
        if attempts is not None and len(attempts) >= self.max_attempts:
            waits.append(attempts[0] + self.window_seconds - now)
        if self.global_max_attempts is not None and len(self._all) >= self.global_max_attempts:
            waits.append(self._all[0][0] + self.window_seconds - now)
        if waits:
            return max(waits)
        if attempts is None:
            attempts = self._attempts[ip] = deque()
        attempts.append(now)
        self._all.append((now, ip))
        return None

    def reset(self, ip: str) -> None:
        """A correct login: forget the failed attempts of that address."""
        self._attempts.pop(ip, None)
        self._all = deque(entry for entry in self._all if entry[1] != ip)
