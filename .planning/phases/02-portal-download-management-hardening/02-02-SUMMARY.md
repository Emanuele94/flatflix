---
phase: 02-portal-download-management-hardening
plan: 02
subsystem: api
tags: [fastapi, qbittorrent, allowlist, download-pipeline, pytest, tdd]

requires:
  - phase: 01-portal-search-start-download
    provides: decide() allowlist, DownloadPipeline, FakeQbit
provides:
  - "decide() sizes the main video against the largest non-sample video of any format (D-43, WR-01)"
  - "torrents/add 415 ends the job as unavailable (DOWN-06)"
affects: [02-04, 02-06, phase-2.1]

actuals:
  tokens: 2650
  tasks: 2
  commits: 4

commits: 4
plan_head_before: 46dd130e774acd83fc3523a9bc83d505221723e3
plan_head_after: dbc0bd6132e3332e7b171fe7ea838591c7be701e

tech-stack:
  added: []
  patterns:
    - "Main video = largest non-sample video of any format; allowed videos below 10 % of it are samples or trailers"
    - "Pipeline WARNING lines carry job id, class name and HTTP status only"

key-files:
  created: []
  modified:
    - backend/app/download/allowlist.py
    - backend/app/download/pipeline.py
    - backend/tests/test_allowlist.py
    - backend/tests/test_download_pipeline.py

key-decisions:
  - "The 10 % sample ratio is measured against the largest non-sample video of any format, integer math, boundary inclusive (D-43, confirmed by the user 2026-10-22)"
  - "A 415 from torrents/add is unavailable; 409 from add stays duplicate; any other non-2xx stays failed"
  - "A failed Download tap is never re-posted automatically (a hidden re-POST could race the btih duplicate check)"

requirements-completed: [DOWN-06]

coverage:
  - id: D1
    description: "A 20 GB .m2ts film with a 100 MB .mp4 trailer is rejected as unsupported through POST /api/download: deleted with its files, never started"
    requirement: "DOWN-06"
    verification:
      - kind: integration
        ref: "backend/tests/test_download_pipeline.py#test_a_big_film_in_another_format_with_a_small_allowed_trailer_is_unsupported"
        status: pass
      - kind: unit
        ref: "backend/tests/test_allowlist.py#test_a_big_other_format_film_with_a_small_allowed_trailer_is_rejected_as_video_format"
        status: pass
    human_judgment: false
  - id: D2
    description: "The 10 % boundary holds across formats; an mkv at a fifth of an m2ts is kept; sample-named files of another format never size the main video; FILT-02 sets unchanged"
    requirement: "DOWN-06"
    verification:
      - kind: unit
        ref: "backend/tests/test_allowlist.py#test_the_ten_percent_boundary_is_measured_against_a_video_of_any_format"
        status: pass
      - kind: unit
        ref: "backend/tests/test_allowlist.py#test_a_sample_named_video_of_another_format_never_sizes_the_main_video"
        status: pass
    human_judgment: false
  - id: D3
    description: "415 from torrents/add reads unavailable with one WARNING carrying only the status; a refused category path (409) fails the job with QbitError and HTTP 409 logged; add 409 is still a duplicate and 500 still fails"
    requirement: "DOWN-06"
    verification:
      - kind: integration
        ref: "backend/tests/test_download_pipeline.py#test_an_invalid_torrent_answered_415_is_unavailable"
        status: pass
      - kind: integration
        ref: "backend/tests/test_download_pipeline.py#test_a_category_path_refused_with_409_fails_the_job_and_logs_the_status"
        status: pass
      - kind: integration
        ref: "backend/tests/test_download_pipeline.py#test_any_other_add_error_still_fails"
        status: pass
    human_judgment: false

duration: 9 min
completed: 2026-10-22
status: complete
---

# Phase 2 Plan 02: WR-01 main-video sizing and DOWN-06 add errors Summary

**`decide()` now measures the 10 % sample ratio against the largest non-sample video of any format, so a 20 GB .m2ts film with a small .mp4 trailer ends as unsupported; a 415 from `torrents/add` reads "Not available".**

## Performance

- **Duration:** 9 min
- **Tasks:** 2 (1 tracer, 1 auto), both TDD
- **Files modified:** 4

## Accomplishments

- WR-01 (D-43): the trailer of an unsupported-format film is no longer started and reported "Started". The torrent is deleted with its files and the row shows the existing unsupported text.
- 20 GB .m2ts plus 4 GB .mkv is accepted (mkv kept, m2ts priority 0); exactly 10 % is kept, one byte less is not.
- DOWN-06: 415 from `torrents/add` ends as unavailable, logged as `add answered HTTP 415` (job id and status only). A category path refused with 409 during the drift repair fails the job and logs `QbitError` plus `HTTP 409` (this already worked through `_settle`; the test is a regression guard).

## Task Commits

1. Task 1 RED: `743437b` test(02-02) failing tests for the m2ts plus trailer case
2. Task 1 GREEN: `a202f48` feat(02-02) size the main video against the largest non-sample video of any format
3. Task 2 RED: `e5049d7` test(02-02) failing test for a 415 reading as unavailable
4. Task 2 GREEN: `dbc0bd6` feat(02-02) answer a 415 from torrents/add as unavailable

## TDD RED evidence

- Task 1 RED run (`pytest backend/tests/test_allowlist.py backend/tests/test_download_pipeline.py`): `3 failed, 82 passed`. Failing: `test_a_big_other_format_film_with_a_small_allowed_trailer_is_rejected_as_video_format`, `test_the_ten_percent_boundary_is_measured_against_a_video_of_any_format`, and the end-to-end `test_a_big_film_in_another_format_with_a_small_allowed_trailer_is_unsupported` (`assert 'started' == 'unsupported'`). The m2ts plus 4 GB mkv and sample-named m2ts cases already passed at HEAD and stay as regression guards.
- Task 2 RED run: `1 failed, 58 passed`. Failing: `test_an_invalid_torrent_answered_415_is_unavailable` (got `failed`). The refused-category 409 test passed already, kept as a regression guard.

## Files Created/Modified

- `backend/app/download/allowlist.py` - `decide()` sizing, updated comments and docstring
- `backend/app/download/pipeline.py` - `HTTP_UNSUPPORTED_MEDIA = 415`, new branch, docstring step 1
- `backend/tests/test_allowlist.py` - four new `decide` cases
- `backend/tests/test_download_pipeline.py` - WR-01 end-to-end, 415, refused category 409, other add error

## Decisions Made

See `key-decisions`. No automatic re-post of a failed Download tap (RESEARCH A5): the Search row's tap-to-retry and list polling (plan 02-06) cover it.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Existing test contradicted the new 415 behavior**
- **Found during:** Task 2
- **Issue:** `test_any_other_refusal_from_add_is_a_failure` asserted that a 415 from add gives `failed`, which D-43/DOWN-06 now defines as `unavailable`.
- **Fix:** Replaced it with `test_any_other_add_error_still_fails` (HTTP 500), as the plan lists; the 415 case moved to its own test.
- **Files modified:** backend/tests/test_download_pipeline.py
- **Commit:** e5049d7

**Total deviations:** 1 auto-fixed (1 test updated to the new contract). **Impact:** none on scope.

## Issues Encountered

None. Backend suite: 468 passed, 4 deselected (integration). `ruff check` and `ruff format --check` clean; `backend/pyproject.toml` and `backend/uv.lock` untouched.

## Known Stubs

None.

## Threat Flags

None. Mitigations T-02-06 (main-video sizing, end-to-end test) and T-02-08 (WARNING lines carry job id and status only, asserted with caplog) are in place.

## Next Phase Readiness

Ready for the remaining wave-1 plans. `decide()` behavior change is internal; the job states and texts the frontend reads are unchanged.

## Self-Check: PASSED

- Files found: allowlist.py, pipeline.py, test_allowlist.py, test_download_pipeline.py
- Commits found: 743437b, a202f48, e5049d7, dbc0bd6
