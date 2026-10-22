---
phase: 02-portal-download-management-hardening
plan: 07
subsystem: api
tags: [fastapi, qbittorrent, cancel, delete, asyncio, tdd]
status: complete

requires:
  - phase: 02-portal-download-management-hardening
    provides: "GET /api/downloads with opaque HMAC ids and job rows (02-01, 02-04); rate limiting and 502 codes (02-05)"
provides:
  - "DELETE /api/downloads/{id}: 204 / 404 download_not_found / 422 / 502 qbit_unreachable|qbit_refused"
  - "DownloadPipeline.cancel(download_id) -> CancelOutcome(action, name, deleted_files) | None, serialised by one lock"
  - "JobState.CANCELLED, JobRegistry.cancel_for(torrent_hash=, job_id=), JobRegistry.spawn_background(coro, name)"
  - "listing.IN_PROGRESS_RAW_STATES, cancel_deletes_files(row), find_torrent(rows, id, settings, secret); every torrent row's action derives from cancel_deletes_files"
affects: [02-09, 02-10, 02-11]

actuals:
  tokens: 9300
  tasks: 3
  commits: 5

commits: 5
plan_head_before: 103d44e2e411c8f17afde99cbbcf326df9e14616
plan_head_after: b9840cadf413809581a3ccefff8c35d98f4b5ca2

tech-stack:
  added: []
  patterns:
    - "Destructive call decided from the live row inside the request: the browser sends only an opaque id, the server re-reads the torrent, re-checks the category and picks deleteFiles"
    - "Stop and await the job task, mark it cancelled, only then send torrents/delete (no ghost failure row, no blocked re-tap)"
    - "Bounded background sweep for a torrent that appears after its job was cancelled; tasks held by the registry and cancelled at shutdown"

key-files:
  created:
    - backend/tests/test_download_cancel.py
  modified:
    - backend/app/download/jobs.py
    - backend/app/download/pipeline.py
    - backend/app/download/listing.py
    - backend/app/routers/downloads.py
    - backend/tests/test_downloads_api.py
    - backend/tests/test_download_listing.py
    - backend/tests/test_no_leaks.py

key-decisions:
  - "deleteFiles is true only for a known in-progress raw state with progress below 1; everything else (ready, moving, error or missingFiles at 1.0, unknown states, non-numeric progress) keeps the files"
  - "The list action is cancel_deletes_files(row), so the button and confirm copy always name what DELETE then does"
  - "The late-torrent sweep and the job-tag lookup also use cancel_deletes_files(row) per row instead of a blanket deleteFiles=true, so no portal path can delete a completed download's files"
  - "A discard that fails after the job was cancelled starts a bounded retry sweep (now + METADATA_TIMEOUT) because torrents of cancelled jobs are hidden from the list"

requirements-completed: [DOWN-05, DOWN-06]

coverage:
  - id: D1
    description: "DELETE /api/downloads/{id} deletes an in-progress torrent with its files (204) and the next list no longer shows it; a ready torrent is removed with files kept; admin-added torrents follow the same rules"
    requirement: "DOWN-05"
    verification:
      - kind: unit
        ref: "backend/tests/test_download_cancel.py#test_cancelling_an_in_progress_download_deletes_the_torrent_and_its_files"
        status: pass
      - kind: unit
        ref: "backend/tests/test_downloads_api.py#test_the_list_action_and_the_delete_agree_on_what_happens_to_the_files"
        status: pass
    human_judgment: false
  - id: D2
    description: "The list offers Cancel exactly where the server deletes files (cancel_deletes_files), Remove everywhere else, for all raw states at 0.4 and 1.0"
    requirement: "DOWN-05"
    verification:
      - kind: unit
        ref: "backend/tests/test_download_listing.py#test_action_is_cancel_exactly_when_cancel_deletes_files"
        status: pass
      - kind: unit
        ref: "backend/tests/test_download_listing.py#test_cancel_deletes_files_only_for_a_known_in_progress_state_below_one"
        status: pass
    human_judgment: false
  - id: D3
    description: "Only Film and SerieTV ids resolve: Other, Film/Extra, unknown ids answer 404 and delete nothing; malformed ids answer 422; a second or simultaneous DELETE sends one torrents/delete; 30 DELETEs never answer 429"
    requirement: "DOWN-05"
    verification:
      - kind: unit
        ref: "backend/tests/test_downloads_api.py#test_a_torrent_outside_film_and_serie_cannot_be_cancelled"
        status: pass
      - kind: unit
        ref: "backend/tests/test_downloads_api.py#test_two_simultaneous_deletes_send_one_torrents_delete"
        status: pass
    human_judgment: false
  - id: D4
    description: "qBittorrent outage or refused credentials answer 502 qbit_unreachable / qbit_refused on DELETE; no portal route answers 401 for a qBittorrent refusal and /api/session stays 200"
    requirement: "DOWN-06"
    verification:
      - kind: unit
        ref: "backend/tests/test_downloads_api.py#test_no_portal_route_answers_401_when_qbit_refuses_the_backend"
        status: pass
    human_judgment: false
  - id: D5
    description: "Cancelling a Preparing download: job task ended and cancelled before torrents/delete, no ghost row after METADATA_TIMEOUT, GET /api/download/{id} says cancelled, the same result can be tapped again at once"
    requirement: "DOWN-05"
    verification:
      - kind: unit
        ref: "backend/tests/test_download_cancel.py#test_cancelling_a_preparing_download_leaves_no_ghost_row"
        status: pass
      - kind: unit
        ref: "backend/tests/test_download_cancel.py#test_a_cancelled_result_can_be_downloaded_again_at_once"
        status: pass
    human_judgment: false
  - id: D6
    description: "A torrent-less Preparing job is cancelled by job id; a torrent that appears later under its tag is never listed and is deleted by a bounded sweep that ends after created_at + METADATA_TIMEOUT and at shutdown"
    requirement: "DOWN-05"
    verification:
      - kind: unit
        ref: "backend/tests/test_download_cancel.py#test_a_torrent_less_preparing_job_is_cancelled_and_a_late_torrent_is_swept"
        status: pass
      - kind: unit
        ref: "backend/tests/test_download_cancel.py#test_shutdown_stops_a_running_sweep_without_errors"
        status: pass
    human_judgment: false
---

# Phase 2 Plan 07: Cancel and remove downloads Summary

**DELETE /api/downloads/{id} cancels an in-progress download with its partial files and removes a finished one while keeping the film, decided on the server from the live row, with the job behind a Preparing download stopped first so no ghost row or stray torrent is left.**

## Performance

- **Duration:** about 7.5 min of wall clock (first commit to last)
- **Tasks:** 3 (1 tracer, 2 TDD)
- **Files:** 1 created, 7 modified

## Accomplishments

- The browser sends only an opaque id. `DownloadPipeline.cancel` lists torrents, matches the id with `find_torrent` (category exactly Film or SerieTV), stops and awaits the job, marks it `cancelled`, then sends `torrents/delete` with `deleteFiles` taken from `cancel_deletes_files(row)`. One `asyncio.Lock` serialises cancels, so two taps send one delete and the second answers 404.
- `cancel_deletes_files` is true only for known in-progress raw states below progress 1.0. The list derives each torrent row's `action` from the same function, so "Cancel download" (with the delete confirm text) appears only where the files really go.
- A Preparing job with no torrent yet is cancelled by its job id. Any torrent already under its tag is deleted, and a bounded `_sweep_cancelled` task removes one that shows up later. Torrents of cancelled jobs are never listed.
- qBittorrent outage and refused credentials answer 502 `qbit_unreachable` / `qbit_refused` on DELETE; no portal route answers 401 for them and the session survives. DELETE is not throttled.

## Task Commits

1. **Task 1 (tracer): cancel through DELETE /api/downloads/{id}** - `5e02520` (feat)
2. **Task 2 RED: list action, id scoping, serialisation, 502 tests** - `9fe6c9f` (test)
3. **Task 2 GREEN: action derived from cancel_deletes_files** - `eb956a0` (feat)
4. **Task 3 RED: Preparing-cancel tests** - `056d917` (test)
5. **Task 3 GREEN: job-id cancel, sweep, hidden cancelled torrents, spawn_background** - `b9840ca` (feat)

## TDD Notes

- **Task 2 RED:** 26 of 194 tests failed, all on the planned assertion `action == "cancel" if cancel_deletes_files(row) else "remove"` (list-action cases for missingFiles, error and moving at 1.0, an unknown state, and every in-progress state at 1.0). The cancel, 404, 422, concurrency and 502 cases already passed because the tracer had delivered them; the list-action cases were the target. No load, syntax or fixture errors. Valid RED.
- **Task 3 RED:** 4 of 8 tests failed on planned assertions (DELETE of a torrent-less job answered 404 instead of 204, a cancelled job's torrent was listed as `preparing`, no `cancel-sweep-` task existed). The ghost-row, re-tap and ended-job-404 cases already passed because the tracer's `cancel_for(torrent_hash=...)` covers the torrent-found path; they stay as regression guards. Valid RED.
- The plan is `type: execute`, so `gsd_run check tdd-red-evidence` was not run; RED evidence was inspected by hand as above. No REFACTOR commit was needed.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality] Sweep and job-tag lookup decide deleteFiles per row**
- **Found during:** Task 3
- **Issue:** The plan says the sweep deletes "with files" any torrent found under the job tag. A torrent in that set that is already complete would lose its film, which breaks the prohibition on deleting a completed download's files through any portal request.
- **Fix:** `_sweep_once` passes `cancel_deletes_files(row)` per row. A late torrent that was just added (stopped, progress 0) still goes with its files.
- **Files modified:** backend/app/download/pipeline.py
- **Commit:** b9840ca

**2. [Rule 1 - Bug] A failed delete after the job was cancelled would orphan a hidden torrent**
- **Found during:** Task 3
- **Issue:** The plan's flagged assumption says the torrent "is listed again" after a 502, but the same plan hides torrents of cancelled jobs, so the household could not retry and the torrent would stay in qBittorrent.
- **Fix:** When `torrents/delete` fails after `cancel_for` returned a job and the row carries a job tag, `cancel` starts the bounded retry sweep (now + METADATA_TIMEOUT) before re-raising the 502. A torrent with no job tag (admin-added, or tags already cleared) stays listed, so the household can retry.
- **Files modified:** backend/app/download/pipeline.py
- **Commit:** b9840ca

**3. [Rule 1 - Bug] "Coroutine was never awaited" warning when shutdown cancels a sweep before its first step**
- **Found during:** Task 3 full-suite run
- **Fix:** `spawn_background` closes the wrapped coroutine in a done callback (no-op once it has run).
- **Files modified:** backend/app/download/jobs.py
- **Commit:** b9840ca

No earlier assertion in test_download_listing.py needed updating: the existing "problem item can be cancelled" case uses progress 0.5, which the new rule also reads as cancel.

## Issues Encountered

None beyond the deviations above.

## Known Stubs

None.

## Threat Flags

None. DELETE is the one new endpoint and is in the plan's threat model (T-02-23 to T-02-28). The `hashes` value sent to qBittorrent only ever comes from a row just read; "all" cannot arrive from the browser (the path pattern is 16 lowercase hex characters).

## Verification

- `uv run --project backend --frozen pytest backend/tests -q`: 613 passed, 4 deselected (integration).
- `uv run --project backend --frozen ruff check backend`: All checks passed.
- `git diff --exit-code -- backend/pyproject.toml backend/uv.lock`: clean.
- Acceptance greps: `@router.delete("/downloads/{download_id}"` 1, `CANCELLED = "cancelled"` 1, `async def cancel_for` 1, `def cancel_deletes_files` 1, `if cancel_deletes_files(row) else "remove"` 1, `"downloads cancel"` in test_no_leaks.py 1, `_sweep_cancelled` 2, `def spawn_background` 1, `asyncio.gather` in test_downloads_api.py 1.
- No docker command was run (per the plan); the live probe belongs to plan 02-11.

## Self-Check: PASSED

- Files exist: backend/tests/test_download_cancel.py and the seven modified files.
- Commits exist: 5e02520, 9fe6c9f, eb956a0, 056d917, b9840ca.
