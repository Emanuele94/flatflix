---
phase: 01-portal-search-start-download
plan: 02
subsystem: api
tags: [fastapi, httpx, pydantic-settings, docker-compose, qbittorrent, uv, respx]

requires:
  - phase: 01-portal-search-start-download
    provides: "01-10 pinned qBittorrent 5.2.4 service on network qbit with provisioned credentials, .env tooling; 01-01 approved lockfiles"
provides:
  - "docker-compose.yml: service backend (build ./backend, networks edge + qbit, waits for qbittorrent healthy, no published port) and network edge"
  - "backend/Dockerfile: python:3.12.15-slim + uv 0.6.14, uv sync --frozen --no-dev, runs as uid 10001"
  - "app.config: Settings (env only, SecretStr, placeholder rejection), get_settings, ensure_real_secret"
  - "app.qbit.client: QbitClient with login, one shared re-login on 403, 900 s / 3600 s cool-downs, typed errors"
  - "app.main.create_app factory (no docs, no openapi, no static files) and GET /api/health"
  - "tests.fakeqbit.FakeQbit stateful WebAPI double plus conftest fixtures settings, fake_qbit, app, api"
affects: [01-04, 01-05, 01-06, 01-07, 01-08, 01-09]

plan_head_before: f5cdbedc7a593a1f8c98c6c9544ba2cba94ed0f8
plan_head_after: f73b1242aa12506ff06739140303860bcfdf602d

actuals:
  tokens: 6592
  tasks: 2
  commits: 3

tech-stack:
  added: ["python:3.12.15-slim (pinned image)", "ghcr.io/astral-sh/uv:0.6.14 (pinned image)"]
  patterns:
    - "create_app(settings, qbit) factory with state set in the lifespan; tests inject a QbitClient over a mock transport"
    - "Session epoch + asyncio.Lock: callers that saw the same stale session trigger exactly one re-login"
    - "Login cool-downs on 401 and 403 keyed to an injectable clock; transport errors never start one"
    - "FakeQbit route table (register) with an async handler that yields once so concurrent callers really interleave"

key-files:
  created:
    - backend/Dockerfile
    - backend/.dockerignore
    - backend/app/config.py
    - backend/app/main.py
    - backend/app/qbit/__init__.py
    - backend/app/qbit/client.py
    - backend/app/routers/__init__.py
    - backend/app/routers/health.py
    - backend/tests/conftest.py
    - backend/tests/fakeqbit.py
    - backend/tests/test_health.py
    - backend/tests/test_qbit_client.py
  modified:
    - docker-compose.yml

key-decisions:
  - "Container healthcheck on /api/health passes on HTTP 200 (backend process alive), not on status ok: a qBittorrent outage must not make the portal container unhealthy and block the web service that will depend on it; the end-to-end ok/up check is the verify step"
  - "FakeQbit.handler is async and yields once (asyncio.sleep(0)): with a sync mock handler the ten concurrent callers never interleave and the lock test would pass without a lock"
  - "Settings uses hide_input_in_errors so a rejected value never appears in ValidationError text; LOG_LEVEL is validated against logging level names"
  - "Login 200 with body Fails. (older qBittorrent) is treated as QbitAuthError; any other login status is QbitUnavailable with no cool-down"

patterns-established:
  - "Health body is exactly {status, qbittorrent}, always HTTP 200; failure logs the exception class name only"
  - "Backend tests build Settings from explicit kwargs and never read the environment"

requirements-completed: []  # INFRA-01, SEC-01, SEC-02, SEC-04 declared by this plan but not marked: requirements.ready-ids returned none ready (sibling phase-01 plans without a SUMMARY still declare them)

coverage:
  - id: D1
    description: "Backend in compose logs into the pinned qBittorrent 5.2.4 with env-provisioned credentials; GET /api/health inside the backend container returns exactly ok/up"
    requirement: "INFRA-01"
    verification:
      - kind: integration
        ref: "docker compose up -d --build --wait && docker compose exec -T backend python -c <urlopen /api/health> prints {'status': 'ok', 'qbittorrent': 'up'}, exit 0 (run three times, including after the client rewrite)"
        status: pass
      - kind: unit
        ref: "backend/tests/test_health.py#test_health_ok_when_qbittorrent_login_and_version_succeed"
        status: pass
    human_judgment: false
  - id: D2
    description: "Health body has exactly the keys status and qbittorrent and leaks no version, host, username or password; /docs, /redoc and /openapi.json return 404"
    requirement: "SEC-01"
    verification:
      - kind: unit
        ref: "backend/tests/test_health.py#test_health_body_leaks_no_version_host_or_credentials"
        status: pass
      - kind: unit
        ref: "backend/tests/test_health.py#test_api_docs_are_not_served"
        status: pass
    human_judgment: false
  - id: D3
    description: "No service publishes a port; qbittorrent only on network qbit, backend on edge and qbit; backend runs as uid 10001"
    requirement: "SEC-02"
    verification:
      - kind: integration
        ref: "yaml parse of docker-compose.yml prints [] for services with ports and the network map; docker compose exec -T backend id -u prints 10001; docker compose port qbittorrent 8088 and backend 8000 show nothing published"
        status: pass
    human_judgment: false
  - id: D4
    description: "Client survives expired sessions, wrong credentials and bans: one login reused, one shared re-login for ten concurrent callers, cool-downs of 900 s and 3600 s with no network I/O, transport errors never block, no Referer/Origin, no password in repr or logs"
    requirement: "SEC-01"
    verification:
      - kind: unit
        ref: "backend/tests/test_qbit_client.py (8 tests: three-calls-one-login, concurrent relogin, wrong-password cooldown, ban cooldown, connection refused, wire format, health+caplog, repr)"
        status: pass
    human_judgment: false
  - id: D5
    description: "An empty or change-me QBITTORRENT_PASS stops Settings with a message naming the variable and never the value"
    requirement: "SEC-04"
    verification:
      - kind: other
        ref: "Settings() with QBITTORRENT_PASS='' prints 'QBITTORRENT_PASS is empty'; with 'change-me-please' prints 'QBITTORRENT_PASS still holds the .env.example placeholder' (manual one-off run, no committed test)"
        status: pass
    human_judgment: true
    rationale: "The placeholder rejection was checked by a one-off command, not by a committed test; the plan did not require one. A verifier should confirm or ask for a test."

duration: 4min
completed: 2026-10-22
status: complete
---

# Phase 1 Plan 02: Backend Tracer and qBittorrent Client Summary

**FastAPI backend in compose that logs into the pinned qBittorrent 5.2.4 with env-provisioned credentials and answers GET /api/health with ok/up, plus an httpx QbitClient that shares one re-login across concurrent callers and backs off after 401 and 403 so it can never ban itself.**

## Performance

- **Duration:** about 4 min
- **Started:** 2026-10-22T10:13:35Z
- **Completed:** 2026-10-22T10:17:21Z (before SUMMARY write)
- **Tasks:** 2 (tracer plus one TDD task)
- **Files modified:** 13 (12 created, docker-compose.yml modified)

## Accomplishments

- Tracer proven end to end on the real image before expansion: `docker compose up -d --build --wait` healthy, `/api/health` inside the backend container prints `{'status': 'ok', 'qbittorrent': 'up'}`; the full verify command was re-run once as the tracer gate with the same result (`Tracer verified end-to-end, expanding`).
- Client hardened by test-first work: three tests failed for the planned reasons (11 logins instead of 2 for ten concurrent callers; a request reaching FakeQbit during both cool-downs), then passed after the epoch plus `asyncio.Lock` plus cool-down change. The rebuilt container still reports ok/up against the real qBittorrent.
- Nothing is published: no service has a `ports` key, `docker compose port` shows nothing for qbittorrent 8088 or backend 8000, and the backend runs as uid 10001.
- `FakeQbit` is ready for later plans: `register(method, path, handler)`, call log, ban and session simulation.

## Task Commits

1. **Task 1: Tracer, backend in compose logs into the real qBittorrent** - `f5d8d1d` (feat)
2. **Task 2: Client survives expired sessions, wrong credentials and bans** (TDD)
   - RED: `8dce419` (test)
   - GREEN: `f73b124` (feat)
   - REFACTOR: none needed

**Plan metadata:** committed separately (docs: complete plan)

## TDD Gate Compliance

RED and GREEN commits are present and in order for Task 2 (`test(01-02)` 8dce419 before `feat(01-02)` f73b124). Task 1 is a tracer (not tdd) and has one `feat` commit.

- **RED:** `backend/tests/test_qbit_client.py` (8 tests) with `FakeQbit`. Command: `pytest backend/tests/test_qbit_client.py backend/tests/test_health.py -q --junitxml=...`, exit 1, 11 passed and 3 failed. Failing targets: `test_concurrent_calls_after_expiry_share_exactly_one_relogin` (`assert 11 == 2` on `fake_qbit.logins`), `test_wrong_password_cooldown_blocks_logins_without_network_io` and `test_ban_cooldown_blocks_calls_for_an_hour` (`assert 2 == 1` on the request count during the cool-down). `gsd check tdd-red-evidence` returned `RED_EVIDENCE_OK` (format junit, reason `target_test_failed`). Semantic assessment: the target tests ran and failed on the planned assertions (a missing lock and a missing cool-down), not on import, fixture or setup faults. The other five tests passed already because Task 1's tracer client satisfied them (single login reuse, transport error handling, wire format, health logging, repr), which is expected, not an unexpected green.
- **GREEN:** `QbitClient` gained `_session_epoch`, `asyncio.Lock`, `_block` and `_raise_if_blocked`; all 72 backend tests pass (14 in the two plan files).
- **REFACTOR:** nothing to clean up.

## Files Created/Modified

- `docker-compose.yml` - adds service `backend` and network `edge`; qbittorrent service untouched
- `backend/Dockerfile`, `backend/.dockerignore` - pinned image build from the lockfile, uid 10001
- `backend/app/config.py` - Settings, `get_settings`, `ensure_real_secret`
- `backend/app/main.py` - `create_app` factory, logging setup, lifespan owning the client
- `backend/app/qbit/client.py` - QbitClient and the four error types
- `backend/app/routers/health.py` - the one unauthenticated route
- `backend/tests/conftest.py`, `fakeqbit.py`, `test_health.py`, `test_qbit_client.py` - fixtures, test double, 14 tests

## Decisions Made

See key-decisions. The container healthcheck deliberately checks liveness (HTTP 200) rather than `status == ok`.

## Deviations from Plan

None - plan executed exactly as written. Small additions inside the plan's intent: `UV_PYTHON_DOWNLOADS=never` in the Dockerfile so `uv sync` can only use the pinned image interpreter, `hide_input_in_errors` on Settings, and LOG_LEVEL validation.

## Issues Encountered

- `ruff format --check` flagged one long signature in `test_health.py` after the first write; reformatted before the commit.
- The test file `test_health.py` builds its own app with a real transport (respx), because Task 2 rewired the shared `app` fixture through `FakeQbit`; the plan allowed this.

## Known Stubs

None.

## Threat Flags

None. New surface (backend listening on 0.0.0.0:8000 inside the `edge` and `qbit` networks, unpublished) is covered by T-01-02, T-01-03 and T-01-06. Note for 01-04 and 01-05: `--forwarded-allow-ips *` (research A3) trusts forwarded headers from any peer on the container network, which matters only for the login limiter.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- 01-04 can add `web` on network `edge` and the compose invariant tests; the file comment now says only `web` is pending.
- Later plans extend `create_app` with routers and middleware, add endpoints to `FakeQbit` via `register`, and reuse `QbitClient._request`.
- The stack is left running: qbittorrent and backend both healthy, nothing published.
- Requirements INFRA-01, SEC-01, SEC-02, SEC-04 stay unmarked until the last sibling plan declaring each has a SUMMARY.

## Self-Check: PASSED

All 13 files exist, commits `f5d8d1d`, `8dce419` and `f73b124` are ancestors of HEAD, `git rev-list --count` gives 3 since `plan_head_before`, all acceptance criteria re-run and passing, plan-level verification (72 tests green, stack healthy with ok/up, no published port) passed.

---
*Phase: 01-portal-search-start-download*
*Completed: 2026-10-22*
