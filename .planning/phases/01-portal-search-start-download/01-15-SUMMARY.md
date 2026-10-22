---
phase: 01-portal-search-start-download
plan: 15
subsystem: ui
tags: [preact, sessionStorage, reload-persistence, job-polling, gap-closure]

requires:
  - phase: 01-portal-search-start-download
    provides: "Search.jsx row states and pollJob (01-13), D-11 Preparing behaviour"
provides:
  - "Search.jsx saves the current search in sessionStorage and restores it after a reload"
  - "Preparing rows resume GET /api/download/{job_id} polling with their original start time"
  - "clearSavedSearch() and SAVED_SEARCH_KEY exported from Search.jsx; logout clears the saved search"
affects: [01-16, phase-02 downloads list (DOWN-04), D-24 decision record]

actuals:
  tokens: 6187
  tasks: 3
  commits: 6
plan_head_before: 4e7fbd45b64f8280dbc70a3cbc11e943a0082ab2
plan_head_after: 93dd3b57440db24114b34d72ecc67698b2025614

tech-stack:
  added: []
  patterns:
    - "Saved state is untrusted input: whole-record validation discards and removes the key, per-item validation drops one row or job"
    - "Module-level generation counter: every clear bumps it, writes from an older generation are dropped"
    - "Restore in a mount effect (never in render); every storage call inside try/catch"

key-files:
  created: []
  modified:
    - frontend/src/Search.jsx
    - frontend/src/App.jsx
    - frontend/src/__tests__/Search.test.jsx
    - frontend/src/__tests__/App.test.jsx

key-decisions:
  - "Only Search.jsx touches web storage, and only sessionStorage (per tab); the record holds {v, type, q, search_id, done, outcome, rows, jobs} and rows are cut to the seven API fields on write and on restore"
  - "A 401 (expired session) does not clear the saved search; only an explicit logout and a new search do"
  - "A saved startedAt in the future is treated as invalid (the row comes back lost), so a tampered value cannot extend polling past 330 s"

patterns-established:
  - "clear-then-bump: submit() and logout() call clearSavedSearch() first, so late async writes cannot resurrect the record"

requirements-completed: [DOWN-01, PUI-01, PUI-02]

coverage:
  - id: D1
    description: "Reloading while a row shows Preparing brings back the same rows, query and Movie/TV Series choice, the row still shows Preparing, job polling resumes and the row ends on the job's final state (G-01-3 c, D-11)"
    requirement: "DOWN-01"
    verification:
      - kind: unit
        ref: "frontend/src/__tests__/Search.test.jsx#Survives a page reload (G-01-3) brings back the rows, the query, the Movie choice and the Preparing row"
        status: pass
      - kind: unit
        ref: "frontend/src/__tests__/Search.test.jsx#Survives a page reload (G-01-3) resumes polling the job 2 s after the new mount and ends on Started, with no second POST"
        status: pass
      - kind: unit
        ref: "frontend/src/__tests__/Search.test.jsx#Survives a page reload (G-01-3) the resumed row ends on the final state of the job"
        status: pass
    human_judgment: false
  - id: D2
    description: "A new search replaces the saved search, logout removes it, and a late job answer cannot write it back"
    requirement: "PUI-02"
    verification:
      - kind: unit
        ref: "frontend/src/__tests__/Search.test.jsx#Survives a page reload (G-01-3) a new search after a restore replaces the saved search"
        status: pass
      - kind: unit
        ref: "frontend/src/__tests__/App.test.jsx#App session lifecycle saved search (G-01-3) logging in shows the restored rows; Log out removes the saved search and the next login starts empty"
        status: pass
      - kind: unit
        ref: "frontend/src/__tests__/Search.test.jsx#Survives a page reload (G-01-3) a job answer that arrives after clearSavedSearch (logout) cannot write the search back"
        status: pass
    human_judgment: false
  - id: D3
    description: "Mid-tap rows and jobs older than 330 s come back retryable with the lost message, never as an endless spinner (WR-05)"
    requirement: "PUI-01"
    verification:
      - kind: unit
        ref: "frontend/src/__tests__/Search.test.jsx#Survives a page reload (G-01-3) a pending row (POST in flight at reload) comes back as lost and retryable, with no request"
        status: pass
      - kind: unit
        ref: "frontend/src/__tests__/Search.test.jsx#Survives a page reload (G-01-3) a preparing row whose job is 331 s old comes back as lost and is never polled"
        status: pass
      - kind: unit
        ref: "frontend/src/__tests__/Search.test.jsx#Survives a page reload (G-01-3) a 10 s old preparing job is polled and gives up at the original 330 s mark"
        status: pass
    human_judgment: false
  - id: D4
    description: "The saved record holds only the planned keys and the seven API row fields; tampered or unreadable data is discarded without a request or an error; ids from storage must match 16 hex before any request; a browser whose sessionStorage throws still works"
    requirement: "PUI-02"
    verification:
      - kind: unit
        ref: "frontend/src/__tests__/Search.test.jsx#Survives a page reload (G-01-3) saves exactly v, type, q, search_id, done, outcome, rows, jobs and only the seven API row fields"
        status: pass
      - kind: unit
        ref: "frontend/src/__tests__/Search.test.jsx#Survives a page reload (G-01-3) tampered data (...) shows the empty start screen, sends no request and removes the key"
        status: pass
      - kind: unit
        ref: "frontend/src/__tests__/Search.test.jsx#Survives a page reload (G-01-3) tampered jobs: an unknown state or a path-like job id is dropped and never requested"
        status: pass
      - kind: unit
        ref: "frontend/src/__tests__/Search.test.jsx#Survives a page reload (G-01-3) a browser whose sessionStorage throws still searches and downloads"
        status: pass
      - kind: unit
        ref: "frontend/src/__tests__/App.test.jsx#App session lifecycle never writes to web storage during login and logout"
        status: pass
    human_judgment: false
  - id: D5
    description: "On a real phone the reload during Preparing feels right (list back at the same scroll area, no flash of the empty screen)"
    verification: []
    human_judgment: true
    rationale: "Perceived behaviour on a phone browser is not asserted by jsdom tests; the served-bundle check runs in plan 01-16 Task 3"

duration: 8min
completed: 2026-10-22
status: complete
---

# Phase 1 Plan 15: Reload-safe Preparing rows (G-01-3 c) Summary

**Frontend-only sessionStorage persistence in Search.jsx: a reload during "Preparing" brings back the rows, query and type, resumes job polling with the original 330 s clock, and logout or a new search clears it.**

## Performance

- **Duration:** 8 min
- **Started:** 2026-10-22T14:42:00Z (approximate; start time was not captured at launch)
- **Completed:** 2026-10-22T14:50:00Z
- **Tasks:** 3 (1 tracer, 2 auto, all TDD)
- **Files modified:** 4

## Accomplishments

- The current search is saved after every snapshot and row-state change and restored in a mount effect; a Preparing row resumes `GET /api/download/{job_id}` polling, never re-POSTs, and ends on the job's final state.
- Saved data is treated as untrusted: whole-record rules discard it (and remove the key), per-item rules drop one bad row or job, `search_id` and `job_id` must match `^[0-9a-f]{16}$` before any request, and a future `startedAt` is rejected.
- Mid-tap (`pending`) rows and jobs older than 330 s come back as `lost` (retryable, existing MSG copy), never as a spinner. No new UI copy was added.
- `logout()` calls `clearSavedSearch()` first; a module-level generation counter drops late writes from the unmounting screen. The existing "never writes to web storage during login and logout" test is untouched and green.
- Test count 104 -> 128; `npm --prefix frontend run build` succeeds.

## Task Commits

1. **Task 1: Tracer - reload during Preparing** - RED `5280505` (test), GREEN `77466d6` (feat)
2. **Task 2: Restore edge cases** - RED `5fb6ed4` (test), GREEN `e11e6f8` (feat)
3. **Task 3: Logout clears the saved search** - RED `55efe22` (test), GREEN `93dd3b5` (feat)

**Plan metadata:** committed separately (docs: complete plan)

## TDD Gate Compliance

All three tasks have a `test(01-15)` commit before the matching `feat(01-15)` commit. No REFACTOR commits were needed (the small `if (!snap.done) poll(...)` tidy was folded into the Task 2 GREEN commit).

- **RED 1:** 5 of the 6 new reload tests failed on assertions (query box empty after the new mount, no resumed poll). Classifier: `RED_EVIDENCE_OK` on the target "brings back the rows, the query, the Movie choice and the Preparing row". Semantic assessment: the target ran and failed on the planned assertion for the intended reason (nothing saved or restored). The "writes nothing before the first search" test passed before the implementation by design: it is a negative guard.
- **RED 2:** 12 of the 17 new edge-case tests failed on assertions. Classifier: `RED_EVIDENCE_OK` on the "331 s old" target (run filtered to `pending row|331 s`, see Issues). Semantic assessment: lost-state mapping, key removal, row/job dropping and the seven-field copy were all missing. 10 s old polling, empty/timeout messages and throwing storage already passed because Task 1 code and its try/catch covered them; these are kept as regression guards.
- **RED 3:** the App logout test failed on "key still present after Log out". Classifier: `RED_EVIDENCE_OK`. The Search late-answer test passed already because the generation guard from Task 1 covers it, as the plan predicted; no guard fix was needed.

## Files Created/Modified

- `frontend/src/Search.jsx` - `SAVED_SEARCH_KEY`, `clearSavedSearch`, `writeSaved`, `readSaved`, `restoreJobs`, `pickRow`, `ROW_STATES`; persist calls in `setJob`, `submit`, `poll`; restore effect; `applyJob` stores `startedAt`.
- `frontend/src/App.jsx` - imports and calls `clearSavedSearch()` first in `logout()`.
- `frontend/src/__tests__/Search.test.jsx` - "Survives a page reload (G-01-3)" block (reload helper, seeded-record tests, tamper cases, throwing storage, late answer); `sessionStorage.clear()` in `beforeEach`, `vi.restoreAllMocks()` in `afterEach`.
- `frontend/src/__tests__/App.test.jsx` - restored-then-logout test; `sessionStorage.clear()` in `afterEach`.

## Decisions Made

- Rows are cut to the seven API fields on both write and restore, and only primitive field values survive, so an object planted in storage cannot reach the render.
- A saved `startedAt` later than now is invalid and the row comes back `lost`: otherwise a tampered value could keep polling past the 330 s limit.
- The unmount cleanup does not touch storage (a reload is an unmount); only `submit()` and `logout()` clear it. A 401 keeps the saved search (plan assumption).
- Test-only: the App seeded test asserts `getItem(...) === null` with `toBe(true)` so the failure report stays parseable by the RED-evidence classifier.

## Deviations from Plan

None - plan executed exactly as written. (The late-answer test needed no fix to the generation guard.)

**Total deviations:** 0
**Impact on plan:** none.

## Issues Encountered

- The RED-evidence classifier rejected the full-file TAP report (`Non-TAP data`) when failures printed multi-line diffs or quoted JSON, a vitest tap-flat escaping limitation. Resolved by re-running the same target with a vitest `-t` name filter, and by shaping the App assertion as a boolean; the underlying tests are unchanged.
- `PLAN_START_TIME` was not captured at launch, so the start time above is approximate.

## Known Stubs

None.

## Threat Flags

None. The only new surface is sessionStorage in Search.jsx, covered by T-01-54 to T-01-57 in the plan's threat model.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Ready for 01-16: add `unsupported` to `JOB_STATES` only (`ROW_STATES` derives from it); record D-24 in 01-CONTEXT.md; Task 3 there does the one rebuild and the served-bundle check (bundle mentions sessionStorage).
- DOWN-04 (downloads list / active-jobs endpoint) stays in Phase 2; nothing here blocks it.

## Self-Check: PASSED

- Files modified exist: `frontend/src/Search.jsx`, `frontend/src/App.jsx`, `frontend/src/__tests__/Search.test.jsx`, `frontend/src/__tests__/App.test.jsx`.
- Commits `5280505`, `77466d6`, `5fb6ed4`, `e11e6f8`, `55efe22`, `93dd3b5` are ancestors of HEAD (6 commits measured from `plan_head_before`).
- `npm --prefix frontend test`: 128 passed; `npm --prefix frontend run build`: ok.
- `grep -rlE 'localStorage|sessionStorage' frontend/src --exclude-dir=__tests__` prints only `frontend/src/Search.jsx`.
