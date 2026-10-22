---
phase: 02-portal-download-management-hardening
plan: 08
subsystem: ui
tags: [preact, vitest, rate-limit, cancel, tdd]
status: complete

requires:
  - phase: 02-portal-download-management-hardening
    provides: "429 too_many_requests contract on /api/search and /api/download (02-05); MSG.throttled and MSG.downloadCancelled copy (02-06); job status cancelled (02-07)"
provides:
  - "Search screen shows MSG.throttled under the search box on a 429, form stays editable"
  - "Result row states throttled and cancelled: warn tone, role status, Download button enabled, restorable after a reload"
affects: [02-09, 02-10, 02-11]

actuals:
  tokens: 6500
  tasks: 2
  commits: 3

commits: 3
plan_head_before: 15cb3df71c49eda53ed4aa4e69295c039c1b3968
plan_head_after: 6d9c0409996c23123b355abedb0c3513be9a2bdf

tech-stack:
  added: []
  patterns:
    - "A new backend outcome becomes a row state in three places only: Search.jsx state sets (RETRYABLE, JOB_STATES or ROW_STATES), the ResultRow MESSAGE table, and an MSG string"
    - "Saved row states are allow-listed (ROW_STATES): throttled is restorable, cancelled restores as a job status, anything else is dropped"

key-files:
  created: []
  modified:
    - frontend/src/Search.jsx
    - frontend/src/ResultRow.jsx
    - frontend/src/__tests__/Search.test.jsx
    - frontend/src/__tests__/ResultRow.test.jsx

key-decisions:
  - "cancelled is a JOB_STATES member (it is a backend job status, so applyJob keeps it instead of mapping it to failed and polling stops); throttled is a client-side ROW_STATES member"
  - "messages.js was not touched: all copy came from plan 02-06"

requirements-completed: [SEC-05, DOWN-06]

coverage:
  - id: D1
    description: "A 429 on POST /api/search shows the plain throttle sentence in the existing alert under the form; no code, no countdown, no Retry-After; the form stays editable and a later search works"
    requirement: "SEC-05"
    verification:
      - kind: unit
        ref: "frontend/src/__tests__/Search.test.jsx#shows the throttle message on a 429 and nothing technical (D-39)"
        status: pass
    human_judgment: false
  - id: D2
    description: "A 429 on POST /api/download puts only that row in a retryable warn state with the plain sentence; tapping again posts again"
    requirement: "SEC-05"
    verification:
      - kind: unit
        ref: "frontend/src/__tests__/Search.test.jsx#a 429 on a Download tap leaves only that row throttled, retryable, with the plain text"
        status: pass
    human_judgment: false
  - id: D3
    description: "A job that answers cancelled leaves a retryable warn row, stops polling, and a new tap posts again"
    requirement: "DOWN-06"
    verification:
      - kind: unit
        ref: "frontend/src/__tests__/Search.test.jsx#a job that answers cancelled leaves a retryable warn row and stops polling"
        status: pass
    human_judgment: false
  - id: D4
    description: "throttled and cancelled rows survive a reload retryable and request-free; an unknown saved state is still dropped"
    requirement: "DOWN-06"
    verification:
      - kind: unit
        ref: "frontend/src/__tests__/Search.test.jsx#throttled and cancelled rows come back with their texts and enabled buttons, with no request"
        status: pass
      - kind: unit
        ref: "frontend/src/__tests__/Search.test.jsx#a saved job with an unknown state such as bogus is still dropped"
        status: pass
    human_judgment: false
---

# Phase 2 Plan 08: Throttle and cancelled rows on the Search screen Summary

**429 and cancelled-job outcomes reach the Search screen as one plain sentence each (search box alert, or a retryable warn row), with no status code or backend text, and survive a reload.**

## Accomplishments

- `searchErrorMessage` maps 429 to `MSG.throttled` in the existing `role=alert` form-error block (tracer, task 1).
- `downloadErrorState` maps 429 to row state `throttled`; `cancelled` is accepted as a job status; both are in `RETRYABLE`, so the Download button stays enabled and a re-tap posts again.
- `ResultRow` `MESSAGE` gains `throttled` and `cancelled` (warn tone, retry true, `role=status` paragraph, no spinner).
- Saved searches restore `throttled` and `cancelled` rows without any request; unknown states such as `bogus` are still dropped.
- No new package, `messages.js` untouched (02-06 copy reused), no inline styles.

## Task Commits

1. Task 1 (tracer): `c2651ef` feat(02-08): show a plain throttle message under the search box on 429
2. Task 2 RED: `d015d65` test(02-08): add failing tests for throttled and cancelled download rows
3. Task 2 GREEN: `6d9c040` feat(02-08): throttled and cancelled download rows are retryable and survive a reload

## Verification

- `npm --prefix frontend ci && npm --prefix frontend test`: 8 files, 202 tests pass.
- `npm --prefix frontend run build`: succeeds.
- Tracer gate: end-to-end verify re-run green before expansion.
- Acceptance greps: `'throttled'` x3 and `'cancelled'` x2 in Search.jsx; `MSG.downloadCancelled` and `MSG.throttled` once each in ResultRow.jsx; `git diff --quiet` on messages.js against the newest 02-06 commit exits 0; package.json and lockfile unchanged.

## Deviations from Plan

None - plan executed exactly as written. (Two of my own new assertions first matched the legitimate word "cancelled" inside the plain sentence; I fixed the assertions to strip the sentence before checking for raw codes. Test-only, no production change.)

## Known Stubs

None.

## Threat Flags

None. T-02-29 (no raw code in the DOM) and T-02-30 (allow-listed restored states) are covered by tests.

## Self-Check: PASSED

- Files modified exist; commits `c2651ef`, `d015d65`, `6d9c040` are in HEAD history.
