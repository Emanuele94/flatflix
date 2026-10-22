---
phase: 02-portal-download-management-hardening
plan: 10
subsystem: ui
tags: [preact, downloads, cancel, remove, confirm, outage, tdd]
status: complete

requires:
  - phase: 02-portal-download-management-hardening
    provides: "Downloads list, DownloadRow, MSG keys and confirm CSS (plan 02-06); DELETE /api/downloads/{id} (plan 02-07)"
provides:
  - "Cancel download button with an inline confirm panel (focus on No, keep it; Escape closes; no dialog) on rows whose action is cancel"
  - "Remove from list button (no confirm, files stay) on rows whose action is remove; no control on action null rows"
  - "One DELETE /api/downloads/{id} per action with only the opaque id and no body; 204 or 404 drops the row at once"
  - "Plain 'That didn’t work. Try again.' on other failures; 502 and network failures follow the outage rule; stale disables every button and closes the panel"
affects: [02-11]

actuals:
  tokens: 7700
  tasks: 2
  commits: 3

commits: 3
plan_head_before: bbcb22319620096afb0620a2819e8ffaa2fdc237
plan_head_after: 44e95b07093480fd10b331c72bc106ccdfa17120

tech-stack:
  added: []
  patterns:
    - "One act(id, kind) handler for Cancel and Remove: the browser sends only the opaque id and the server decides about files"
    - "A shared poll counter (ref) plus a removed-id map lets a poll that began before a removal be filtered, so a slow answer cannot resurrect the row"
    - "Single confirmId state: one open panel at a time, cleared by stale, by a refresh that drops the row or changes its action away from cancel"

key-files:
  created: []
  modified:
    - frontend/src/DownloadRow.jsx
    - frontend/src/Downloads.jsx
    - frontend/src/__tests__/DownloadRow.test.jsx
    - frontend/src/__tests__/Downloads.test.jsx

key-decisions:
  - "The panel stays visible while its own DELETE is in flight even if a failed poll closed the confirm, so the Cancelling... state never vanishes mid-request"
  - "A 401 on the DELETE does nothing here (the global handler owns it); busy is still cleared"
  - "A removed row is remembered with the poll number current at removal; only polls that began later are trusted to list it again"

requirements-completed: [DOWN-05, DOWN-06]

coverage:
  - id: D1
    description: "Cancel download asks once in the row, focus lands on 'No, keep it', Escape and No close it and return focus; Yes sends exactly one DELETE with the id and no body, shows Cancelling... with both buttons disabled, and 204 or 404 removes the row at once"
    requirement: "DOWN-05"
    verification:
      - kind: unit
        ref: "frontend/src/__tests__/DownloadRow.test.jsx#Cancel download (D-32)"
        status: pass
      - kind: unit
        ref: "frontend/src/__tests__/Downloads.test.jsx#cancel from the list (D-32, D-35)"
        status: pass
    human_judgment: false
  - id: D2
    description: "Remove from list is one tap with no confirm, sends one DELETE with no body, shows Removing..., removes the row on 204 or 404; failed-job rows have no button"
    requirement: "DOWN-05"
    verification:
      - kind: unit
        ref: "frontend/src/__tests__/Downloads.test.jsx#remove from list (D-33)"
        status: pass
    human_judgment: false
  - id: D3
    description: "A 500 restores the row and shows one plain sentence (role=status, warn tone); 502 unreachable, 502 refused and a network failure give the banner, greyed list and disabled buttons; the next good poll re-enables them; no status or detail code reaches the DOM"
    requirement: "DOWN-06"
    verification:
      - kind: unit
        ref: "frontend/src/__tests__/Downloads.test.jsx#action failures (D-36, D-37)"
        status: pass
    human_judgment: false
  - id: D4
    description: "One confirm panel at a time; it survives a refresh that keeps the row and closes when the row becomes ready or disappears; an older poll cannot bring a removed row back"
    requirement: "DOWN-05"
    verification:
      - kind: unit
        ref: "frontend/src/__tests__/Downloads.test.jsx#one confirm panel at a time, and only while it is true"
        status: pass
    human_judgment: false
  - id: D5
    description: "The 48 px full-width buttons, the side-by-side confirm buttons at 320 px, and the focus ring and tap feel on a real phone"
    requirement: "DOWN-05"
    verification:
      - kind: manual
        ref: "Real-phone pass in plan 02-11 (UI-SPEC backstops)"
        status: untested
    human_judgment: true
---

# Phase 2 Plan 10: Cancel and Remove from the Downloads tab Summary

**Cancel download with one in-row confirm and Remove from list with one tap, both a single id-only DELETE, with plain failures and an outage lock, in Preact with no new dependency.**

## Performance

- **Tasks:** 2 (1 tracer, 1 TDD)
- **Files:** 4 modified, none created
- **Tests:** 241 passed in the frontend suite

## Accomplishments

- A downloading, preparing, stalled or problem row shows an outlined full-width "Cancel download". Tapping it swaps the button in place for the panel "Cancel this download?" with the muted file-deletion note and side-by-side "Yes, cancel" (destructive outline) and "No, keep it". Focus goes to "No, keep it"; Escape or No closes it and focus returns to Cancel. No dialog element.
- "Yes, cancel" sends exactly one `DELETE /api/downloads/{id}` with no body, shows the spinner and "Cancelling…", disables both buttons, and a second tap sends nothing. 204 and 404 both drop the row at once, no toast.
- A ready row shows "Remove from list": one tap, one DELETE, "Removing…", row gone on 204 or 404. Failed-job rows (action null) render no action area.
- Any other failure closes the panel, keeps the row and shows "That didn’t work. Try again." under the button (role=status, warn tone); the next tap works. 502 or a network failure sets the same banner and greyed list as a failed poll.
- While the list is stale every action button is disabled and an open panel closes. Only one panel is open at a time; it survives a refresh that keeps the row and closes if the row became ready or vanished.

## Task Commits

1. **Task 1 (tracer): Cancel download, one confirm, one DELETE** - `98dac04` (feat)
2. **Task 2 RED: failing tests for Remove, failures, outage lock, confirm rules** - `f12cfe1` (test)
3. **Task 2 GREEN: Remove from list, plain failures, outage lock** - `44e95b0` (feat)

## TDD Notes

- **Task 2 RED:** 17 of 241 tests failed, all on planned assertions: "Remove from list" button not found (7), "Removing…" not found, the action sentence or banner text not found (4), and the confirm panel still open after a failed poll or a row turning ready (3), plus the slow-poll resurrection case and the stale-disabled check. No syntax, import or fixture errors. Semantic assessment: the target tests ran and failed for the intended reason; the other 224 passed unchanged.
- The plan is `type: execute`, so the plan-level `gsd_run check tdd-red-evidence` gate does not apply. I tried it anyway on a vitest `tap-flat` report and it answered `invalid_record` ("Malformed TAP"): vitest prints the multi-line DOM dump of a Testing Library failure unindented in the TAP `actual:` field, which the parser rejects. That is a reporter limitation, not an unexpected green; RED was judged by reading the failures as above.
- The tracer (Task 1) was committed once with its tests, as the plan asks. The tracer gate (re-run verify end to end) passed before Task 2 started.
- No REFACTOR commit was needed.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] A poll that began before a cancel could bring the row back**
- **Found during:** Task 2 (test "a slow poll that started before the cancel does not bring the row back")
- **Issue:** A GET already in flight when the DELETE succeeded would answer with the old list and re-add the row, so "removed at once" would flicker back.
- **Fix:** The poll counter moved from a local variable to a ref; a removed id is stored with the counter value at removal, and an answer from a poll numbered at or below it is filtered. Polls that start later are trusted again.
- **Files modified:** frontend/src/Downloads.jsx
- **Commit:** 44e95b0

No other deviations. No CSS or messages.js change was needed: every class and string from 02-06 was present.

## Issues Encountered

None.

## Known Stubs

None. `DownloadRow` now uses the `stale` prop that 02-06 left unused.

## Threat Flags

None. No new endpoint or storage. T-02-37: one confirm with focus on the safe choice, Remove never deletes the film, the panel closes when the row turns ready. T-02-38: tests assert method, path and an absent body for every DELETE. T-02-39: tests assert no 404, 500, 502, `qbit_` or `download_not_found` text in the DOM. T-02-SC: `package.json` and the lockfile are unchanged.

## Verification

- `npm --prefix frontend test`: 8 files, 241 tests passed.
- `npm --prefix frontend run build`: succeeds.
- `git diff --exit-code -- frontend/package.json frontend/package-lock.json`: clean.
- Acceptance greps: `method: 'DELETE'` 1 in Downloads.jsx; `MSG.cancelConfirmTitle` 1, `MSG.cancelConfirmNo` 1, `MSG.removeFromList` 1, `MSG.actionFailed` 1, `MSG.removing` 1, `MSG.cancelling` 1, `<dialog` 0, `style=` 0 in both components.
- No docker command was run (per the plan); the stack rebuild and the live probe belong to plan 02-11.

## Self-Check: PASSED

- Files exist: DownloadRow.jsx, Downloads.jsx, DownloadRow.test.jsx, Downloads.test.jsx.
- Commits exist: 98dac04, f12cfe1, 44e95b0.
