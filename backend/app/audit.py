"""Audit trail and log redaction (SEC-06, D-40, D-41).

Every audit event is one INFO record of the logger `app.audit`: plain `key=value` text rendered
by the existing LOG_FORMAT and written to the container's stdout, so `docker compose logs backend`
shows it. There is no log file, volume or endpoint.

The helpers are typed on purpose: none can be handed a request, a body, a header, a cookie or a
settings object. Free text (search text, torrent names) is attacker-influenced, so it is rendered
with `json.dumps` after a 200-character cut: quotes, newlines and control characters are escaped
and a value can never start a second log line. The attempted username of a failed login is never
logged (someone may type the password into that box), nor any password, hash, cookie,
SECRET_KEY or qBittorrent credential.

`RedactingFilter` is defence in depth: it blanks the three secrets and the two cookie shapes in
every record of every handler it is installed on.
"""

import json
import logging
import re
from collections.abc import Sequence

audit_logger = logging.getLogger("app.audit")

MAX_TEXT = 200
# Secrets shorter than this are not redacted: they would blank ordinary words. The audit helpers
# never log a secret in the first place; this filter is the second line of defence only.
MIN_SECRET_LENGTH = 8

_IP_PATTERN = re.compile(r"^[0-9A-Fa-f:.]{1,45}$")
# Enum-like values and ids: printed bare only when they are plainly word-shaped.
_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_COOKIE_PATTERNS = (
    re.compile(r"QBT_SID\w*=[^;\s]+"),
    re.compile(r"flatflix_session=[^;\s]+"),
)
REDACTED = "[redacted]"
# Loggers whose handlers are configured by uvicorn, not by `logging.basicConfig`.
UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


def _text(value: str | None) -> str:
    """Free text as a quoted, escaped, 200-character value; None is `null`."""
    if value is None:
        return "null"
    return json.dumps(value[:MAX_TEXT], ensure_ascii=False)


def _ip(value: str) -> str:
    return value if _IP_PATTERN.match(value) else _text(value)


def _token(value: object) -> str:
    """An enum-like value or id: bare when word-shaped, otherwise quoted like free text."""
    text = "none" if value is None else str(value)
    return text if _TOKEN_PATTERN.match(text) else _text(text)


def login(ip: str, outcome: str) -> None:
    audit_logger.info("event=login ip=%s outcome=%s", _ip(ip), _token(outcome))


def logout(ip: str) -> None:
    audit_logger.info("event=logout ip=%s", _ip(ip))


def search(ip: str, content_type: str, q: str) -> None:
    audit_logger.info("event=search ip=%s type=%s q=%s", _ip(ip), _token(content_type), _text(q))


def throttled(ip: str, scope: str) -> None:
    audit_logger.info("event=throttled ip=%s scope=%s", _ip(ip), _token(scope))


def download_requested(ip: str, content_type: str | None, job_id: str, name: str | None) -> None:
    audit_logger.info(
        "event=download ip=%s type=%s job_id=%s name=%s",
        _ip(ip),
        _token(content_type),
        _token(job_id),
        _text(name),
    )


def download_finished(job_id: str, name: str | None, outcome: str) -> None:
    audit_logger.info(
        "event=download_done job_id=%s name=%s outcome=%s",
        _token(job_id),
        _text(name),
        _token(outcome),
    )


def removed(ip: str, action: str, name: str | None, outcome: str) -> None:
    """`action` is `cancel` or `remove`; it is the event name."""
    audit_logger.info(
        "event=%s ip=%s name=%s outcome=%s",
        _token(action),
        _ip(ip),
        _text(name),
        _token(outcome),
    )


def quarantine_passed(name: str | None, files: int) -> None:
    """A torrent passed the sandbox check and its files were linked into media (D-54)."""
    audit_logger.info("event=quarantine.passed name=%s files=%s", _text(name), _token(files))


def quarantine_runner_unavailable(why: str) -> None:
    """The sandbox cannot be used right now; written once per outage, not once per tick (D-58)."""
    audit_logger.info("event=quarantine.runner_unavailable why=%s", _token(why))


def error(where: str, exc_class: str, status: int | None, ip: str | None = None) -> None:
    """Class name and status only: an exception text could carry a URL or a credential."""
    where_text = f"event=error where={_token(where)}"
    tail = f"exc={_token(exc_class)} status={_token(status)}"
    if ip is None:
        audit_logger.info("%s %s", where_text, tail)
    else:
        audit_logger.info("%s ip=%s %s", where_text, _ip(ip), tail)


class RedactingFilter(logging.Filter):
    """Replace secrets and cookie values in a record's message, string args and exception text.

    `record.args` keeps its structure (a tuple stays a tuple of the same length, a mapping stays
    a mapping): uvicorn's access formatter unpacks it and would break on one collapsed string.
    """

    def __init__(self, secrets: Sequence[str] = ()) -> None:
        super().__init__()
        # Longest first, so a secret that contains another is replaced whole.
        self._secrets = sorted(
            {secret for secret in secrets if len(secret) >= MIN_SECRET_LENGTH},
            key=len,
            reverse=True,
        )

    def redact(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, REDACTED)
        for pattern in _COOKIE_PATTERNS:
            text = pattern.sub(REDACTED, text)
        return text

    def _arg(self, arg: object) -> object:
        if isinstance(arg, str):
            return self.redact(arg)
        if arg is None or isinstance(arg, bool | int | float):
            return arg
        # An exception or another object that prints a secret: swap in its redacted text, but
        # only when something was actually redacted so formatting is otherwise unchanged.
        try:
            shown = str(arg)
        except Exception:  # noqa: BLE001 - a broken __str__ must not break logging
            return arg
        redacted = self.redact(shown)
        return redacted if redacted != shown else arg

    def filter(self, record: logging.LogRecord) -> bool:
        # `logger.error(exc)` passes an object as the message and logging prints `str(msg)` later.
        record.msg = (
            self.redact(record.msg) if isinstance(record.msg, str) else self._arg(record.msg)
        )
        if isinstance(record.args, tuple):
            record.args = tuple(self._arg(arg) for arg in record.args)
        elif isinstance(record.args, dict):
            record.args = {key: self._arg(arg) for key, arg in record.args.items()}
        if record.exc_info and record.exc_info[0] is not None:
            if not record.exc_text:
                record.exc_text = logging.Formatter().formatException(record.exc_info)
            record.exc_text = self.redact(record.exc_text)
        if record.stack_info:
            record.stack_info = self.redact(record.stack_info)
        return True


def install_redaction(secrets: Sequence[str]) -> None:
    """Put one RedactingFilter on every root handler and every uvicorn handler.

    uvicorn configures `uvicorn` and `uvicorn.access` with their own non-propagating handlers
    before the app factory runs, so a root-only filter would never see its lines. Calling this
    again replaces the previous filter instead of stacking another.
    """
    redactor = RedactingFilter(secrets)
    for logger in (logging.getLogger(), *(logging.getLogger(n) for n in UVICORN_LOGGERS)):
        for handler in logger.handlers:
            for existing in [f for f in handler.filters if isinstance(f, RedactingFilter)]:
                handler.removeFilter(existing)
            handler.addFilter(redactor)
