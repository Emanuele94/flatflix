"""SEC-06: the audit trail (D-40, D-41) and the redaction of every log handler.

A StringIO handler with the production LOG_FORMAT is attached to the root logger before the app
is created, so `create_app` installs the redacting filter on it exactly as it does on the real
stdout handler. The tests read what that handler wrote.
"""

import io
import json
import logging
import re
from collections.abc import Iterator

import httpx
import pytest
from fastapi import FastAPI

from app.config import Settings
from app.main import LOG_FORMAT, create_app
from app.qbit.client import QbitClient
from tests.fakeqbit import FakeQbit


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
