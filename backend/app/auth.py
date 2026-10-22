"""Access control for the portal (AUTH-01, D-15..D-18).

One shared household account from the environment. Every feature router must be
built with `protected_router()` so it is born behind `require_user`; the only
public routes are POST /api/login and GET /api/health (guarded by a test).
"""

import hmac
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
    """RED stub: allows everything. Replaced by the real limiter in the GREEN commit."""

    def __init__(self, max_attempts: int = 5, window_seconds: float = 900, clock=None) -> None:  # type: ignore[no-untyped-def]
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds

    def try_acquire(self, ip: str) -> float | None:
        return None

    def reset(self, ip: str) -> None:
        return None
