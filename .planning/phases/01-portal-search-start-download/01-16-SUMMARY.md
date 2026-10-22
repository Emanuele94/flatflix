---
phase: 01-portal-search-start-download
plan: 16
subsystem: download
tags: [fastapi, preact, allowlist, unsupported-format, gap-closure, real-engine-guard]

requires:
  - phase: 01-portal-search-start-download
    provides: "stop-condition adds and the real-engine plugin test (01-14), reload-safe saved search (01-15)"
provides:
  - "decide() reason video_format vs no_video; OTHER_VIDEO_EXTENSIONS picks wording only"
  - "JobState.UNSUPPORTED: a .webm-only torrent is deleted with its files, never started, API body still {status, job_id}"
  - "Row text 'This video format isn’t supported. Try another result.' (not retryable, never success, restored after a reload)"
  - "D-13 amendment, D-23 re-affirmation and D-24 recorded in 01-CONTEXT.md"
  - "Laptop stack rebuilt and checked: all three G-01-3 fixes served, real-engine guard 4 passed"
affects: [UAT test 3 phone re-test, phase-02 downloads list (DOWN-04)]

actuals:
  tokens: 5081
  tasks: 3
  commits: 5
plan_head_before: 34ad5174c3b04d5e5cf41444face45b767d7b29f
plan_head_after: ff973034aaa331fdd592c2fae1c6af6f5c29e64a

tech-stack:
  added: []
  patterns:
    - "A rejection reason from the pure decision function picks the job state; the allowlist itself is untouched"

key-files:
  created: []
  modified:
    - backend/app/download/allowlist.py
    - backend/app/download/jobs.py
    - backend/app/download/pipeline.py
    - backend/tests/test_allowlist.py
    - backend/tests/test_download_pipeline.py
    - frontend/src/messages.js
    - frontend/src/ResultRow.jsx
    - frontend/src/Search.jsx
    - frontend/src/__tests__/Search.test.jsx
    - frontend/src/__tests__/ResultRow.test.jsx
    - .planning/phases/01-portal-search-start-download/01-CONTEXT.md

key-decisions:
  - "FILT-02 allowlist unchanged (.mkv .mp4 .avi .m4v); OTHER_VIDEO_EXTENSIONS is read only to choose the rejection wording (user option B, 2026-10-22)"
  - "unsupported is a final, non-retryable job state with its own text; D-13 text kept for a torrent with no video at all"
  - "Reload persistence recorded as D-24 (sessionStorage, reversible); D-23 re-affirmed for plugin-printed magnets"

requirements-completed: [FILT-02, DOWN-01, PUI-02]

coverage:
  - id: D1
    description: "A .webm-only torrent is deleted with its files before any payload and the API answers unsupported"
    requirement: FILT-02
    verification:
      - kind: unit
        ref: "backend/tests/test_download_pipeline.py#test_a_webm_only_torrent_is_unsupported_deleted_and_never_started"
        status: pass
    human_judgment: false
  - id: D2
    description: "The FILT-02 video list is pinned unchanged; a mixed .mkv + .webm torrent keeps only the .mkv"
    requirement: FILT-02
    verification:
      - kind: unit
        ref: "backend/tests/test_allowlist.py#test_the_filt02_video_list_is_unchanged_and_webm_is_never_in_it"
        status: pass
      - kind: unit
        ref: "backend/tests/test_allowlist.py#test_a_mixed_mkv_and_webm_torrent_keeps_only_the_mkv"
        status: pass
    human_judgment: false
  - id: D3
    description: "The row says the format text, never shows success, has a disabled button, and a reload restores it"
    requirement: PUI-02
    verification:
      - kind: unit
        ref: "frontend/src/__tests__/Search.test.jsx#brings back an unsupported row with the format message and a disabled button"
        status: pass
      - kind: unit
        ref: "frontend/src/__tests__/ResultRow.test.jsx#never_success: state unsupported never renders Started or a check mark"
        status: pass
    human_judgment: false
  - id: D4
    description: "The running stack serves the new bundle and backend; the real engine accepts the stop-condition adds on every route the guard covers"
    requirement: DOWN-01
    verification:
      - kind: integration
        ref: "QBIT_TEST_URL=http://127.0.0.1:8088 pytest backend/tests/integration -m integration -q -rs (4 passed in 10.69s)"
        status: pass
    human_judgment: true
    rationale: "Phone re-test of UAT test 3 on a real device is the next step and is not automated"
---

# Phase 1 Plan 16: Unsupported video format and stack proof Summary

**A torrent whose only videos are .webm (or another non-allowlisted format) now ends as its own `unsupported` status with the text "This video format isn’t supported. Try another result.", the FILT-02 allowlist is untouched, and the rebuilt laptop stack passes the real-engine guard (4 passed, 0 skipped).**

## Performance

- **Duration:** about 6 min of wall time per the commit clock (16:50 to 16:56 local, stack rebuild and guard included)
- **Tasks:** 3 (1 tracer, 2 auto), all TDD where planned
- **Files modified:** 11

## Accomplishments

- Backend: `decide()` returns reason `video_format` when the only videos are in `OTHER_VIDEO_EXTENSIONS` (non-sample), else `no_video`; `_process` maps that to `JobState.UNSUPPORTED`, deleting with files, no start, no filePrio call. Reconcile resumes use the same path.
- Frontend: `MSG.unsupportedFormat`, `MESSAGE.unsupported` (warn, no retry), `unsupported` added to `JOB_STATES` so `ROW_STATES` and the reload restore pick it up. The D-13 text is unchanged.
- 01-CONTEXT.md: D-13 amended, D-23 re-affirmed, D-24 added under "UAT gap decisions", Specific Ideas extended.
- Stack: `docker compose up -d --build --wait` healthy; doctor OK; served bundle `/assets/index-D0xfx9Od.js` contains `sessionStorage` and `video format`; the running backend has no `stopped` parameter on `QbitClient.add_torrent` and `JobState.UNSUPPORTED.value == "unsupported"`; `smoke.py login` all OK.

## Real-engine guard (Task 3 step 6)

- Command: `QBIT_TEST_URL=http://127.0.0.1:8088 uv run --project backend --frozen pytest backend/tests/integration -m integration -q -rs`
- Summary line: `4 passed in 10.69s` (0 failed, 0 skipped, so there are no skip reasons to list)
- This includes `test_a_plugin_result_whose_downloader_prints_a_magnet_fetches_metadata_with_zero_payload`, which passed on the real engine for the first time.
- Afterwards `docker compose up -d --wait` restored the base stack; 127.0.0.1:8088 refuses connections and `docker compose ps` shows only port 80 published.

## Task Commits

1. Task 1 RED: `317ac15` test(01-16): failing tests for the unsupported video format status
2. Task 1 GREEN: `50db74d` feat(01-16): answer unsupported for a torrent whose only videos are outside the allowlist
3. Task 2 RED: `51d9c9a` test(01-16): failing tests for the unsupported video format row
4. Task 2 GREEN: `164f965` feat(01-16): show a plain message for an unsupported video format
5. Task 3: `ff97303` docs(01-16): record the G-01-3 decisions (D-13 amended, D-23 re-affirmed, D-24)

## TDD Gate Compliance

- **RED (backend):** `test_a_webm_only_torrent_is_unsupported_deleted_and_never_started` failed on `assert 'rejected' == 'unsupported'` (target test, planned assertion). The `test_allowlist.py` additions failed at collection with `ImportError: cannot import name 'OTHER_VIDEO_EXTENSIONS'`, an import-level failure because the symbol did not exist yet; semantic assessment: acceptable for the pure-function cases (they cannot run before the symbol exists), and the pipeline test supplied the assertion-level RED. `gsd_run check tdd-red-evidence` was not run: the `gsd_run` shell helper is not available in this executor shell and pytest console output is not one of the supported report formats.
- **RED (frontend):** 5 vitest tests failed on assertions about the format text and disabled state (ResultRow x2, Search outcomes, poll-to-unsupported, reload restore).
- **GREEN:** both greens pass the full suites. **REFACTOR:** none needed.

## Verification

- Backend: `386 passed, 4 deselected` (baseline 378 + 8 new); `ruff check` and `ruff format --check` clean.
- Frontend: `135 passed` (baseline 128 + 7 new); `vite build` OK.
- Acceptance greps: VIDEO_EXTENSIONS line count 1; `UNSUPPORTED = "unsupported"` 1; `video_format` in pipeline.py 1 and in test_allowlist.py 7; D-24 1; Re-affirmed 1; `isn’t supported` in CONTEXT 2; messages.js format text 1 and D-13 text 1.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] ruff import order in test_allowlist.py**
- **Found during:** Task 1 verify
- **Issue:** the new `OTHER_VIDEO_EXTENSIONS` import was not sorted (ruff I001)
- **Fix:** `ruff check --fix` on that file, folded into the GREEN commit `50db74d`
- **Files modified:** backend/tests/test_allowlist.py

**Total deviations:** 1 auto-fixed (trivial lint). **Impact:** none.

## Known Stubs

None.

## Threat Flags

None. T-01-58 to T-01-61 mitigations hold: allowlist pinned and sets asserted disjoint; never_success tests cover unsupported; Task 3 precondition (.env and qbittorrent config) was met before any compose command; the admin port was closed again and verified.

## Notes for the UAT re-test

- Phone re-test of UAT test 3 can run now against the rebuilt stack: tap a result (adds with stop condition), reload the page mid-Preparing (row and polling come back), and tap a .webm-only result (format text, nothing downloaded).
- `smoke.py all` and `download` were deliberately not run (they start a real download).
- Pre-existing untracked/modified files (`.planning/state.json`, `config.json`, `milestone.lock`, `research/`) were not staged.

## Self-Check: PASSED

All 11 modified files exist; commits 317ac15, 50db74d, 51d9c9a, 164f965, ff97303 are on the branch.
