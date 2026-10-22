---
phase: 01-portal-search-start-download
plan: 13
subsystem: frontend
tags: [preact, vitest, download, polling, italian-ui, idempotency]
status: complete

requires:
  - phase: 01-portal-search-start-download
    provides: "01-08 POST /api/download and GET /api/download/{job_id}; 01-12 Search and ResultRow with type prop and MSG.notReady"
provides:
  - "Download button on every result row posting exactly {result_id, type}"
  - "Row state map in Search keyed by result_id (pending, started, preparing, duplicate, rejected, unavailable, failed, expired, notReady, network)"
  - "Job polling every 2 s, capped at 330 s, cleared on unmount and on a new search"
  - "MSG keys: download, started, preparing, rejected, unavailable, duplicate, downloadFailed, searchExpired"
affects: [01-09]

plan_head_before: 90ccfd44db8601404d434df7829622e838bd79ae
plan_head_after: 08c88e1b1e64aad16e5b96994b8d26d6797a8cfe

actuals:
  tokens: 7200
  tasks: 2
  commits: 3

tech-stack:
  added: []
  patterns:
    - "Row state lives in Search as a ref (synchronous double-tap guard) mirrored into state (renders), keyed by result_id so re-sorted snapshots keep each row's state"
    - "A jobEpoch counter invalidates every in-flight download and poll on a new search or unmount, same idea as the search runId"
    - "Unknown backend statuses map to failed: only the literal status started can ever render success"

key-files:
  created: []
  modified:
    - frontend/src/Search.jsx
    - frontend/src/ResultRow.jsx
    - frontend/src/messages.js
    - frontend/src/styles.css
    - frontend/src/__tests__/ResultRow.test.jsx
    - frontend/src/__tests__/Search.test.jsx

key-decisions:
  - "The POST and the polling live in Search, not ResultRow: ResultRow is a pure view taking state and onDownload, so state survives re-sorts and unmounted rows"
  - "Type sent is captured at submit time (rowsType ref), so toggling Movie/TV Series after results arrive cannot cause a type_mismatch"
  - "rejected, unavailable and expired rows disable the button (a retry cannot change the outcome); failed, 503 and network keep it enabled"
  - "A poll answering 404 or 401 stops polling and keeps Preparing; network blips and 5xx keep polling until the 330 s cap"

requirements-completed: [DOWN-01, SEC-03]

duration: about 25 min
completed: 2026-10-22
---

# Phase 1 Plan 13: Download button and row states Summary

**Download on every result row posts only {result_id, type}; each outcome is a plain English state on its own row, and "Started ✓" appears only for a backend status of started**

## Accomplishments

- Tracer: the web image Caddy serves carries the Download button. The served bundle references `/api/download` and `Started`, and `POST /api/download` through the same origin answers 401 without a session. No real download was started.
- Row states: spinner while the POST is pending, "Started ✓", "Preparing" (with spinner), "Already added", the D-13 rejection text, "Not available. Try another result.", "Download failed. Try again." with the button enabled again, 410 "Search expired. Search again.", 503 `MSG.notReady`, network `MSG.serverUnreachable`.
- Preparing jobs poll `GET /api/download/{job_id}` every 2 s until a final status, give up after 330 s keeping "Preparing", and stop on unmount or a new search.
- Idempotency and concurrency: taps on started, preparing, duplicate, pending rows send nothing (disabled button plus a handler guard), two taps in one tick send one request, three rows tapped together resolve independently, and a re-sorting snapshot keeps each state.
- Verification: frontend vitest 100 pass (38 before). Web image rebuilt healthy; bundle check and 401 check pass.

## TDD

- **RED** (`ca5e19a`): 20 Search tests and 19 ResultRow tests failed on assertions for the planned behavior (for example the row never showed a message, the sent type followed the live toggle, nothing polled). `gsd-tools check tdd-red-evidence` returned `RED_EVIDENCE_OK target_test_failed` for the target "sends the type of the search that produced the row, not the current toggle" (expected `serie`, actual `film`), captured with the `tap-flat` reporter. Semantic assessment: the target ran and failed on the planned assertion, not on a load or fixture fault. Some guard tests (for example never_success on the tracer-only row) passed already in RED; they are regression guards, not the RED target.
- **GREEN** (`08c88e1`): implementation makes all 100 pass. No REFACTOR commit.

## Commits

| Task | Commit | Message |
| ---- | ------ | ------- |
| 1 tracer | 0782508 | feat(01-13): tracer Download button posts {result_id, type} and shows Started on started |
| 2 RED | ca5e19a | test(01-13): add failing tests for row states, polling, idempotency and never_success |
| 2 GREEN | 08c88e1 | feat(01-13): every download outcome is a plain Italian row state, success only for started (UI later switched to English) |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Live toggle type used for downloads**
- **Found during:** Task 2 (RED test design)
- **Issue:** 01-12 passed the live `type` toggle into rows, so switching Movie to TV Series after results arrived would send the wrong type and hit `type_mismatch` (422).
- **Fix:** `rowsType` ref set at submit; the POST uses it.
- **Files modified:** frontend/src/Search.jsx
- **Commit:** 08c88e1

**2. [Rule 3 - Blocking] Disabled button still fired onClick under jsdom**
- **Found during:** Task 2 GREEN
- **Issue:** `fireEvent.click` on a disabled Preact button reached the handler, breaking the "tap does nothing" tests.
- **Fix:** handler guard `if (!disabled) onDownload(result)` in addition to the `disabled` attribute.
- **Files modified:** frontend/src/ResultRow.jsx
- **Commit:** 08c88e1

### Plan wording differences (no behavior change)

- Task 1 acceptance says `frontend/src/ResultRow.jsx` contains `/api/download` and `result_id`. After Task 2 the POST moved into `Search.jsx` as Task 2 itself prescribes (state and `onDownload` passed into ResultRow). The tracer commit did satisfy the criterion; the final code has both strings in `Search.jsx`, and the key link `ResultRow -> /api/download` is realised through `onDownload`.
- The exact-body assertion for the "type of the producing search" test compares `.type` rather than the whole object, because the TAP adapter of the RED classifier rejects multi-line vitest diffs. The exact-body `toEqual({result_id, type})` test remains in "posts exactly {result_id, type}".

**Total deviations:** 2 auto-fixed (1 bug, 1 blocking), 2 wording notes. **Impact:** none on scope.

## Authentication Gates

None.

## Known Stubs

None.

## Threat Flags

None. The only new request is the one the threat model already covers (T-01-45, T-01-46, T-01-47 mitigated by tests; T-01-SC: no packages added).

## Issues Encountered

None. The real tap from a phone remains the end-of-phase human check in 01-09, whose smoke `all` starts the first real download.

## Next Phase Readiness

Ready for 01-09. Row-state copy lives in `messages.js`; tap targets are 48 px and styles are class-only (CSP safe).

## Self-Check: PASSED

- Files modified exist: Search.jsx, ResultRow.jsx, messages.js, styles.css, both test files.
- Commits 0782508, ca5e19a, 08c88e1 are ancestors of HEAD.
- Acceptance greps pass: `Started ✓`, `Preparing`, D-13 text, `Already added`, `Search expired. Search again.` in messages.js; `never_success` tests in ResultRow.test.jsx.
- Plan verification: `npm --prefix frontend test` green (100); served bundle references `/api/download`; `POST /api/download` without session answers 401.
