---
phase: 02-portal-download-management-hardening
plan: 06
subsystem: ui
tags: [preact, vite, tabs, polling, page-visibility, progress, tdd, css]
status: complete

requires:
  - phase: 02-portal-download-management-hardening
    provides: "GET /api/downloads contract with ordered rows and states (plan 02-01); failed job rows (plan 02-04)"
provides:
  - "Search | Downloads tab bar in App.jsx with roving tabindex and Left/Right/Home/End keys; Search always mounted in a hidden panel"
  - "Downloads({ onGoToSearch }) with a visibility-aware 5 s setTimeout chain, outage banner over a greyed list, loading and empty states, in-session cache, clearDownloadsCache()"
  - "DownloadRow({ item, stale }) pure view for all nine backend states; formatEta(seconds) in eta.js"
  - "All 31 Phase 2 MSG keys (plans 02-08 and 02-10 add no strings)"
  - "Phase 2 CSS: tabs, rows, native progress colours, confirm panel, .btn-destructive, [hidden], reduced motion, Phase 1 typography edits"
affects: [02-08, 02-10, 02-11]

actuals:
  tokens: 10000
  tasks: 3
  commits: 5

commits: 5
plan_head_before: 4f8edffdf9dc6c7fe7162f187ea144f0e36819a1
plan_head_after: 55919ec71a74fd31b690e8296d9f56f73f8bc630

tech-stack:
  added: []
  patterns:
    - "Polling as a setTimeout chain started after each answer settles, with an epoch counter that drops late answers and a visibilitychange listener (only 'hidden' pauses, jsdom never reports 'visible')"
    - "One lookup table keyed by the backend state code gives text, tone, bar kind and hint; the frontend has no second state logic"
    - "Native <progress> coloured by modifier classes on the element, so no inline style attribute exists (CSP)"

key-files:
  created:
    - frontend/src/Downloads.jsx
    - frontend/src/DownloadRow.jsx
    - frontend/src/eta.js
    - frontend/src/__tests__/Downloads.test.jsx
    - frontend/src/__tests__/DownloadRow.test.jsx
    - frontend/src/__tests__/eta.test.js
  modified:
    - frontend/src/App.jsx
    - frontend/src/messages.js
    - frontend/src/styles.css
    - frontend/src/__tests__/App.test.jsx

key-decisions:
  - "A 401 poll shows nothing and the chain keeps scheduling: the global handler unmounts the panel, and if no handler is registered the list is simply left as it was"
  - "While a problem is set, a known-empty list shows only the banner (not the empty state): an unknown state is never presented as 'No downloads yet'"
  - "Tab buttons are written out as two literal role=\"tab\" buttons (not a map) so the plan's grep gate and the markup stay greppable"
  - "Ready rows always render value 100 and '100%' regardless of the progress field"

requirements-completed: [DOWN-04, DOWN-06]

coverage:
  - id: D1
    description: "After login two tabs show with Search selected; the Downloads tab lists the backend rows; Search keeps its typed value across a tab switch; arrow keys switch tabs"
    requirement: "DOWN-04"
    verification:
      - kind: unit
        ref: "frontend/src/__tests__/App.test.jsx#App tabs (D-26)"
        status: pass
    human_judgment: false
  - id: D2
    description: "Polling is a 5000 ms setTimeout chain after each answer, pauses while the page is hidden, resumes at once on visibilitychange, stops on unmount, and ignores late or older answers"
    requirement: "DOWN-04"
    verification:
      - kind: unit
        ref: "frontend/src/__tests__/Downloads.test.jsx#polling (D-31)"
        status: pass
    human_judgment: false
  - id: D3
    description: "Outage keeps the last list greyed under a plain banner (down vs refused wording), polls on, clears by itself; a failed first load never shows the empty state; no status code, detail code or 'error' reaches the DOM"
    requirement: "DOWN-06"
    verification:
      - kind: unit
        ref: "frontend/src/__tests__/Downloads.test.jsx#outage (D-36, DOWN-06)"
        status: pass
    human_judgment: false
  - id: D4
    description: "Loading line, empty state with Go to Search, and the in-session cache that shows at once on remount and is cleared by logout"
    requirement: "DOWN-04"
    verification:
      - kind: unit
        ref: "frontend/src/__tests__/Downloads.test.jsx#first load, empty list and session cache"
        status: pass
    human_judgment: false
  - id: D5
    description: "formatEta boundaries and every row state (bar, tone, hint, ETA), name fallback, missing badge, literal markup name, no style attribute"
    requirement: "DOWN-04"
    verification:
      - kind: unit
        ref: "frontend/src/__tests__/eta.test.js"
        status: pass
      - kind: unit
        ref: "frontend/src/__tests__/DownloadRow.test.jsx"
        status: pass
    human_judgment: false
  - id: D6
    description: "A 200-character name without spaces causes no horizontal scroll at 320 px; iOS Safari and Android Chrome draw the blue, amber, green and indeterminate progress bar as specified"
    requirement: "DOWN-04"
    verification:
      - kind: manual
        ref: "Real-phone pass in plan 02-11 (UI-SPEC backstops)"
        status: untested
    human_judgment: true
---

# Phase 2 Plan 06: Downloads tab Summary

**Search | Downloads tabs with a visibility-aware 5 s live list, plain per-state rows with native progress and ETA, and a calm self-clearing outage banner, all in Preact with no new dependency.**

## Performance

- **Duration:** about 3.5 min of wall clock between start and summary
- **Tasks:** 3 (1 tracer, 2 TDD)
- **Files:** 6 created, 4 modified

## Accomplishments

- The household sees two tabs under the header; Search is the default and stays mounted behind the `hidden` attribute, so its form, results and row states survive a switch.
- The Downloads tab fetches on mount, then 5000 ms after each answer settles; it sleeps while the page is hidden, wakes on `visibilitychange`, and stops on unmount. A late or older answer is ignored by an epoch check.
- Nine row states render from one lookup table: spinner plus indeterminate bar for Preparing, blue bar with % and rough ETA for Downloading, amber bar and hint for Stalled, green full bar for Ready, text only for Problem and the four failed-job states.
- An outage greys the last list and shows "Can’t reach the download service. Retrying…" (or "…has a problem. Ask the admin." for `qbit_refused`), keeps polling, and clears with no extra message. A failed first load shows only the banner.
- All 31 Phase 2 copy keys are in `messages.js`; the CSS carries the whole Phase 2 contract plus the three Phase 1 typography edits (four sizes, two weights, no `font-weight: 700` left).

## Task Commits

1. **Task 1 (tracer): tabs and first list path** - `57f1b70` (feat)
2. **Task 2 RED: failing tests for the live list** - `4db5820` (test)
3. **Task 2 GREEN: polling, banner, empty and loading states** - `652f821` (feat)
4. **Task 3 RED: failing tests for ETA and row states** - `e9b369f` (test)
5. **Task 3 GREEN: every row state, formatEta, Phase 2 CSS** - `55919ec` (feat)

## TDD Notes

- **Task 2 RED:** 11 of 16 tests failed on planned assertions (request count after 5 s, missing loading line, missing empty-state heading, missing banner text). The 5 that passed were negative cases (nothing scheduled while hidden, nothing after unmount) that a missing implementation satisfies trivially. No load, syntax or fixture errors. Semantic assessment: the failing tests are the targets and fail for the intended reason.
- **Task 3 RED:** `eta.js` was committed as a stub returning null so the test file compiles; 16 of 34 tests failed on assertions (null instead of ETA wording, missing hint text, missing ETA and % elements). Semantic assessment: valid RED.
- The plan is `type: execute`, so the `gsd_run check tdd-red-evidence` classifier was not run (it applies to plan-level `type: tdd`); the RED evidence was inspected by hand as above.
- No REFACTOR commit was needed.

## Deviations from Plan

None - plan executed as written. One judgement call: the tab buttons are two literal elements instead of a `.map`, because the Task 1 acceptance grep counts `role="tab"` occurrences.

## Issues Encountered

None.

## Known Stubs

None. `DownloadRow` accepts a `stale` prop that it does not use yet; the plan states plan 02-10 consumes it for the Cancel and Remove buttons. `Downloads` already passes it.

## Threat Flags

None. No new endpoint, auth path or storage; names render only as text children (T-02-19), only MSG strings reach the DOM (T-02-20), no inline style (T-02-21), one request at a time while visible (T-02-22), `package.json` and the lockfile are unchanged (T-02-SC).

## Verification

- `npm --prefix frontend test`: 8 files, 189 tests passed (includes the unchanged Search tests and the no-third-party test).
- `npm --prefix frontend run build`: succeeds.
- `git diff --exit-code -- frontend/package.json frontend/package-lock.json`: clean.
- Acceptance greps: `role="tablist"` 1, `role="tab"` 2, `setInterval` 0, `visibilitychange` 2, `font-weight: 700` 0, `display: none !important` 1, `prefers-reduced-motion` 1, `::-moz-progress-bar` 3, `style=` 0 in the three components.
- No docker command was run (per the plan); the live probe belongs to plan 02-11.

## Self-Check: PASSED

- Files exist: Downloads.jsx, DownloadRow.jsx, eta.js, Downloads.test.jsx, DownloadRow.test.jsx, eta.test.js.
- Commits exist: 57f1b70, 4db5820, 652f821, e9b369f, 55919ec.
