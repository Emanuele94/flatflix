"""Strict input for POST /api/search: only film or serie, and a clean 2..100 code point query.

Every rejected request must leave the qBittorrent call log without a `search/start` (SEC-03,
research Pitfall 4: qBittorrent would act on anything it is handed).
"""

import unicodedata

import httpx
import pytest

from app.config import Settings
from app.content_type import CONTENT_TYPES, PLUGIN_CATEGORY, qbit_category, save_path
from app.main import create_app
from app.qbit.client import QbitClient
from tests.conftest import log_in
from tests.fakeqbit import FakeQbit

START = "/api/v2/search/start"
MISSING = object()


def started(fake: FakeQbit) -> list:
    return fake.calls_to(START)


async def post(client: httpx.AsyncClient, body: dict) -> httpx.Response:
    return await client.post("/api/search", json=body)


@pytest.mark.parametrize(
    "bad_type",
    [
        MISSING,
        None,
        "",
        "Film",
        "FILM",
        " film",
        "film ",
        "film\u0000",
        "ｆｉｌｍ",  # fullwidth "film", no Unicode normalization
        "movies",
        "Serie",
        "serie\n",
        "tv",
        "SerieTV",
        0,
        ["film"],
    ],
    ids=repr,
)
async def test_type_other_than_the_exact_string_film_or_serie_is_422_and_no_qbit_call(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit, bad_type: object
) -> None:
    body: dict = {"q": "sintel"}
    if bad_type is not MISSING:
        body["type"] = bad_type

    response = await post(user_api, body)

    assert response.status_code == 422
    assert started(fake_qbit) == []


@pytest.mark.parametrize(
    "extra", [{"category": "Film"}, {"path": "/media/Film"}, {"plugins": "all"}]
)
async def test_extra_body_fields_are_422_and_no_qbit_call(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit, extra: dict
) -> None:
    response = await post(user_api, {"q": "sintel", "type": "film", **extra})

    assert response.status_code == 422
    assert started(fake_qbit) == []


async def test_non_json_bodies_are_422_and_no_qbit_call(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit
) -> None:
    form = await user_api.post("/api/search", data={"q": "sintel", "type": "film"})
    empty = await user_api.post("/api/search")

    assert form.status_code == 422
    assert empty.status_code == 422
    assert started(fake_qbit) == []


@pytest.mark.parametrize(
    "bad_query",
    [
        MISSING,
        None,
        123,
        "",
        "   ",
        "\t\n ",
        "a",
        " a ",
        "\u0000a",
        "\u200ba\u200b",  # zero-width space is category Cf
        "\u0000\u0000\u0000",
        "x" * 101,
        "é" * 101,
        "x" * 1001,
    ],
    ids=lambda value: repr(value)[:30],
)
async def test_empty_short_or_overlong_query_is_422_and_no_qbit_call(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit, bad_query: object
) -> None:
    body: dict = {"type": "film"}
    if bad_query is not MISSING:
        body["q"] = bad_query

    response = await post(user_api, body)

    assert response.status_code == 422
    assert started(fake_qbit) == []


async def test_hundred_accented_code_points_are_accepted_and_sent_unchanged(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit
) -> None:
    query = "è" * 100

    response = await post(user_api, {"q": query, "type": "film"})

    assert response.status_code == 200
    (call,) = started(fake_qbit)
    assert call.form["pattern"] == query


async def test_hundred_and_one_code_points_are_rejected(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit
) -> None:
    response = await post(user_api, {"q": "è" * 101, "type": "film"})

    assert response.status_code == 422
    assert started(fake_qbit) == []


async def test_length_counts_code_points_not_grapheme_clusters(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit
) -> None:
    decomposed = "e\u0301"  # one visible letter, two code points
    assert len(decomposed) == 2

    short = await post(user_api, {"q": decomposed, "type": "film"})
    too_long = await post(user_api, {"q": decomposed * 51, "type": "film"})

    assert short.status_code == 200
    assert too_long.status_code == 422
    assert len(started(fake_qbit)) == 1


async def test_control_and_format_characters_are_stripped_before_counting_and_sending(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit
) -> None:
    dirty = "\u200b  sin\u0000tel\u202e \u200d\ufeff\x1b "
    padded = "a" * 100 + "\u200b" * 50 + "\x00" * 50

    first = await post(user_api, {"q": dirty, "type": "film"})
    second = await post(user_api, {"q": padded, "type": "serie"})

    assert first.status_code == 200
    assert second.status_code == 200
    forms = [call.form["pattern"] for call in started(fake_qbit)]
    assert forms == ["sintel", "a" * 100]
    for pattern in forms:
        assert not any(unicodedata.category(ch) in ("Cc", "Cf") for ch in pattern)


async def test_inner_spacing_and_letters_are_otherwise_sent_unchanged(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit
) -> None:
    query = "Amélie  Poulain 2001"

    await post(user_api, {"q": query, "type": "film"})

    (call,) = started(fake_qbit)
    assert call.form["pattern"] == query


async def test_search_routes_answer_401_without_a_session(
    api: httpx.AsyncClient, fake_qbit: FakeQbit
) -> None:
    posted = await post(api, {"q": "sintel", "type": "film"})
    fetched = await api.get("/api/search/abc")

    for response in (posted, fetched):
        assert response.status_code == 401
        assert response.json() == {"detail": "not_authenticated"}
    assert started(fake_qbit) == []


async def test_search_routes_answer_503_not_ready_before_bootstrap(
    settings: Settings, fake_qbit: FakeQbit
) -> None:
    # qBittorrent never answers the version probe, so bootstrap stays in its retry loop.
    original = fake_qbit._routes[("GET", "/api/v2/app/webapiVersion")]

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    fake_qbit.register("GET", "/api/v2/app/webapiVersion", refuse)
    client = QbitClient(
        settings.qbittorrent_url,
        settings.qbittorrent_user,
        settings.qbittorrent_pass,
        transport=fake_qbit.transport,
    )
    app = create_app(settings, client)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://portal.test") as web:
            await log_in(web)
            posted = await post(web, {"q": "sintel", "type": "film"})
            fetched = await web.get("/api/search/abc")
            app.state.readiness.mark_ready()
            fake_qbit.register("GET", "/api/v2/app/webapiVersion", original)
            unknown = await web.get("/api/search/abc")

    for response in (posted, fetched):
        assert response.status_code == 503
        assert response.json() == {"detail": "not_ready"}
    assert started(fake_qbit) == []
    assert unknown.status_code == 404


def test_every_content_type_round_trips_through_the_fixed_maps(settings: Settings) -> None:
    expected = {
        "film": ("movies", "Film", "/media/Film"),
        "serie": ("tv", "SerieTV", "/media/SerieTV"),
    }

    # A third type cannot be added without updating every map.
    assert set(CONTENT_TYPES) == set(expected) == set(PLUGIN_CATEGORY)
    for content_type in CONTENT_TYPES:
        plugin_category, category, path = expected[content_type]
        assert PLUGIN_CATEGORY[content_type] == plugin_category
        assert qbit_category(settings, content_type) == category
        assert save_path(settings, content_type) == path
        assert settings.category_paths[category] == path


def test_an_unknown_type_has_no_category_or_path(settings: Settings) -> None:
    with pytest.raises(ValueError):
        qbit_category(settings, "movies")  # type: ignore[arg-type]
    with pytest.raises((ValueError, KeyError)):
        save_path(settings, "movies")  # type: ignore[arg-type]
