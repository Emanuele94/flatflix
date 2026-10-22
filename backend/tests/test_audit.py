"""SEC-06: the audit trail (D-40, D-41) and the redaction of every log handler.

A StringIO handler with the production LOG_FORMAT is attached to the root logger before the app
is created, so `create_app` installs the redacting filter on it exactly as it does on the real
stdout handler. The tests read what that handler wrote.
"""

import asyncio
import io
import json
import logging
import re
import time
from collections.abc import Iterator

import httpx
import pytest
from fastapi import FastAPI

from app.config import Settings
from app.main import LOG_FORMAT, create_app
from app.qbit.client import QbitClient
from app.throttle import SlidingWindowThrottle
from tests.conftest import PORTAL_USER, log_in
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
