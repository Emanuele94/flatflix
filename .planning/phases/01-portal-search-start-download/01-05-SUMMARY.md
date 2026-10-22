---
phase: 01-portal-search-start-download
plan: 05
subsystem: auth
tags: [fastapi, starlette-sessions, argon2id, pydantic-settings, throttle, pytest]

requires:
  - phase: 01-portal-search-start-download
    provides: "01-02 Settings/ensure_real_secret/create_app and the test fixtures; 01-04 Caddy single origin proxying /api/*; 01-10 dev_env.py and .env.example"
provides:
  - "POST /api/login (JSON only) -> 204 + flatflix_session cookie (HttpOnly, SameSite=Lax, Path=/, Max-Age=2592000) | 401 bad_credentials | 429 too_many_attempts with Retry-After | 422"
  - "GET /api/session and POST /api/logout behind require_user"
  - "app.auth: SESSION_COOKIE, require_user, protected_router, verify_credentials, LoginThrottle (try_acquire, reset)"
  - "Settings: app_user, app_pass_hash, secret_key, login_max_attempts, login_window_minutes, session_max_age_days, session_max_age_seconds"
  - "python -m app.tools.hash_password [--stdin] printing APP_PASS_HASH='$argon2id$...'"
  - "scripts/smoke.py --base URL login: stdlib end-to-end session lifecycle probe through Caddy"
  - "test_routes_protected: route-enumeration guard (deny by default, allow-list is login and health only)"
affects: [01-06, 01-07, 01-08, 01-09, 01-11, 01-12, 01-13]

plan_head_before: 7f51c8127bd48b4ca1ba90315d335331144b8ace
plan_head_after: fb2dfd559755b2b25b41679672a14c1acfec17fe

actuals:
  tokens: 10424
  tasks: 3
  commits: 5

tech-stack:
  added: []
  patterns:
    - "Every feature router is built with protected_router(); test_routes_protected enumerates the real app and fails on any route outside the allow-list that lacks require_user"
    - "Login attempt slot is reserved synchronously (no await between check and record) before the slow argon2 check runs in a thread"
    - "Secrets validated at startup: empty, change-me placeholder, short SECRET_KEY and non-argon2id hash all stop the backend with a message naming the variable and never the value"
    - "Test password hash is computed at run time in conftest, so no hash is ever written to a tracked file"

key-files:
  created:
    - backend/app/auth.py
    - backend/app/routers/auth.py
    - backend/app/tools/__init__.py
    - backend/app/tools/hash_password.py
    - scripts/smoke.py
    - backend/tests/test_auth.py
    - backend/tests/test_login_throttle.py
    - backend/tests/test_routes_protected.py
    - backend/tests/test_config.py
  modified:
    - backend/app/config.py
    - backend/app/main.py
    - backend/tests/conftest.py
    - .env.example
    - scripts/dev_env.py

key-decisions:
  - "Route-enumeration guard uses fastapi.routing.iter_route_contexts: FastAPI 0.159 keeps included routers as nested _IncludedRouter objects, so iterating app.routes and testing isinstance(route, APIRoute) fails"
  - "LoginThrottle is built in create_app (not the lifespan) and stored on app.state.login_throttle, so it exists for every request path and tests can swap in a fake clock"
  - "Login success clears the session before writing the auth marker, so nothing from a previous session survives a login"
  - "Dev password lives in .dev-portal-password (0600, gitignored); dev_env.py regenerates it together with the hash whenever APP_PASS_HASH is missing, so file and hash cannot drift"

patterns-established:
  - "New routers: from app.auth import protected_router; router = protected_router(); register with app.include_router in create_app"
  - "Tests of protected routes use the user_api fixture (api client already logged in); tests.conftest.log_in logs a client in"

requirements-completed: [SEC-04]
# AUTH-01 is declared by this plan but not marked: requirements.ready-ids did not list it as ready
# (01-11, the login screen, still declares it).

coverage:
  - id: D1
    description: "Through Caddy the shared account logs in and gets the 30-day HttpOnly SameSite=Lax cookie; wrong user and wrong password give the same 401; session works, logout clears it"
    requirement: "AUTH-01"
    verification:
      - kind: unit
        ref: "backend/tests/test_auth.py (8 tests)"
        status: pass
      - kind: integration
        ref: "python3 scripts/smoke.py --base http://127.0.0.1 login on the rebuilt stack: six OK lines (no-session-401, wrong-password-401, login-204-cookie, session-200, logout-204, session-401-again), run three times"
        status: pass
    human_judgment: false
  - id: D2
    description: "Every route except POST /api/login and GET /api/health returns 401 not_authenticated without a session, and the guard fails if a future route lacks require_user"
    requirement: "AUTH-01"
    verification:
      - kind: unit
        ref: "backend/tests/test_routes_protected.py (4 tests including test_the_guard_catches_an_unprotected_route)"
        status: pass
    human_judgment: false
  - id: D3
    description: "The 6th login attempt within 15 minutes from one IP gets 429 with Retry-After and skips argon2; allowed after the window; success clears the counter; another IP unaffected; ten concurrent wrong logins let at most five through"
    requirement: "AUTH-01"
    verification:
      - kind: unit
        ref: "backend/tests/test_login_throttle.py (7 tests)"
        status: pass
      - kind: other
        ref: "Throttle behaviour through the real Caddy and uvicorn --proxy-headers path (client address taken from X-Forwarded-For) was not exercised; tests inject the client address at the ASGI layer"
        status: unknown
    human_judgment: true
    rationale: "Pitfall 14: behind Docker Desktop all LAN clients may share one source address. Plan accepts this and assigns the documentation to 01-09; nothing here measured it on the real network."
  - id: D4
    description: "Misconfigured secrets stop the backend with a message naming the variable and never the value: empty, change-me placeholder, SECRET_KEY under 32 characters, APP_PASS_HASH not argon2id (message mentions single quotes)"
    requirement: "SEC-04"
    verification:
      - kind: unit
        ref: "backend/tests/test_config.py (secret_key length, empty/placeholder per secret, empty and missing env vars, five bad-hash shapes, four value-not-echoed cases)"
        status: pass
    human_judgment: false
  - id: D5
    description: "The hash helper prints exactly one APP_PASS_HASH='$argon2id$...' line that verifies, exits 2 on mismatch or a password under 8 characters, and works inside the backend container"
    requirement: "SEC-04"
    verification:
      - kind: unit
        ref: "backend/tests/test_config.py (stdin, interactive confirmed, mismatch, short password x2)"
        status: pass
      - kind: integration
        ref: "printf ... | uv run --directory backend --frozen python -m app.tools.hash_password --stdin matches ^APP_PASS_HASH='\\$argon2id\\$; docker compose run --rm --no-deps backend python -m app.tools.hash_password --stdin printed the same shape"
        status: pass
    human_judgment: false
  - id: D6
    description: "A hash stored in .env as APP_PASS_HASH='$argon2id$...' survives Compose env_file interpolation (Pitfall 6)"
    requirement: "SEC-04"
    verification:
      - kind: integration
        ref: "dev_env.py wrote the single-quoted hash; the rebuilt backend started (Settings validated an argon2id hash) and smoke login step login-204-cookie passed through Compose env_file"
        status: pass
    human_judgment: false

duration: 10min
completed: 2026-10-22
status: complete
---

# Phase 1 Plan 05: Shared-Account Login, Throttle and Strict Secrets Summary

**One shared household account now logs in through Caddy with an argon2id-verified, 30-day HttpOnly session; every route is deny-by-default behind a route-enumeration guard, login is limited to 5 tries per 15 minutes per IP with atomic slot reservation, and bad secrets stop the backend with a value-free message.**

## Performance

- **Duration:** about 10 min (start time was not captured at launch; estimated from the previous plan's commit time and file timestamps)
- **Completed:** 2026-10-22T10:35Z
- **Tasks:** 3 (one tracer, two TDD)
- **Files:** 14 touched (9 created, 5 modified)

## Accomplishments

- Tracer proven on the real stack before expansion: `python3 scripts/smoke.py --base http://127.0.0.1 login` printed six OK lines (no session 401, wrong password 401, login 204 with the 30-day cookie, session 200, logout 204, session 401 again). Tracer gate: the full verify command was re-run once (pytest, dev_env, `docker compose up -d --build --wait`, smoke) with the same result, then expansion started. Interactive mode, `human_verify_mode` default, automated-only verify, so no human checkpoint applied.
- The dev password and a single-quoted argon2id hash are generated by `scripts/dev_env.py` (password file mode 0600, nothing printed). Compose took the quoted `$` signs literally, which closes the Compose interpolation risk for this stack (Pitfall 6).
- 175 tests pass (backend and infra), up from 131. New: 8 login/session, 7 throttle, 4 route guard, 25 config and hash helper.

## Task Commits

1. **Task 1: Tracer, login through Caddy with the 30-day session** - `f065814` (feat)
2. **Task 2: Deny by default and throttle brute force** (TDD)
   - RED: `5a2ef7a` (test)
   - GREEN: `6041be8` (feat)
3. **Task 3: Strict secret validation and the hash helper** (TDD)
   - RED: `af21724` (test)
   - GREEN: `fb2dfd5` (feat)

## TDD Gate Compliance

**Task 2**
- RED: the RED commit carries a stub `LoginThrottle` (allows everything, no-op reset) and the `app.state.login_throttle` wiring, so tests fail on assertions instead of on import. Result: 5 failed, 6 passed. `gsd_run check tdd-red-evidence` (JUnit XML, target `test_sixth_attempt_is_429_with_retry_after_and_skips_argon2`) returned `RED_EVIDENCE_OK / target_test_failed`.
- Semantic assessment: the target failed on `assert 401 == 429` (the stub never throttles), and the unit test failed on `None == 90` (no retry value). Both are the planned behaviours. The 6 tests that passed in RED are the route-enumeration tests: they assert a property (every route protected) that already held because 01-05 Task 1 built the auth routes with `protected_router()`. This is the unexpected-green case from the fail-fast rules, investigated and accepted: the guard exists to stop future regressions, and `test_the_guard_catches_an_unprotected_route` proves the guard itself can fail by feeding it a deliberately unprotected route.
- First RED run also showed two test bugs, fixed before the RED commit and not counted as RED: `app.routes` in FastAPI 0.159 holds nested `_IncludedRouter` objects (switched to `fastapi.routing.iter_route_contexts`), and a bare `FastAPI()` in the guard self-test carried docs routes (docs disabled).
- GREEN: real `LoginThrottle` and the 429 path. 150 passed.
- REFACTOR: none.

**Task 3**
- RED: stub `hash_password.main` (returns 0, prints nothing). Result: 14 failed, 11 passed. `check tdd-red-evidence` with target `test_secret_key_of_31_characters_is_rejected_and_32_accepted` returned `RED_EVIDENCE_OK / target_test_failed`.
- Semantic assessment: the target failed because no `ValidationError` was raised for a 31-character key (the length rule did not exist). Hash-rejection, value-not-echoed and helper tests failed for the same kind of reason (no rule, no output). The 11 that passed are the empty and placeholder cases and the 32-character case, already enforced by `ensure_real_secret` from 01-02, plus the defaults test; expected green, not a gap.
- GREEN: validators and the real helper. 175 passed.
- REFACTOR: none.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Test fixtures needed the new required Settings fields**
- **Found during:** Task 1
- **Issue:** `backend/tests/conftest.py` builds `Settings(...)` from kwargs; `app_user`, `app_pass_hash` and `secret_key` are required now, and the file was not in the plan's files list. The conftest also needed `log_in` and `user_api` helpers for later plans.
- **Fix:** conftest gets test constants, a run-time argon2 hash of the test password, the new Settings kwargs and the two helpers.
- **Files modified:** backend/tests/conftest.py
- **Commit:** f065814

**2. [Rule 1 - Bug] Route guard tests used an API removed in the pinned FastAPI**
- **Found during:** Task 2 (first RED run)
- **Issue:** `app.routes` yields `_IncludedRouter` objects in FastAPI 0.159.1, so the plan's "walk route.dependant" approach on `app.routes` raised on the first non-APIRoute entry.
- **Fix:** enumerate with `fastapi.routing.iter_route_contexts`, which flattens includes and exposes the effective `dependant`, router-level dependencies included.
- **Files modified:** backend/tests/test_routes_protected.py
- **Commit:** 5a2ef7a (fixed before commit)

**3. [Rule 2 - Missing critical] Unbounded growth of the throttle table**
- **Found during:** Task 2 (GREEN)
- **Issue:** a per-IP deque that is never removed grows for every address ever seen.
- **Fix:** expired entries are dropped on each acquire and an emptied IP key is deleted.
- **Files modified:** backend/app/auth.py
- **Commit:** 6041be8

No plan scope was changed.

## Authentication Gates

None.

## Known Stubs

None. The RED-commit stubs (`LoginThrottle`, `hash_password.main`) were replaced in the GREEN commits.

## Issues Encountered

- The `ruff check` on `scripts/qbit_login_check.py` reports two UP031 findings from an earlier plan. Out of scope (not touched by this plan), not fixed.
- The mangled-hash test ids appear in pytest output as generated strings. They are produced from a run-time test hash, never committed.

## Next Phase Readiness

- Plans 01-07 and 01-08 must create routers with `protected_router()`; `test_routes_protected` covers them automatically through the `app` fixture and will fail if a new route is public.
- 01-11 (login screen) can call `POST /api/login` JSON `{username, password}`, `GET /api/session`, `POST /api/logout` exactly as in the interfaces block; 429 carries `Retry-After`.
- 01-09 documents: the hash helper commands, the single-quote rule for `.env`, and Pitfall 14 (all LAN clients may share one address, so five wrong tries can lock the whole household for 15 minutes).
- Rotating `SECRET_KEY` logs everyone out. Session cookie travels over plain HTTP on the LAN (T-01-17, accepted).

## Self-Check: PASSED

- Files: all 9 created files and 5 modified files present; commits f065814, 5a2ef7a, 6041be8, af21724 and fb2dfd5 are ancestors of HEAD.
- `git rev-list --count 7f51c81..HEAD` measured 5 (matches `actuals.commits`).
- `uv run --project backend --frozen pytest backend/tests infra/tests -q`: 175 passed; `ruff check backend scripts/dev_env.py scripts/smoke.py`: clean.
