---
phase: 01-portal-search-start-download
plan: 12
subsystem: frontend
tags: [preact, vitest, search, polling, italian-ui, xss]
status: complete

requires:
  - phase: 01-portal-search-start-download
    provides: "01-07 POST /api/search + GET /api/search/{id} snapshots; 01-11 login shell with main area and api.js"
provides:
  - "Search.jsx: Film/Serie TV toggle, query box, Cerca, 700 ms polling, searching/empty/timeout/error states"
  - "ResultRow.jsx: li.result with name, size, seeders, muted leechers/source, quality badge"
  - "MSG keys: typeFilm, typeSerie, queryPlaceholder, searchButton, searching, noResults, searchTimedOut, notReady, queryTooShort, searchFailed, seedUnit, leechUnit"
affects: [01-13, 01-09]

plan_head_before: d5feb53f4c7645b3785233eed10f8418329a7880
plan_head_after: 816dd365a1e2f09493175c24e44d74d8b4b55614

actuals:
  tokens: 6000
  tasks: 2
  commits: 3

tech-stack:
  added: []
  patterns:
    - "Polling loop guarded by a runId ref: a new search or unmount bumps it and clears the timer, so no stale loop continues"
    - "searchErrorMessage maps ApiError status to MSG keys only (503 notReady, 422 queryTooShort, 0 serverUnreachable, else searchFailed, 401 silent because App returns to login)"
    - "Result names rendered only as Preact text children; rows keyed by result_id"

key-files:
  created:
    - frontend/src/Search.jsx
    - frontend/src/ResultRow.jsx
    - frontend/src/__tests__/Search.test.jsx
    - frontend/src/__tests__/ResultRow.test.jsx
  modified:
    - frontend/src/App.jsx
    - frontend/src/messages.js
    - frontend/src/styles.css
    - frontend/src/__tests__/App.test.jsx

key-decisions:
  - "Added MSG.searchFailed ('Qualcosa è andato storto. Riprova.') for poll errors such as 404 search_not_found, so nothing technical is ever shown"
  - "ResultRow takes only { result }; Search passes type as an extra prop for 01-13 to use"

requirements-completed: [SRCH-01, SRCH-02, SRCH-03, PUI-01, PUI-02]

duration: 15min
completed: 2026-10-22
---

# Phase 1 Plan 12: Search screen and result rows Summary

**Preact search screen: Film/Serie TV toggle, 700 ms live polling through Caddy, D-09 result rows with quality badge, and plain-Italian searching, empty, timeout and error states**

## Performance

- **Duration:** about 15 min
- **Tasks:** 2 of 2 (tracer + TDD)
- **Files:** 8 changed (4 created, 4 modified)

## Accomplishments

- Tracer: after login the main area renders `Search`; POST `{q, type}` then poll `/api/search/{id}` every 700 ms until `done`. Proven on the real stack: the bundle served by Caddy references `/api/search` and the smoke search through the same origin returned rows.
- Polling stops on done, on a new search and on unmount (T-01-44).
- Phone states: spinner + "Ricerca in corso…" while running, "Nessun risultato. Prova con altre parole." / "La ricerca ha impiegato troppo tempo. Riprova." on zero rows, Italian-only error messages for 503, 422, network and poll failures.
- Row layout per D-09 with muted leechers and source, plus a quality pill; 48 px segmented toggle, wrapping names, no inline styles.

## TDD (Task 2)

- **RED** (7d7b017): 11 tests failed on the planned assertions (missing seed unit, missing muted meta line, missing badge, missing searching indicator, empty/timeout/503/422/network/poll-error messages, message cleared on new search). Semantic assessment: all failures were assertion failures on the behavior to build (e.g. `expected '4.2 GB 120' to contain '120 seed'`); no import, syntax or collection errors, both test files collected. The tests for the XSS literal render, no badge on null quality, timed-out-with-results, no message before any search and re-sort DOM-node survival already passed after the tracer; they are kept as regression guards, not RED targets.
- **GREEN** (816dd36): minimal implementation; all 38 frontend tests pass.
- **REFACTOR:** none needed.

## Task Commits

1. Task 1 (tracer): `1826f41` feat(01-12): tracer search screen with live polling through Caddy
2. Task 2 RED: `7d7b017` test(01-12): add failing tests for search states and result row layout
3. Task 2 GREEN: `816dd36` feat(01-12): phone-friendly result list with searching, empty and timeout states

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Updated App.test.jsx for the new logged-in shell**
- **Found during:** Task 1
- **Issue:** App tests waited for "Accesso effettuato.", which the logged-in shell no longer renders once Search replaces it.
- **Fix:** Tests now wait for the "Cerca" button. `MSG.loggedIn` is left in messages.js, unused.
- **Files modified:** frontend/src/__tests__/App.test.jsx
- **Commit:** 1826f41

**2. [Rule 2 - Missing critical] Added `MSG.searchFailed`**
- **Issue:** Plan listed messages for 503, 422 and network only; a poll failing with 404 `search_not_found` would otherwise show nothing or technical text (PUI-02).
- **Fix:** Generic Italian fallback message.
- **Commit:** 816dd36

**3. Live probe keywords:** the plan's precondition and verify use `--q 1080p`; per the run instructions to keep public-site queries benign, `Sintel` (film) and `Pioneer One` (serie) were used instead. The check is equivalent (search API answers with rows through Caddy).

None of these changed scope beyond the plan's intent.

## Issues Encountered

None.

## Known Stubs

None.

## Threat Flags

None. T-01-28 (no `dangerouslySetInnerHTML`, text-only rendering, XSS test) and T-01-44 (polling cancelled on new search/unmount, tests) are mitigated. No new packages (lockfile `npm ci` only).

## Flagged assumptions

- PUI-01 relies on the 48 px controls and wrapping rows; the real-phone check (360 px) is still owned by 01-09.

## Verification

- `npm --prefix frontend test`: 5 files, 38 tests pass.
- `docker compose up -d --build --wait`: all services healthy; served bundle contains `/api/search` and "Ricerca in corso…".
- `scripts/smoke.py search` film `Sintel` (2 results) and serie `Pioneer One` (17 results) OK through port 80. No download started.
- `grep dangerouslySetInnerHTML frontend/src`: empty; `min-height: 48px` present in styles.css.

## Self-Check: PASSED

Files exist, commits 1826f41, 7d7b017, 816dd36 are ancestors of HEAD.
