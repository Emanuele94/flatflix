---
phase: 02-portal-download-management-hardening
plan: 05
subsystem: api
tags: [fastapi, rate-limit, throttle, sliding-window, tdd, python]
status: complete

requires:
  - phase: 02-portal-download-management-hardening
    provides: "phase base (plan 02-01); LoginThrottle and the login 429 shape from phase 1"
provides:
  - "app/throttle.py: SlidingWindowThrottle (per address, optional global ceiling) and THROTTLE_WINDOW_SECONDS = 60"
  - "POST /api/search answers 429 {detail: too_many_requests} with integer Retry-After after 10 starts a minute per address"
  - "POST /api/download answers 429 too_many_requests with Retry-After after 20 starts a minute per address"
  - "Settings search_rate_per_minute (10) and download_rate_per_minute (20), ge=1, in .env.example"
  - "app.state.search_throttle and app.state.download_throttle; LoginThrottle stays importable from app.auth as an alias"
affects: [02-08, 02-09, 02-11]

actuals:
  tokens: 4000
  tasks: 2
  commits: 3

commits: 3
plan_head_before: e4ecaf8f2593e19971af8bd5615c7caf03fd5584
plan_head_after: 877d3d78e804e35913382ab522e6f487343ff0e0

tech-stack:
  added: []
  patterns:
    - "A start route takes its throttle slot inside the handler, after require_user, require_ready and body validation, so rejected requests never consume one"
    - "One generic limiter class, three uses (login, search, download); the old name is an alias"

key-files:
  created:
    - backend/app/throttle.py
    - backend/tests/test_rate_limit.py
  modified:
    - backend/app/auth.py
    - backend/app/main.py
    - backend/app/config.py
    - backend/app/routers/search.py
    - backend/app/routers/download.py
    - .env.example

key-decisions:
  - "Search and download throttles have no global ceiling: both routes sit behind a login and the limit targets a stuck finger or a script (D-38)"
  - "The key is the exact request.client.host string (already the forwarded address through TrustedProxyHeaders); no header is re-read in the routers"
  - "LoginThrottle = SlidingWindowThrottle in app.auth, so main.py and test_login_throttle.py stay untouched"

requirements-completed: [SEC-05]

coverage:
  - id: D1
    description: "The 11th search and 21st download in a minute from one address answer 429 too_many_requests with an integer Retry-After; the 10th and 20th pass"
    requirement: "SEC-05"
    verification:
      - kind: integration
        ref: "backend/tests/test_rate_limit.py#test_eleventh_search_in_a_minute_is_429_with_integer_retry_after"
        status: pass
      - kind: integration
        ref: "backend/tests/test_rate_limit.py#test_twenty_first_download_in_a_minute_is_429_with_retry_after"
        status: pass
    human_judgment: false
  - id: D2
    description: "Exact window boundary (59.9 s blocked, 60 s passes), Retry-After rounded up, 25 concurrent downloads give exactly 20 passes"
    requirement: "SEC-05"
    verification:
      - kind: integration
        ref: "backend/tests/test_rate_limit.py#test_a_slot_frees_exactly_sixty_seconds_after_it_was_taken"
        status: pass
      - kind: integration
        ref: "backend/tests/test_rate_limit.py#test_retry_after_rounds_up_to_whole_seconds"
        status: pass
      - kind: integration
        ref: "backend/tests/test_rate_limit.py#test_twenty_five_concurrent_downloads_give_exactly_twenty_passes"
        status: pass
    human_judgment: false
  - id: D3
    description: "Anonymous (401), malformed (422) and not-ready (503) requests consume no slot; polls, the downloads list and the session probe are never limited"
    requirement: "SEC-05"
    verification:
      - kind: integration
        ref: "backend/tests/test_rate_limit.py#test_anonymous_and_malformed_requests_never_use_a_slot"
        status: pass
      - kind: integration
        ref: "backend/tests/test_rate_limit.py#test_not_ready_downloads_consume_nothing"
        status: pass
      - kind: integration
        ref: "backend/tests/test_rate_limit.py#test_polling_a_job_and_listing_downloads_are_never_limited"
        status: pass
    human_judgment: false

duration: 20 min
completed: 2026-10-22
---

# Phase 2 Plan 05: Rate limits on search and download starts Summary

**Per-address sliding-window throttle (10 searches, 20 download starts per minute) returning 429 `too_many_requests` with Retry-After, built on the login limiter moved into its own generic module.**

## Accomplishments

- Tracer: `POST /api/search` is limited end to end (settings, `.env.example`, `create_app` wiring, handler, tests). The slot is taken inside the handler, after session, readiness and body validation.
- `POST /api/download` gets the same treatment before `pipeline.submit`.
- `LoginThrottle`'s body moved unchanged into `app/throttle.py` as `SlidingWindowThrottle`; `app.auth.LoginThrottle` is an alias, so `test_login_throttle.py` passes untouched.
- `tests/test_rate_limit.py` (18 tests): boundary at 59.9 s and 60 s, Retry-After rounding, 25 concurrent downloads giving exactly 20 passes, key independence, no slot consumed by 401/422/503, polls and reads never limited.

## Task Commits

1. Task 1 (tracer): `ac00ec9` feat(02-05): throttle POST /api/search
2. Task 2 RED: `70a2688` test(02-05): download throttle, concurrency, keying and generic limiter tests
3. Task 2 GREEN: `877d3d7` feat(02-05): throttle POST /api/download; one generic sliding-window limiter

## Deviations from Plan

None - plan executed exactly as written. No existing test hit a limit (Pitfall 9 did not occur), so no test needed a throttle swap and the defaults stayed as specified.

## Verification

- `pytest backend/tests -q`: 511 passed, 4 deselected (integration marker).
- `ruff check backend`: All checks passed. `ruff format --check backend`: clean.
- `git diff` on `backend/pyproject.toml`, `backend/uv.lock` and `backend/tests/test_login_throttle.py`: empty (no package added).
- Acceptance greps all at the expected counts.
- Docker stack not touched (the plan forbids it; 02-09 and 02-11 rebuild).

## Known Stubs

None.

## Threat Flags

None. Mitigates T-02-15 to T-02-18 as planned; no new endpoint or trust boundary.

## Next

Ready for 02-06. Frontend mapping of the 429 text is plan 02-08; docs/setup.md note about household-wide keying behind a hidden-address host is plan 02-11.

## Self-Check: PASSED

- backend/app/throttle.py and backend/tests/test_rate_limit.py exist.
- Commits ac00ec9, 70a2688 and 877d3d7 are ancestors of HEAD.
