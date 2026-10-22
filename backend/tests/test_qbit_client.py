"""QbitClient session handling: one login, one shared re-login, cool-downs, no leaks (SEC-01)."""

import asyncio
import logging
from urllib.parse import parse_qs

import httpx
import pytest
import respx
from pydantic import SecretStr

from app.config import Settings
from app.main import create_app
from app.qbit.client import QbitAuthError, QbitBanned, QbitClient, QbitUnavailable
from tests.conftest import QBIT_PASS, QBIT_URL, QBIT_USER
from tests.fakeqbit import FakeQbit

LOGIN_COOLDOWN = 900
BAN_COOLDOWN = 3600


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


def make_client(
    fake: FakeQbit, clock: FakeClock | None = None, password: str = QBIT_PASS
) -> QbitClient:
    return QbitClient(
        QBIT_URL,
        QBIT_USER,
        SecretStr(password),
        transport=fake.transport,
        clock=clock or FakeClock(),
    )


async def test_three_consecutive_calls_perform_exactly_one_login(fake_qbit: FakeQbit) -> None:
    client = make_client(fake_qbit)

    versions = [await client.webapi_version() for _ in range(3)]

    assert versions == ["2.15.1"] * 3
    assert fake_qbit.logins == 1
    await client.aclose()


async def test_concurrent_calls_after_expiry_share_exactly_one_relogin(
    fake_qbit: FakeQbit,
) -> None:
    client = make_client(fake_qbit)
    await client.webapi_version()
    assert fake_qbit.logins == 1

    fake_qbit.expire_sessions()
    results = await asyncio.gather(*(client.webapi_version() for _ in range(10)))

    assert results == ["2.15.1"] * 10
    assert fake_qbit.logins == 2
    await client.aclose()


async def test_wrong_password_cooldown_blocks_logins_without_network_io(
    fake_qbit: FakeQbit, clock: FakeClock
) -> None:
    client = make_client(fake_qbit, clock, password="not-the-password")

    with pytest.raises(QbitAuthError):
        await client.webapi_version()
    assert fake_qbit.login_attempts == 1
    requests_before = len(fake_qbit.calls)

    clock.now += LOGIN_COOLDOWN - 1
    with pytest.raises(QbitAuthError):
        await client.webapi_version()
    assert len(fake_qbit.calls) == requests_before

    clock.now += 2  # past the cool-down
    with pytest.raises(QbitAuthError):
        await client.webapi_version()
    assert fake_qbit.login_attempts == 2
    await client.aclose()


async def test_ban_cooldown_blocks_calls_for_an_hour(fake_qbit: FakeQbit, clock: FakeClock) -> None:
    fake_qbit.ban_after = 0  # every login answers 403
    client = make_client(fake_qbit, clock)

    with pytest.raises(QbitBanned):
        await client.webapi_version()
    requests_before = len(fake_qbit.calls)

    clock.now += BAN_COOLDOWN - 1
    with pytest.raises(QbitBanned):
        await client.webapi_version()
    assert len(fake_qbit.calls) == requests_before

    clock.now += 2
    with pytest.raises(QbitBanned):
        await client.webapi_version()
    assert fake_qbit.login_attempts == 2
    await client.aclose()


async def test_connection_refused_is_unavailable_and_never_starts_a_cooldown() -> None:
    attempts = 0

    def refuse(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError("refused", request=request)

    client = QbitClient(
        QBIT_URL, QBIT_USER, SecretStr(QBIT_PASS), transport=httpx.MockTransport(refuse)
    )

    for expected in (1, 2):
        with pytest.raises(QbitUnavailable):
            await client.webapi_version()
        assert attempts == expected
    await client.aclose()


async def test_login_wire_format_is_a_plain_form_without_referer_or_origin() -> None:
    with respx.mock(base_url=QBIT_URL, assert_all_called=False) as router:
        login = router.post("/api/v2/auth/login").respond(
            204, headers={"set-cookie": "QBT_SID_8088=abc123; HttpOnly; path=/"}
        )
        version = router.get("/api/v2/app/webapiVersion").respond(200, text="2.15.1")
        client = QbitClient(QBIT_URL, QBIT_USER, SecretStr(QBIT_PASS))

        await client.webapi_version()
        await client.aclose()

    request = login.calls.last.request
    assert request.headers["content-type"] == "application/x-www-form-urlencoded"
    assert set(parse_qs(request.content.decode())) == {"username", "password"}
    for sent in (request, version.calls.last.request):
        assert "referer" not in sent.headers
        assert "origin" not in sent.headers


async def test_health_degraded_on_auth_error_and_logs_no_credentials(
    settings: Settings, fake_qbit: FakeQbit, caplog: pytest.LogCaptureFixture
) -> None:
    wrong = "wrong-password-xyz"
    client = make_client(fake_qbit, password=wrong)
    app = create_app(settings, client)
    caplog.set_level(logging.DEBUG)

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://portal.test") as api:
            response = await api.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "degraded", "qbittorrent": "down"}
    assert "QbitAuthError" in caplog.text
    for secret in (QBIT_PASS, wrong, QBIT_USER):
        assert secret not in caplog.text


async def test_repr_shows_no_password_or_secretstr(fake_qbit: FakeQbit) -> None:
    client = make_client(fake_qbit)

    for text in (repr(client), str(client)):
        assert QBIT_PASS not in text
        assert "SecretStr('" not in text
    await client.aclose()


# --- configuration endpoints used by bootstrap (01-06) ---------------------------------------


async def test_set_preferences_posts_one_json_form_field(fake_qbit: FakeQbit) -> None:
    client = make_client(fake_qbit)

    await client.set_preferences({"auto_tmm_enabled": True, "max_ratio": 1.0})

    call = fake_qbit.calls_to("/api/v2/app/setPreferences")[0]
    assert set(call.form) == {"json"}
    assert fake_qbit.preferences["max_ratio"] == 1.0
    await client.aclose()


async def test_create_category_sends_name_and_save_path_and_reports_conflict(
    fake_qbit: FakeQbit,
) -> None:
    client = make_client(fake_qbit)

    first = await client.create_category("Film", "/media/Film")
    second = await client.create_category("Film", "/media/Film")

    forms = [c.form for c in fake_qbit.calls_to("/api/v2/torrents/createCategory")]
    assert (first, second) == (True, False)
    assert all(set(form) == {"category", "savePath"} for form in forms)
    await client.aclose()


async def test_configuration_error_carries_status_but_not_the_response_body(
    fake_qbit: FakeQbit,
) -> None:
    from app.qbit.client import QbitError

    fake_qbit.register(
        "GET", "/api/v2/app/preferences", lambda r: httpx.Response(500, text="secret-body-text")
    )
    client = make_client(fake_qbit)

    with pytest.raises(QbitError) as caught:
        await client.get_preferences()

    assert "500" in str(caught.value)
    assert "secret-body-text" not in str(caught.value)
    await client.aclose()
