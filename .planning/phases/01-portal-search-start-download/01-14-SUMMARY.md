---
phase: 01-portal-search-start-download
plan: 14
subsystem: api
tags: [qbittorrent, fastapi, tdd, gap-closure, stop-condition, pytest]

requires:
  - phase: 01-portal-search-start-download
    provides: download pipeline, QbitClient, FakeQbit, real-engine guard (plans 01-01..01-13)
provides:
  - "add_torrent sends stopCondition=MetadataReceived on every route and has no stopped parameter"
  - "FakeQbit models a plugin downloader that prints a magnet and the 5.2.4 stop-condition semantics"
  - "four-route zero-payload test, plus a real-engine guard for the magnet-printing plugin route"
affects: [01-15, 01-16, phase-2.1]

actuals:
  tokens: 7700
  tasks: 3
  commits: 4
plan_head_before: 949a0cfe385050c336c709e3b254ae354e048c1a
plan_head_after: ac423bc348f5e7939818b6ae6b73ebd7ba09d727

tech-stack:
  added: []
  patterns:
    - "One add form for every route; qBittorrent itself pauses a metadata-complete torrent under the stop condition"
    - "Fake qBittorrent pinned to the real engine's behaviour by its own test"

key-files:
  created: []
  modified:
    - backend/app/qbit/client.py
    - backend/app/download/pipeline.py
    - backend/tests/fakeqbit.py
    - backend/tests/test_download_pipeline.py
    - backend/tests/integration/test_real_qbit.py

key-decisions:
  - "Every torrents/add carries stopCondition=MetadataReceived; the stopped form field is gone and add_torrent cannot send it (reverts WR-04, restores FILT-02 / D-23 as written)"
  - "The fake treats the stop condition as holding any torrent at add (magnet at metadata, metadata-complete torrent paused), citing sessionimpl.cpp:2794-2801"

patterns-established:
  - "Signature test forbids a stopped parameter on add_torrent, so the defect cannot return silently"
  - "Real-engine guard fails on a stoppedDL row without metadata (the G-01-3 signature)"

requirements-completed: [FILT-02, DOWN-01, DOWN-03]

coverage:
  - id: D1
    description: "A page result whose plugin downloader prints a magnet (limetorrents, torrentproject) fetches metadata, passes the allowlist and ends started, well under METADATA_TIMEOUT"
    requirement: DOWN-01
    verification:
      - kind: integration
        ref: "backend/tests/test_download_pipeline.py#test_a_page_result_whose_downloader_prints_a_magnet_fetches_metadata_and_starts"
        status: pass
    human_judgment: false
  - id: D2
    description: "Every add on all four routes carries the stop condition, never the stopped field, and holds zero payload before the allowlist (also on rejection)"
    requirement: FILT-02
    verification:
      - kind: integration
        ref: "backend/tests/test_download_pipeline.py#test_no_route_downloads_a_payload_byte_before_the_allowlist"
        status: pass
      - kind: integration
        ref: "backend/tests/test_download_pipeline.py#test_a_downloader_magnet_without_a_video_is_rejected_with_zero_payload"
        status: pass
      - kind: unit
        ref: "backend/tests/test_download_pipeline.py#test_add_torrent_always_sends_the_stop_condition_and_never_stopped"
        status: pass
    human_judgment: false
  - id: D3
    description: "The fake qBittorrent behaves like 5.2.4 for stop conditions and downloader-printed magnets"
    requirement: DOWN-03
    verification:
      - kind: unit
        ref: "backend/tests/test_download_pipeline.py#test_the_fake_holds_a_metadata_complete_torrent_added_with_the_stop_condition"
        status: pass
    human_judgment: false
  - id: D4
    description: "Opt-in real-engine test drives a magnet-printing plugin result for a Blender open movie through the portal"
    requirement: DOWN-01
    verification: []
    human_judgment: true
    rationale: "Needs the running stack, a live indexer and a swarm; it is skipped here without QBIT_TEST_URL and is run once against the real engine by plan 01-16"

duration: 9min
completed: 2026-10-22
status: complete
---

# Phase 1 Plan 14: Stop condition on every add (G-01-3 a) Summary

**Every torrents/add now sends stopCondition=MetadataReceived and never the stopped field, so a limetorrents or torrentproject result whose downloader prints a magnet fetches its metadata and starts instead of ending "unavailable" after 300 s.**

## Performance

- **Duration:** 9 min
- **Started:** 2026-10-22T14:34Z
- **Completed:** 2026-10-22T14:43Z
- **Tasks:** 3
- **Files modified:** 5 (all under backend/)

## Accomplishments

- Client and pipeline: one add form for the four routes (direct magnet, downloader to magnet, downloader to .torrent, URL to .torrent). `add_torrent` lost its keyword-only stop flag; the pipeline no longer derives a stopped decision from the search URL. Docstrings cite qBittorrent 5.2.4 `sessionimpl.cpp:2794-2801`.
- Fake qBittorrent: new `downloader_magnets` knob (page URL to the magnet the plugin prints); the add params apply to whatever the downloader produced; a torrent runs at add only with neither flag; a stopped magnet still never fetches metadata.
- Tests: tracer test for the UAT route, four-route zero-payload test, rejection with `downloaded == 0` at delete time, slow-metadata preparing-then-started on the new route, a test that pins the fake to the 5.2.4 behaviour, and the two WR-04 tests flipped.
- Real-engine guard: synthetic torrents use the portal's stop-condition form; the evidence-only stop-condition test is gone; a new opt-in test taps an open-licensed Blender result from a magnet-printing plugin.

## TDD record

**RED** (commit `6d485c9`): `test_a_page_result_whose_downloader_prints_a_magnet_fetches_metadata_and_starts` run against the unchanged client and pipeline.
- Evidence: pytest JUnit report passed through `gsd_run check tdd-red-evidence`, verdict `RED_EVIDENCE_OK` (reason `target_test_failed`, 1 test, 1 failure, format junit).
- The assertion failed as planned: `assert 'unavailable' == 'started'`. The old code added the page result fully stopped, the fake printed a magnet, and a stopped magnet never fetched metadata.
- `semanticAssessment`: the target test executed and failed on the planned assertion (job status) for the intended reason (the stopped add of a downloader-printed magnet). No setup, import or fixture fault; the other 370 tests passed in the same run.

**GREEN** (commit `ab43662`): client and pipeline send the single stop-condition form; the tracer, the flipped signature test and the downloader test pass; full suite 371 passed.

**REFACTOR:** none needed.

**Mutation check (Task 2):** temporarily swapping the form to `stopped=true` made 27 pipeline tests fail; the source was restored before committing.

## Task Commits

1. **Task 1: Tracer** - RED `6d485c9` (test), GREEN `ab43662` (feat)
2. **Task 2: Four-route zero-payload tests** - `cfc4bae` (test)
3. **Task 3: Real-engine guard** - `ac423bc` (test)

**Plan metadata:** recorded in the docs commit that follows this file.

## Files Created/Modified

- `backend/app/qbit/client.py` - `add_torrent` always sends `stopCondition=MetadataReceived`; no stopped parameter
- `backend/app/download/pipeline.py` - one add call for every route; module docstring step 1 rewritten
- `backend/tests/fakeqbit.py` - `downloader_magnets`, 5.2.4 stop-condition semantics, shared pending-response helper
- `backend/tests/test_download_pipeline.py` - tracer, four-route, rejection, slow-metadata and fake-fidelity tests; two WR-04 tests flipped
- `backend/tests/integration/test_real_qbit.py` - stop-condition form on synthetic adds, magnet-printing plugin test, evidence-only test removed

## Decisions Made

- Restored FILT-02 / D-23 as written: one add form, nothing else. A metadata-complete torrent is held by qBittorrent itself, so the zero-payload property no longer depends on a stopped add.
- The fake now holds any torrent added with the stop condition; a torrent added with neither flag still gets `downloaded = 1`, so a pipeline that dropped the condition would be caught.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical] Two consecutive polls before the real-engine test calls a torrent "stopped without metadata"**
- **Found during:** Task 3
- **Issue:** The plan says to fail at once on a stoppedDL/pausedDL row with no readable file list. At the instant metadata arrives a magnet stops itself and the file list can lag by one poll, so a single observation could fail a correct run (a false alarm on the first real-engine run in plan 01-16).
- **Fix:** The test fails on the second consecutive such observation (about 4 s at the 2 s poll). A stopped magnet that never gets metadata stays in that state, so the G-01-3 defect is still caught.
- **Files modified:** `backend/tests/integration/test_real_qbit.py`
- **Committed in:** `ac423bc`

---

**Total deviations:** 1 auto-fixed (1 missing critical)
**Impact on plan:** Stricter-against-flakiness, same detection power. No scope creep.

## Issues Encountered

None. No production change was needed in Task 2 (the Task 1 fix was complete).

## Verification

- `uv run --project backend --frozen pytest backend/tests -q`: 378 passed (370 at HEAD), 4 deselected
- `uv run --project backend --frozen pytest backend/tests/integration -m integration -q -rs`: 4 skipped, reason "QBIT_TEST_URL is not set"
- `uv run --project backend --frozen pytest infra/tests -q`: 61 passed
- `uv run --project backend --frozen ruff check backend`: All checks passed
- Acceptance greps: `"stopped"` in client.py 0, `["stopped"] ==` in the pipeline tests 0, `downloader_magnets` in the fake 2, `sessionimpl.cpp` in client.py 1, `"stopped": "true"` in the real-engine file 0

## TDD Gate Compliance

RED (`test(01-14)` `6d485c9`) precedes GREEN (`feat(01-14)` `ab43662`). No gate violation.

## Known Stubs

None.

## Threat Flags

None. No new endpoint, auth path or trust boundary; the change narrows the add form (T-01-50, T-01-51, T-01-52 mitigated as planned; T-01-53 limited to the opt-in test and the Blender title list).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 01-16 rebuilds the stack and runs the real-engine guard, including the new magnet-printing plugin test (skipped here: needs the running stack and a live swarm).
- The D-23 re-affirmation note in 01-CONTEXT.md is left to plan 01-16, as planned.

## Self-Check: PASSED

- FOUND: backend/app/qbit/client.py, backend/app/download/pipeline.py, backend/tests/fakeqbit.py, backend/tests/test_download_pipeline.py, backend/tests/integration/test_real_qbit.py
- FOUND commits: 6d485c9, ab43662, cfc4bae, ac423bc

---
*Phase: 01-portal-search-start-download*
*Completed: 2026-10-22*
