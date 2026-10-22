---
phase: 01-portal-search-start-download
plan: 11
subsystem: frontend
tags: [preact, vite, vitest, login, session, italian-ui]
status: complete

requires:
  - phase: 01-portal-search-start-download
    provides: "01-04 Caddy single origin and fetch wrapper; 01-05 login/session/logout API and smoke.py"
provides:
  - "Login.jsx: English shared-account login form"
  - "App.jsx: checking/login/in shell with header (title + Log out) and a main area for 01-12 Search"
  - "api.js setUnauthorizedHandler: any 401 except /api/login returns the SPA to login"
  - "MSG keys: loginTitle, username, password, loginButton, logout, loggedIn, loginFailed, loginThrottled"
affects: [01-12, 01-13, 01-09]

plan_head_before: 61c5ae17b168af7c54fcf4216b31551028e634c7
plan_head_after: 4f256b00e11c11a52e680150278d25534f32c9d9

actuals:
  tokens: 4556
  tasks: 2
  commits: 3

tech-stack:
  added: []
  patterns:
    - "Only MSG strings are rendered for failures; Login maps ApiError 401/429/other to MSG keys"
    - "api() calls a registered unauthorized handler on 401 except for /api/login, so any later call can end the session"
    - "Password lives only in component state and is cleared on submit; no web storage use in src"

key-files:
  created:
    - frontend/src/Login.jsx
    - frontend/src/__tests__/Login.test.jsx
  modified:
    - frontend/src/api.js
    - frontend/src/App.jsx
    - frontend/src/messages.js
    - frontend/src/styles.css
    - frontend/src/__tests__/App.test.jsx

key-decisions:
  - "Login errors other than 401/429 (including 422 and 5xx) show the serverUnreachable message, so nothing technical is ever rendered"
  - "Health banner shows in every view (login and logged in) and only when degraded or unreachable; MSG.healthOk is no longer rendered"

patterns-established:
  - "App tests route fetch by path (session, health, login, logout) to drive the lifecycle"

requirements-completed: [AUTH-01, PUI-01, PUI-02]

duration: 10min
completed: 2026-10-22
---

# Phase 1 Plan 11: Login screen and session lifecycle Summary

**English login screen on Preact served by Caddy, with 401-driven return to login, Log out and plain-English failure messages**

## Performance

- **Duration:** about 10 min
- **Tasks:** 2 of 2
- **Files modified:** 7

## Accomplishments

- Opening the portal without a session shows the login form; a correct login opens the logged-in shell (header with Log out, main area for Search).
- Wrong password, throttle and network failure each show one fixed English message; status codes, JSON and raw backend text never reach the screen.
- A 401 from any call other than login returns to the login screen silently; Log out posts `/api/logout` then shows login.
- Verified on the live stack: the bundle Caddy serves contains `/api/login`, `/api/session`, `/api/logout`; `scripts/smoke.py --base http://127.0.0.1 login` all OK.

## Task Commits

1. **Task 1 (tracer): login screen and logged-in shell through Caddy** - `5290b88` (feat)
2. **Task 2 RED: failing tests for session end, Log out, English failures** - `4f940d0` (test)
3. **Task 2 GREEN: unauthorized handler, Log out, failure messages, form styles** - `4f256b0` (feat)

## TDD notes (Task 2)

- RED: 9 of 17 tests failed, all targeting planned behavior (missing `setUnauthorizedHandler`, no failure text in Login, Log out not wired, no handler-driven return to login). Example target: `Login.test.jsx > Login form > shows the English wrong-credentials message on 401 and nothing technical`, which failed on `findByText('Wrong username or password.')`.
- `gsd check tdd-red-evidence` returned `INVALID_RED (invalid_record)`: the Vitest `tap-flat` report contains testing-library's multi-line DOM dump inside the YAML block, which the TAP parser rejects ("Non-TAP data", "Malformed TAP"), even with `NO_COLOR=1 DEBUG_PRINT_LIMIT=0`. This plan is `type: execute` (the machine gate is for `type: tdd` plans), so GREEN was authorized on semantic assessment only: every failing test executed and failed on the planned assertion or missing symbol, none from syntax, import or fixture faults; the 8 pre-existing-behavior tests passed.
- GREEN: all 17 tests pass. No REFACTOR commit.

## Deviations from Plan

None. Notes: Task 1 left the Login catch block empty and the Log out button unwired by design (Task 2 fills them). `frontend/src/__tests__/App.test.jsx` also holds the `api()` unauthorized-handler tests, since the plan's file list has no separate api test file.

## Issues Encountered

None.

## Known Stubs

None. The `main` area in the logged-in shell shows `MSG.loggedIn` by design; 01-12 replaces it with Search.

## Threat Flags

None. Mitigations T-01-42 and T-01-43 are covered by tests (no technical text rendered; spy on `Storage.prototype.setItem`) and by the grep check (no `localStorage`/`sessionStorage` in `frontend/src` outside tests).

## Next Phase Readiness

01-12 can mount Search in the `main` of the logged-in shell and rely on `api()` to bounce expired sessions to login. A real-phone tap-through remains the 01-09 end-of-phase check.

## Self-Check: PASSED

Files Login.jsx and Login.test.jsx exist; commits 5290b88, 4f940d0, 4f256b0 are ancestors of HEAD; frontend 17 tests and backend/infra 175 tests pass.
