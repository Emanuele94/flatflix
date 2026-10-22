"""Deny by default: every API route needs a session except login and health (AUTH-01, T-01-16).

The app comes from the `app` fixture, so routers added by later plans are covered
without touching this file.
"""

import re

import httpx
from fastapi import APIRouter, Depends, FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute, RouteContext, iter_route_contexts

from app.auth import protected_router, require_user

# The only public routes of the whole API.
ALLOW_LIST = {("POST", "/api/login"), ("GET", "/api/health")}


def api_routes(app: FastAPI) -> list[RouteContext]:
    """Every route with its effective path and dependencies (router-level ones included).

    FastAPI 0.159 keeps included routers as nested objects in `app.routes`;
    `iter_route_contexts` flattens them.
    """
    contexts = list(iter_route_contexts(app.routes))
    for context in contexts:
        assert isinstance(context.original_route, APIRoute), (
            f"unexpected non-API route: {context.original_route!r}"
        )
    return contexts


def _chain(dependant: Dependant) -> list[object]:
    calls: list[object] = [dependant.call]
    for sub in dependant.dependencies:
        calls.extend(_chain(sub))
    return calls


def has_require_user(route: RouteContext) -> bool:
    return require_user in _chain(route.dependant)


def unprotected_routes(app: FastAPI) -> list[tuple[str, str]]:
    """(method, path) of every route that is neither allow-listed nor behind require_user."""
    found = []
    for route in api_routes(app):
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            if (method, route.path) in ALLOW_LIST:
                continue
            if not has_require_user(route):
                found.append((method, route.path))
    return found


def test_every_route_except_login_and_health_requires_a_session(app: FastAPI) -> None:
    assert unprotected_routes(app) == []


def test_the_guard_catches_an_unprotected_route() -> None:
    sneaky = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    router = APIRouter(prefix="/api")

    @router.get("/leak")
    async def leak() -> dict[str, str]:
        return {}

    safe = protected_router()

    @safe.get("/fine")
    async def fine() -> dict[str, str]:
        return {}

    @router.get("/dep", dependencies=[Depends(require_user)])
    async def dep() -> dict[str, str]:
        return {}

    sneaky.include_router(router)
    sneaky.include_router(safe)

    assert unprotected_routes(sneaky) == [("GET", "/api/leak")]


def test_every_route_lives_under_api(app: FastAPI) -> None:
    paths = [route.path for route in api_routes(app)]
    assert paths
    assert all(path.startswith("/api/") for path in paths)


async def test_protected_routes_answer_401_without_a_session(
    app: FastAPI, api: httpx.AsyncClient
) -> None:
    checked = 0
    for route in api_routes(app):
        path = re.sub(r"\{[^}]+\}", "x", route.path)
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            if (method, route.path) in ALLOW_LIST:
                continue
            response = await api.request(method, path, json={})
            assert response.status_code == 401, (method, route.path)
            assert response.json() == {"detail": "not_authenticated"}
            checked += 1
    assert checked >= 2  # at least /api/session and /api/logout
