"""SEC-06: the audit trail (D-40, D-41) and the redaction of every log handler.

A StringIO handler with the production LOG_FORMAT is attached to the root logger before the app
is created, so `create_app` installs the redacting filter on it exactly as it does on the real
stdout handler. The tests read what that handler wrote.
"""

import asyncio
import io
import json
import logging
import logging.config
import re
import sys
import time
from collections.abc import Iterator

import httpx
import pytest
import uvicorn.config
from fastapi import FastAPI
from fastapi.routing import iter_route_contexts

from app import audit
from app.config import Settings
from app.main import LOG_FORMAT, create_app
from app.qbit.client import QbitClient
from app.throttle import SlidingWindowThrottle
from tests.conftest import (
    PORTAL_PASS_HASH,
    PORTAL_PASSWORD,
    PORTAL_USER,
    log_in,
    wait_for_bootstrap,
)
from tests.fakeqbit import FakeQbit

# The download rig (fake clock, cached result, pipeline) is shared with the pipeline tests.
from tests.test_download_pipeline import (  # noqa: F401
    BTIH,
    RESULT_ID,
    SINTEL_FILES,
    Rig,
    clock,
    rig,
)
from tests.test_no_leaks import (
    BTIH as CANARY_BTIH,
)
from tests.test_no_leaks import (
    CANARY_QBIT_PASS,
    CANARY_QBIT_USER,
    CANARY_SECRET_KEY,
    FILM_FILES,
    canary_settings,
    search_row,
)


class AuditLog:
    """The text of every log record emitted while the test ran."""

    def __init__(self) -> None:
        self.stream = io.StringIO()
        self.handler = logging.StreamHandler(self.stream)
        self.handler.setFormatter(logging.Formatter(LOG_FORMAT))

    @property
    def text(self) -> str:
        return self.stream.getvalue()

    @property
    def lines(self) -> list[str]:
        return self.text.splitlines()

    def audit_lines(self) -> list[str]:
        return [line for line in self.lines if " app.audit " in line]

    def events(self, name: str) -> list[dict[str, str]]:
        return [parse(line) for line in self.audit_lines() if f" event={name} " in line + " "]


FIELD = re.compile(r'(\w+)=("(?:[^"\\]|\\.)*"|\S+)')


def parse(line: str) -> dict[str, str]:
    """The key=value fields of an audit line; quoted values are decoded from their JSON form."""
    _, _, rest = line.partition(" app.audit ")
    return {
        key: json.loads(value) if value.startswith('"') else value
        for key, value in FIELD.findall(rest)
    }


@pytest.fixture
def audit_log() -> Iterator[AuditLog]:
    log = AuditLog()
    root = logging.getLogger()
    root.addHandler(log.handler)
    try:
        yield log
    finally:
        root.removeHandler(log.handler)


def build_app(settings: Settings, fake: FakeQbit) -> FastAPI:
    client = QbitClient(
        settings.qbittorrent_url,
        settings.qbittorrent_user,
        settings.qbittorrent_pass,
        transport=fake.transport,
    )
    return create_app(settings, client)


@pytest.fixture
def app(audit_log: AuditLog, settings: Settings, fake_qbit: FakeQbit) -> FastAPI:
    """Overrides the shared `app` so the log handler exists before `create_app` runs."""
    return build_app(settings, fake_qbit)


# -- tracer: a search leaves one audit line ------------------------------------------------------


async def test_a_search_writes_one_audit_line_with_ip_type_and_quoted_text(
    user_api: httpx.AsyncClient, audit_log: AuditLog
) -> None:
    response = await user_api.post("/api/search", json={"q": "sintel 1080p", "type": "film"})

    assert response.status_code == 200
    lines = [line for line in audit_log.audit_lines() if "event=search" in line]
    assert len(lines) == 1
    assert 'INFO app.audit event=search ip=127.0.0.1 type=film q="sintel 1080p"' in lines[0]


# -- the other events ----------------------------------------------------------------------------

HASH = "a" * 40


async def test_login_outcomes_are_audited_without_the_attempted_username(
    api: httpx.AsyncClient, audit_log: AuditLog, settings: Settings
) -> None:
    await log_in(api)
    assert (await api.post("/api/logout")).status_code == 204
    wrong = {"username": "nobody-" + PORTAL_USER, "password": "wrong-wrong"}
    for _ in range(settings.login_max_attempts):
        assert (await api.post("/api/login", json=wrong)).status_code == 401
    assert (await api.post("/api/login", json=wrong)).status_code == 429

    logins = audit_log.events("login")
    assert [event["outcome"] for event in logins] == (
        ["ok"] + ["fail"] * settings.login_max_attempts + ["throttled"]
    )
    assert all(set(event) == {"event", "ip", "outcome"} for event in logins)
    assert all(event["ip"] == "127.0.0.1" for event in logins)
    assert "nobody-" not in audit_log.text
    assert PORTAL_USER not in audit_log.text
    (logout,) = audit_log.events("logout")
    assert logout["ip"] == "127.0.0.1"


async def test_a_throttled_download_is_audited_with_its_scope(
    app: FastAPI, user_api: httpx.AsyncClient, audit_log: AuditLog
) -> None:
    app.state.download_throttle = SlidingWindowThrottle(max_attempts=1, window_seconds=60)
    body = {"result_id": RESULT_ID, "type": "film"}

    assert (await user_api.post("/api/download", json=body)).status_code == 410
    assert (await user_api.post("/api/download", json=body)).status_code == 429

    (event,) = audit_log.events("throttled")
    assert (event["ip"], event["scope"]) == ("127.0.0.1", "download")


async def test_a_throttled_search_is_audited_with_its_scope(
    app: FastAPI, user_api: httpx.AsyncClient, audit_log: AuditLog
) -> None:
    app.state.search_throttle = SlidingWindowThrottle(max_attempts=1, window_seconds=60)
    body = {"q": "sintel", "type": "film"}

    assert (await user_api.post("/api/search", json=body)).status_code == 200
    assert (await user_api.post("/api/search", json=body)).status_code == 429

    (event,) = audit_log.events("throttled")
    assert (event["ip"], event["scope"]) == ("127.0.0.1", "search")


async def test_a_started_download_is_audited_twice_joined_by_its_job_id(
    rig: Rig,  # noqa: F811
    audit_log: AuditLog,
) -> None:
    rig.cache()
    rig.fake.set_metadata(BTIH, SINTEL_FILES)

    posted = (await rig.post()).json()

    (requested,) = audit_log.events("download")
    (finished,) = audit_log.events("download_done")
    assert requested == {
        "event": "download",
        "ip": "127.0.0.1",
        "type": "film",
        "job_id": posted["job_id"],
        "name": "Sintel",
    }
    assert finished == {
        "event": "download_done",
        "job_id": posted["job_id"],
        "name": "Sintel",
        "outcome": "started",
    }
    lines = audit_log.audit_lines()
    assert lines.index(next(line for line in lines if "event=download " in line)) < lines.index(
        next(line for line in lines if "event=download_done" in line)
    )


async def test_a_rejected_download_ends_with_outcome_rejected(
    rig: Rig,  # noqa: F811
    audit_log: AuditLog,
) -> None:
    rig.cache()
    rig.fake.set_metadata(BTIH, [("Movie/setup.exe", 5000), ("Movie/readme.txt", 10)])

    await rig.post()

    (finished,) = audit_log.events("download_done")
    assert finished["outcome"] == "rejected"


async def test_a_cancelled_job_writes_no_download_done_line(
    rig: Rig,  # noqa: F811
    audit_log: AuditLog,
) -> None:
    rig.cache()  # a magnet that never gets its metadata: the job stays preparing
    rig.app.state.settings = rig.app.state.settings.model_copy(
        update={"download_wait_seconds": 0.05}
    )

    async def slow_sleep(seconds: float) -> None:
        rig.clock.now += seconds
        await asyncio.sleep(0.01)

    rig.use_sleep(slow_sleep)
    posted = (await rig.post()).json()
    assert posted["status"] == "preparing"
    (item,) = (await rig.api.get("/api/downloads")).json()["items"]

    assert (await rig.api.delete(f"/api/downloads/{item['id']}")).status_code == 204
    await asyncio.sleep(0.1)

    assert audit_log.events("download_done") == []
    (cancel,) = audit_log.events("cancel")
    assert (cancel["name"], cancel["outcome"], cancel["ip"]) == ("Sintel", "done", "127.0.0.1")


async def test_cancel_remove_and_not_found_are_audited_with_the_row_name(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit, audit_log: AuditLog
) -> None:
    fake_qbit.add_torrent_row(HASH, name="Half Film", state="downloading", progress=0.4)
    fake_qbit.add_torrent_row(
        "b" * 40,
        name="Done Film",
        state="stalledUP",
        progress=1.0,
        completion_on=int(time.time()) - 60,
    )
    items = (await user_api.get("/api/downloads")).json()["items"]
    by_name = {item["name"]: item["id"] for item in items}

    assert (await user_api.delete(f"/api/downloads/{by_name['Half Film']}")).status_code == 204
    assert (await user_api.delete(f"/api/downloads/{by_name['Done Film']}")).status_code == 204
    assert (await user_api.delete("/api/downloads/0123456789abcdef")).status_code == 404

    (cancel,) = [e for e in audit_log.events("cancel") if e["outcome"] == "done"]
    (remove,) = audit_log.events("remove")
    (missing,) = [e for e in audit_log.events("cancel") if e["outcome"] == "not_found"]
    assert (cancel["name"], cancel["ip"]) == ("Half Film", "127.0.0.1")
    assert (remove["name"], remove["outcome"], remove["ip"]) == ("Done Film", "done", "127.0.0.1")
    assert missing["name"] == "null"


async def test_a_qbit_outage_is_audited_as_an_error_with_class_and_status(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit, audit_log: AuditLog
) -> None:
    fake_qbit.unreachable = True

    assert (await user_api.get("/api/downloads")).status_code == 502
    assert (await user_api.delete("/api/downloads/0123456789abcdef")).status_code == 502
    assert (
        await user_api.post("/api/search", json={"q": "sintel", "type": "film"})
    ).status_code == 503

    listing, cancel, search = audit_log.events("error")
    assert (listing["where"], listing["exc"], listing["ip"]) == (
        "downloads",
        "QbitUnavailable",
        "127.0.0.1",
    )
    assert (cancel["where"], cancel["exc"], cancel["ip"]) == (
        "cancel",
        "QbitUnavailable",
        "127.0.0.1",
    )
    assert (search["where"], search["exc"], search["ip"]) == (
        "search",
        "QbitUnavailable",
        "127.0.0.1",
    )


async def test_every_request_scoped_audit_line_carries_the_client_ip(
    rig: Rig,  # noqa: F811
    audit_log: AuditLog,
) -> None:
    rig.cache()
    rig.fake.set_metadata(BTIH, SINTEL_FILES)
    await rig.api.post("/api/search", json={"q": "sintel", "type": "film"})
    await rig.post()
    (item,) = (await rig.api.get("/api/downloads")).json()["items"]
    await rig.api.delete(f"/api/downloads/{item['id']}")
    await rig.api.post("/api/logout")

    scoped = [e for e in map(parse, audit_log.audit_lines()) if e["event"] != "download_done"]
    assert len(scoped) >= 5
    assert all(event.get("ip") == "127.0.0.1" for event in scoped)


# -- sanitising ----------------------------------------------------------------------------------


def test_free_text_is_escaped_and_cut_so_it_never_starts_a_second_line(
    audit_log: AuditLog,
) -> None:
    forged = 'sintel\nevent=login ip=6.6.6.6 outcome=ok\r\x07 "quoted" ' + "x" * 300

    audit.search("203.0.113.7", "film", forged)

    (line,) = audit_log.lines
    assert "\n" not in line.rstrip("\n") and "\r" not in line
    event = parse(line)
    assert event["q"].startswith('sintel\nevent=login ip=6.6.6.6 outcome=ok\r\x07 "quoted" ')
    assert len(event["q"]) == audit.MAX_TEXT
    assert event["ip"] == "203.0.113.7"
    assert "\\n" in line  # the newline is written as an escape, not as a newline


def test_quarantine_events_escape_a_hostile_torrent_name_and_carry_no_path_or_hash(
    audit_log: AuditLog,
) -> None:
    forged = 'Movie "x"\nevent=login ip=6.6.6.6 outcome=ok\r ' + "y" * 300

    audit.quarantine_passed(forged, 2)
    audit.quarantine_rejected(
        forged, forged, "probe_failed", "matroska", "h264", "6000", 123, "8.1"
    )
    audit.quarantine_link_failed(forged, "EXDEV")
    audit.quarantine_seeding_done(forged)
    audit.quarantine_purged(3)

    lines = audit_log.lines
    assert len(lines) == 5  # one line each: the newline of the name never starts another
    for line in lines:
        assert "\r" not in line
        assert "/data" not in line
        assert not re.search(r"[0-9a-f]{40}", line)
    for event in (parse(line) for line in lines[:4]):
        assert event["name"].startswith('Movie "x"\nevent=login ip=6.6.6.6 outcome=ok\r ')
        assert len(event["name"]) == audit.MAX_TEXT
    rejected = parse(lines[1])
    assert rejected["reason"] == "probe_failed"
    assert (rejected["format"], rejected["codec"], rejected["duration"]) == (
        "matroska",
        "h264",
        "6000",
    )
    assert rejected["size"] == "123"
    assert parse(lines[4]) == {"event": "quarantine.purged", "count": "3"}


def test_an_address_is_bare_only_when_it_is_address_shaped(audit_log: AuditLog) -> None:
    audit.logout("2001:db8::1")
    audit.logout('1.2.3.4" event=login')

    first, second = audit_log.audit_lines()
    assert first.endswith("event=logout ip=2001:db8::1")
    assert second.endswith('event=logout ip="1.2.3.4\\" event=login"')


# -- redaction -----------------------------------------------------------------------------------

SECRET = "s3cr3t-value-0123456789"


def make_record(msg: str, args: object = None, exc_info: object = None) -> logging.LogRecord:
    return logging.LogRecord("x", logging.INFO, __file__, 1, msg, args, exc_info)  # type: ignore[arg-type]


def test_the_filter_replaces_secrets_in_message_args_and_cookies() -> None:
    redactor = audit.RedactingFilter([SECRET, "short"])

    by_arg = make_record("token %s", (SECRET,))
    by_message = make_record(f"token {SECRET} and short")
    sid = make_record("cookie QBT_SID_8088=abcdef; path=/")
    session = make_record("cookie flatflix_session=xyz.abc")
    mapping = make_record("%(a)s %(b)d", {"a": SECRET, "b": 3})

    for record in (by_arg, by_message, sid, session, mapping):
        assert redactor.filter(record) is True
    assert by_arg.getMessage() == "token [redacted]"
    assert by_message.getMessage() == "token [redacted] and short"  # under 8 chars: ignored
    assert sid.getMessage() == "cookie [redacted]; path=/"
    assert session.getMessage() == "cookie [redacted]"
    assert isinstance(mapping.args, dict)
    assert mapping.getMessage() == "[redacted] 3"


def test_the_filter_redacts_exception_text_and_non_string_args() -> None:
    redactor = audit.RedactingFilter([SECRET])
    try:
        raise RuntimeError(f"login failed for {SECRET}")
    except RuntimeError as exc:
        with_exception = make_record("boom", None, sys.exc_info())
        with_arg = make_record("failed: %s", (exc,))

    redactor.filter(with_exception)
    redactor.filter(with_arg)

    formatted = logging.Formatter(LOG_FORMAT).format(with_exception)
    assert "RuntimeError" in formatted
    assert SECRET not in formatted
    assert SECRET not in with_arg.getMessage()


def test_the_filter_redacts_a_message_that_is_an_exception_or_another_object() -> None:
    redactor = audit.RedactingFilter([SECRET])

    class Leaky:
        def __str__(self) -> str:
            return f"leaky {SECRET}"

    by_exception = make_record(RuntimeError(f"login failed for {SECRET}"))  # type: ignore[arg-type]
    by_object = make_record(Leaky())  # type: ignore[arg-type]
    clean = make_record(RuntimeError("nothing secret"))  # type: ignore[arg-type]
    original = clean.msg

    for record in (by_exception, by_object, clean):
        assert redactor.filter(record) is True

    assert by_exception.getMessage() == "login failed for [redacted]"
    assert by_object.getMessage() == "leaky [redacted]"
    assert clean.msg is original  # nothing to redact: formatting is unchanged


@pytest.fixture
def logging_state() -> Iterator[None]:
    """Restore handlers, filters, levels and propagation of the loggers a test reconfigures."""
    names = ["", "app.audit", *audit.UVICORN_LOGGERS]
    saved = {}
    for name in names:
        logger = logging.getLogger(name)
        saved[name] = (
            list(logger.handlers),
            [list(handler.filters) for handler in logger.handlers],
            logger.level,
            logger.propagate,
            logger.disabled,
        )
    try:
        yield
    finally:
        for name, (handlers, filters, level, propagate, disabled) in saved.items():
            logger = logging.getLogger(name)
            logger.handlers[:] = handlers
            for handler, kept in zip(handlers, filters, strict=True):
                handler.filters[:] = kept
            logger.setLevel(level)
            logger.propagate = propagate
            logger.disabled = disabled


def redactors(handler: logging.Handler) -> list[audit.RedactingFilter]:
    return [f for f in handler.filters if isinstance(f, audit.RedactingFilter)]


def test_every_root_and_uvicorn_handler_carries_exactly_one_filter(
    logging_state: None, settings: Settings, fake_qbit: FakeQbit, audit_log: AuditLog
) -> None:
    # What uvicorn does before the app factory runs: its own non-propagating handlers.
    logging.config.dictConfig(uvicorn.config.LOGGING_CONFIG)
    uvicorn_handlers = [
        handler
        for name in ("uvicorn", "uvicorn.access")
        for handler in logging.getLogger(name).handlers
    ]
    assert uvicorn_handlers, "uvicorn no longer configures its own handlers (RESEARCH A3)"
    assert logging.getLogger("uvicorn.access").propagate is False

    build_app(settings, fake_qbit)
    build_app(settings, fake_qbit)  # twice: the filters must not stack

    handlers = [*logging.getLogger().handlers, *uvicorn_handlers]
    assert audit_log.handler in handlers
    for handler in handlers:
        assert len(redactors(handler)) == 1, handler


def test_an_access_line_goes_through_uvicorns_own_formatter_redacted(
    logging_state: None, settings: Settings, fake_qbit: FakeQbit
) -> None:
    logging.config.dictConfig(uvicorn.config.LOGGING_CONFIG)
    build_app(settings, fake_qbit)
    (handler,) = logging.getLogger("uvicorn.access").handlers
    record = make_record(
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:5000", "GET", "/api/x?flatflix_session=abc123", "1.1", 200),
    )
    record.name = "uvicorn.access"

    assert handler.filter(record)
    shown = handler.format(record)

    assert "[redacted]" in shown
    assert "abc123" not in shown
    assert isinstance(record.args, tuple) and len(record.args) == 5


async def test_the_audit_trail_survives_log_level_warning(
    audit_log: AuditLog, settings: Settings, fake_qbit: FakeQbit
) -> None:
    quiet = settings.model_copy(update={"log_level": "WARNING"})
    app = build_app(quiet, fake_qbit)
    async with app.router.lifespan_context(app):
        await wait_for_bootstrap(app)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://portal.test") as http:
            await log_in(http)
            await http.post("/api/search", json={"q": "sintel", "type": "film"})
        logging.getLogger("app.download.pipeline").info("pipeline noise")

    assert [e["event"] for e in map(parse, audit_log.audit_lines())] == ["login", "search"]
    assert "pipeline noise" not in audit_log.text


# -- canary run ----------------------------------------------------------------------------------

TIMESTAMP = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3} ")
FORGED_NAME = "Sintel 1080p\nevent=login ip=6.6.6.6 outcome=ok"


async def test_canary_secrets_never_reach_a_log_line(audit_log: AuditLog) -> None:
    settings = canary_settings()
    fake = FakeQbit(CANARY_QBIT_USER, CANARY_QBIT_PASS)
    fake.script_search([[search_row(FORGED_NAME, 40)]])
    fake.set_metadata(CANARY_BTIH, FILM_FILES)
    app = build_app(settings, fake)
    seen_secrets: set[str] = set()

    async with app.router.lifespan_context(app):
        await wait_for_bootstrap(app)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://portal.test") as http:
            # The real password typed into the username box of a wrong login.
            wrong = await http.post(
                "/api/login", json={"username": PORTAL_PASSWORD, "password": "nope-nope"}
            )
            assert wrong.status_code == 401
            await log_in(http)
            session_cookie = http.cookies.get("flatflix_session")
            assert session_cookie

            started = await http.post(
                "/api/search",
                json={"q": "sintel\nevent=login ip=6.6.6.6 outcome=ok", "type": "film"},
            )
            assert started.status_code == 200
            rows: list[dict] = []
            for _ in range(10):
                snapshot = (await http.get(f"/api/search/{started.json()['search_id']}")).json()
                rows = snapshot["results"]
                if snapshot["done"]:
                    break
            assert rows, "the seeded result never reached the snapshot"
            download = await http.post(
                "/api/download", json={"result_id": rows[0]["result_id"], "type": "film"}
            )
            assert download.json()["status"] == "started"
            listing = (await http.get("/api/downloads")).json()["items"]
            assert (await http.delete(f"/api/downloads/{listing[0]['id']}")).status_code == 204

            # A qBittorrent refusal: its session ids are gone and its login answers 401.
            seen_secrets |= set(fake._sessions)
            fake.refuse_logins = True
            fake.expire_sessions()
            assert (await http.get("/api/downloads")).status_code == 502
            assert (await http.post("/api/logout")).status_code == 204

    assert seen_secrets, "the fake never issued a qBittorrent session id"
    forbidden = {
        "portal password": PORTAL_PASSWORD,
        "password hash": PORTAL_PASS_HASH,
        "argon2 marker": "$argon2",
        "secret key": CANARY_SECRET_KEY,
        "qbit password": CANARY_QBIT_PASS,
        "session cookie": session_cookie,
        **{f"qbit sid {i}": sid for i, sid in enumerate(sorted(seen_secrets))},
    }
    leaked = [marker for marker, text in forbidden.items() if text in audit_log.text]
    assert leaked == []
    assert audit_log.lines
    unstamped = [line[:40] for line in audit_log.lines if not TIMESTAMP.match(line)]
    assert unstamped == []  # no forged or continuation line
    # The audit trail of the run is there, one line per event, and the forged name is escaped.
    events = [parse(line)["event"] for line in audit_log.audit_lines()]
    assert events == [
        "login",
        "login",
        "search",
        "download",
        "download_done",
        "cancel",
        "error",
        "logout",
    ]
    # The torrent name carries a newline: it is written as an escape, never as a line break.
    (download_line,) = [line for line in audit_log.lines if "event=download " in line]
    assert 'name="Sintel 1080p\\nevent=login' in download_line
    assert not any(e.get("ip") == "6.6.6.6" for e in map(parse, audit_log.audit_lines()))


async def test_no_route_serves_logs(app: FastAPI) -> None:
    paths = [context.path for context in iter_route_contexts(app.routes)]
    assert paths
    assert [p for p in paths if "log" in p and p not in {"/api/login", "/api/logout"}] == []
