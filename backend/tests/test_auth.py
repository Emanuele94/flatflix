"""Shared-account login, session cookie and logout (AUTH-01, D-15, D-16)."""

import httpx

from tests.conftest import PORTAL_PASSWORD, PORTAL_USER, log_in


async def test_login_sets_a_30_day_httponly_lax_cookie(api: httpx.AsyncClient) -> None:
    response = await api.post(
        "/api/login", json={"username": PORTAL_USER, "password": PORTAL_PASSWORD}
    )

    assert response.status_code == 204
    cookie = response.headers["set-cookie"].lower()
    assert cookie.startswith("flatflix_session=")
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "max-age=2592000" in cookie
    assert "path=/" in cookie


async def test_wrong_user_and_wrong_password_get_the_same_401(api: httpx.AsyncClient) -> None:
    wrong_user = await api.post(
        "/api/login", json={"username": "someone", "password": PORTAL_PASSWORD}
    )
    wrong_password = await api.post(
        "/api/login", json={"username": PORTAL_USER, "password": "not the password"}
    )

    assert wrong_user.status_code == wrong_password.status_code == 401
    assert wrong_user.json() == wrong_password.json() == {"detail": "bad_credentials"}
    assert "set-cookie" not in wrong_user.headers
    assert "set-cookie" not in wrong_password.headers


async def test_session_survives_a_second_request(api: httpx.AsyncClient) -> None:
    await log_in(api)

    first = await api.get("/api/session")
    second = await api.get("/api/session")

    assert first.status_code == second.status_code == 200
    assert second.json() == {"logged_in": True}


async def test_logout_clears_the_session(api: httpx.AsyncClient) -> None:
    await log_in(api)

    logout = await api.post("/api/logout")
    after = await api.get("/api/session")

    assert logout.status_code == 204
    assert after.status_code == 401
    assert after.json() == {"detail": "not_authenticated"}


async def test_session_without_cookie_is_401(api: httpx.AsyncClient) -> None:
    response = await api.get("/api/session")

    assert response.status_code == 401
    assert response.json() == {"detail": "not_authenticated"}


async def test_forged_cookie_is_401(api: httpx.AsyncClient) -> None:
    api.cookies.set("flatflix_session", "eyJhdXRoIjogeyJ2IjogMX19.forged.signature")

    response = await api.get("/api/session")

    assert response.status_code == 401


async def test_form_encoded_login_is_422(api: httpx.AsyncClient) -> None:
    response = await api.post(
        "/api/login", data={"username": PORTAL_USER, "password": PORTAL_PASSWORD}
    )

    assert response.status_code == 422
    assert "set-cookie" not in response.headers


async def test_unknown_login_field_is_422(api: httpx.AsyncClient) -> None:
    response = await api.post(
        "/api/login",
        json={"username": PORTAL_USER, "password": PORTAL_PASSWORD, "admin": True},
    )

    assert response.status_code == 422
