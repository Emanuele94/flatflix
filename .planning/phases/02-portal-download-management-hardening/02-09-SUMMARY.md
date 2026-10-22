---
phase: 02-portal-download-management-hardening
plan: 09
subsystem: api
tags: [logging, audit, redaction, fastapi, uvicorn, tdd]
status: complete

requires:
  - phase: 02-portal-download-management-hardening
    provides: "Throttle blocks on search and download (02-05); cancel and remove with CancelOutcome (02-07); job registry _guard with finished_at (02-04)"
provides:
  - "app/audit.py: typed helpers login, logout, search, throttled, download_requested, download_finished, removed, error; free-text and IP sanitising; RedactingFilter; install_redaction(secrets)"
  - "configure_logging(level, secrets) writing to stdout, with app.audit pinned to INFO and the redacting filter on every root and uvicorn handler"
  - "Log line contract: '<asctime> INFO app.audit event=<login|logout|search|throttled|download|download_done|cancel|remove|error> ip=<addr> <fields>'"
affects: [02-10, 02-11]

actuals:
  tokens: 8000
  tasks: 3
  commits: 4

commits: 4
plan_head_before: d6c6e77fb2f2aa192b0ab82543d30d225c39ae37
plan_head_after: c0c20e22e71225d6a55d4f918d13706dfe805bfe

tech-stack:
  added: []
  patterns:
    - "Typed audit helpers instead of a generic kwargs logger: a request, body, header, cookie or settings object cannot be passed"
    - "Free text rendered with json.dumps(value[:200], ensure_ascii=False); address bare only when address-shaped"
    - "Redacting logging.Filter keeps record.args structure (uvicorn's access formatter unpacks it) and is installed idempotently on every root and uvicorn handler"

key-files:
  created:
    - backend/app/audit.py
    - backend/tests/test_audit.py
  modified:
    - backend/app/main.py
    - backend/app/routers/search.py
    - backend/app/routers/auth.py
    - backend/app/routers/download.py
    - backend/app/routers/downloads.py
    - backend/app/download/jobs.py

key-decisions:
  - "A failed login logs outcome and address only, never the attempted username (a password typed into that box would land in the log)"
  - "download_done is written from JobRegistry._guard and never for a cancelled task, so a cancel produces one cancel line and no second outcome line"
  - "error() takes an optional ip so every request-scoped line carries the client address; the plan's three-argument signature still works"
  - "RedactingFilter also swaps non-string args (an exception object) for their redacted text, but only when something was redacted, so numeric args and normal formatting are untouched"

requirements-completed: [SEC-06]

coverage:
  - id: D1
    description: "A search leaves exactly one audit line 'event=search ip=... type=film q=\"...\"' on the container's stdout, visible in docker compose logs backend"
    requirement: "SEC-06"
    verification:
      - kind: unit
        ref: "backend/tests/test_audit.py#test_a_search_writes_one_audit_line_with_ip_type_and_quoted_text"
        status: pass
      - kind: integration
        ref: "scripts/smoke.py search, then docker compose logs backend | grep 'app.audit event=search'"
        status: pass
    human_judgment: false
  - id: D2
    description: "Login ok, fail and throttled, logout, throttled search and download, download and download_done joined by job_id, cancel, remove, not_found and qBittorrent errors are each audited with the client address; no username on a failed login; no download_done for a cancelled job"
    requirement: "SEC-06"
    verification:
      - kind: unit
        ref: "backend/tests/test_audit.py#test_login_outcomes_are_audited_without_the_attempted_username"
        status: pass
      - kind: unit
        ref: "backend/tests/test_audit.py#test_a_started_download_is_audited_twice_joined_by_its_job_id"
        status: pass
      - kind: unit
        ref: "backend/tests/test_audit.py#test_a_cancelled_job_writes_no_download_done_line"
        status: pass
      - kind: unit
        ref: "backend/tests/test_audit.py#test_cancel_remove_and_not_found_are_audited_with_the_row_name"
        status: pass
      - kind: unit
        ref: "backend/tests/test_audit.py#test_a_qbit_outage_is_audited_as_an_error_with_class_and_status"
        status: pass
      - kind: unit
        ref: "backend/tests/test_audit.py#test_every_request_scoped_audit_line_carries_the_client_ip"
        status: pass
    human_judgment: false
  - id: D3
    description: "Free text is escaped and cut to 200 characters so a newline in a query or torrent name never starts a second line; an address is bare only when address-shaped"
    requirement: "SEC-06"
    verification:
      - kind: unit
        ref: "backend/tests/test_audit.py#test_free_text_is_escaped_and_cut_so_it_never_starts_a_second_line"
        status: pass
      - kind: unit
        ref: "backend/tests/test_audit.py#test_an_address_is_bare_only_when_it_is_address_shaped"
        status: pass
    human_judgment: false
  - id: D4
    description: "The redacting filter replaces the three secrets (8+ characters) and both cookie shapes in message, args and exception text, keeps args structure, sits once on every root and uvicorn handler also after create_app twice, and works through uvicorn's own access formatter"
    requirement: "SEC-06"
    verification:
      - kind: unit
        ref: "backend/tests/test_audit.py#test_the_filter_replaces_secrets_in_message_args_and_cookies"
        status: pass
      - kind: unit
        ref: "backend/tests/test_audit.py#test_every_root_and_uvicorn_handler_carries_exactly_one_filter"
        status: pass
      - kind: unit
        ref: "backend/tests/test_audit.py#test_an_access_line_goes_through_uvicorns_own_formatter_redacted"
        status: pass
    human_judgment: false
  - id: D5
    description: "LOG_LEVEL=WARNING still emits audit lines while other INFO loggers stay silent"
    requirement: "SEC-06"
    verification:
      - kind: unit
        ref: "backend/tests/test_audit.py#test_the_audit_trail_survives_log_level_warning"
        status: pass
    human_judgment: false
  - id: D6
    description: "Canary run over wrong login (password typed as username), login, search, download, list, cancel, qBittorrent refusal and logout: no password, hash, SECRET_KEY, qBittorrent password, QBT_SID or flatflix_session value in any line, every line timestamped; no route serves logs"
    requirement: "SEC-06"
    verification:
      - kind: unit
        ref: "backend/tests/test_audit.py#test_canary_secrets_never_reach_a_log_line"
        status: pass
      - kind: unit
        ref: "backend/tests/test_audit.py#test_no_route_serves_logs"
        status: pass
    human_judgment: false
---

# Phase 2 Plan 09: Audit logging and redaction Summary

**Every login, search, download and its outcome, cancel, remove, throttle and error leaves one key=value `app.audit` line with the client address on the backend's stdout, and a redacting filter on every root and uvicorn handler keeps passwords, hashes, SECRET_KEY, qBittorrent credentials and cookies out of any line.**

## Performance

- **Duration:** about 25 min of wall clock
- **Tasks:** 3 (1 tracer, 2 TDD)
- **Files:** 2 created, 6 modified

## Accomplishments

- `app/audit.py` holds eight typed helpers. Free text goes through `json.dumps(value[:200], ensure_ascii=False)`, so a newline in a torrent name shows as `\n` inside the quotes. Addresses print bare only when they match `^[0-9A-Fa-f:.]{1,45}$`.
- `configure_logging` writes to stdout, pins `app.audit` to INFO (the trail survives `LOG_LEVEL=WARNING`) and installs the filter with the three secret values. `create_app` can run any number of times without stacking filters.
- Search, login, logout, download, `_guard` (download outcome), cancel/remove and the qBittorrent failure paths call the helpers. A failed login never records the username.
- On the rebuilt backend container a smoke search and login produced `app.audit event=search ip=... type=film q="big buck bunny"`, `event=login ... outcome=fail|ok` and `event=logout` in `docker compose logs backend`.

## Task Commits

1. **Task 1 (tracer): a search writes one audit line to stdout** - `def94d6` (feat)
2. **Task 2 RED: failing tests for the other events** - `585a6f2` (test)
3. **Task 2 GREEN: login, download, cancel, throttle and error audit calls** - `5f3087a` (feat)
4. **Task 3: redaction, level independence and canary tests** - `c0c20e2` (test)

## Findings

- **RESEARCH A3 held.** After `logging.config.dictConfig(uvicorn.config.LOGGING_CONFIG)` the loggers `uvicorn` and `uvicorn.access` have their own handlers and `uvicorn.access.propagate` is False, so a root-only filter would miss the access lines. `install_redaction` covers root, `uvicorn`, `uvicorn.error` and `uvicorn.access`; a test formats an access record through the handler's own `AccessFormatter` and sees `[redacted]` with the five-tuple `args` intact.
- The search validator already strips control characters, so a newline in `q` never reaches the log; the escaping is exercised by the helper test and by a torrent name with a newline in the canary run.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality] `audit.error` carries the client address**
- **Found during:** Task 2
- **Issue:** The plan's `error(where, exc_class, status)` has no address, but the behaviour list requires `ip=` on every request-scoped line.
- **Fix:** Added an optional `ip` argument; `unavailable()` and `qbit_failure()` now take and pass it (`qbit_failure(exc, where, ip)`).
- **Files modified:** backend/app/audit.py, backend/app/routers/search.py, backend/app/routers/downloads.py
- **Commit:** 5f3087a

**2. [Rule 2 - Missing critical functionality] Filter also redacts non-string args**
- **Found during:** Task 3
- **Issue:** `logger.warning("failed: %s", exc)` passes an exception object whose text can hold a secret; the plan redacted string args only.
- **Fix:** Non-string, non-numeric args are replaced by their redacted text only when redaction changed something.
- **Files modified:** backend/app/audit.py
- **Commit:** def94d6 (written with the module, tested in c0c20e2)

### TDD note

`RedactingFilter` and `install_redaction` were written in Task 1, as the plan instructs, so the Task 3 tests passed on their first run (no RED commit for Task 3). A mutation check (making `redact` a no-op) made three of the Task 3 tests fail, confirming they bite.

## Known Stubs

None.

## Issues Encountered

None beyond the deviations above. `ruff` flags the shared `rig` fixture import (F811) in test modules; the existing convention (`# noqa: F811` on the parameter) is followed.

## Threat Flags

None. No new route, auth path or file access; logs stay on stdout. By D-41 the log holds search text and LAN addresses; plan 02-11 documents it in docs/setup.md.

## Self-Check: PASSED

- backend/app/audit.py, backend/tests/test_audit.py: found
- Commits def94d6, 585a6f2, 5f3087a, c0c20e2: found on the branch
- `uv run --project backend --frozen pytest backend/tests -q`: 632 passed; `ruff check backend`: all checks passed; pyproject.toml and uv.lock unchanged
