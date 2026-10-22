---
phase: 02-portal-download-management-hardening
plan: 04
subsystem: api
tags: [fastapi, download-jobs, downloads-list, tdd, python]

requires:
  - phase: 02-portal-download-management-hardening
    provides: "listing.build_items, tag helpers and failed_visible_seconds (plan 02-01)"
provides:
  - "Job.name and Job.finished_at; JobRegistry(clock=...), JobRegistry.all(), FAILED_STATES; finished_at stamped once in _guard's finally"
  - "GET /api/downloads lists failed attempts (rejected, unsupported, unavailable, failed) for FAILED_VISIBLE_HOURS and torrent-less Preparing jobs with action cancel"
  - "Torrents named by a bare info-hash take the name of the job that owns them (by hash or fx-job tag)"
  - "JobRegistry._prune drops the oldest finished job first, never a running one"
  - "pipeline.py shares the tag rules with listing.py (one definition)"
affects: [02-05, 02-06, 02-09, phase-3]

actuals:
  tokens: 4600
  tasks: 2
  commits: 3

commits: 3
plan_head_before: d6bd1b9b1168ed15e74724f154617e0fc65dc601
plan_head_after: 2125ad1808e95f0116b56dadc6e1df503b399090

tech-stack:
  added: []
  patterns:
    - "A job adds a row to the downloads list only when no torrent represents it; the torrent is the primary identity"
    - "JobRegistry takes an injectable clock (epoch seconds) like DownloadPipeline"

key-files:
  created: []
  modified:
    - backend/app/download/jobs.py
    - backend/app/download/listing.py
    - backend/app/download/pipeline.py
    - backend/app/routers/downloads.py
    - backend/tests/test_downloads_api.py
    - backend/tests/test_download_listing.py

key-decisions:
  - "finished_at is stamped in a finally around the whole job task, so a job that sat Preparing for minutes ages from its end, not its start (Pitfall 3)"
  - "A job name that is itself a bare info-hash (a reconciled job) is never used as a display name"
  - "A failed job whose torrent is still listed gets its own failed row next to the torrent row: the torrent appears once, the failed attempt is a separate listed job row"

requirements-completed: [DOWN-04]

coverage:
  - id: D1
    description: "A rejected Download tap shows in GET /api/downloads with its plain state, the result's name and no action, and leaves exactly at FAILED_VISIBLE_HOURS"
    requirement: "DOWN-04"
    verification:
      - kind: integration
        ref: "backend/tests/test_downloads_api.py#test_a_rejected_download_tap_is_listed_with_its_reason_and_name"
        status: pass
      - kind: integration
        ref: "backend/tests/test_downloads_api.py#test_a_failed_row_disappears_after_failed_visible_hours"
        status: pass
      - kind: unit
        ref: "backend/tests/test_download_listing.py#test_a_failure_row_leaves_exactly_at_the_window"
        status: pass
    human_judgment: false
  - id: D2
    description: "Every Film/SerieTV torrent appears exactly once; torrent-less Preparing jobs are listed with cancel; hash-named magnets take the job name; job rows join the D-30 order"
    requirement: "DOWN-04"
    verification:
      - kind: unit
        ref: "backend/tests/test_download_listing.py#test_every_film_or_serie_torrent_appears_exactly_once"
        status: pass
      - kind: unit
        ref: "backend/tests/test_download_listing.py#test_job_rows_join_the_order_by_group_then_newest_first"
        status: pass
    human_judgment: false
  - id: D3
    description: "Registry stamps finished_at once for every ending and prunes the oldest finished job first, never a running one"
    requirement: "DOWN-04"
    verification:
      - kind: unit
        ref: "backend/tests/test_download_listing.py#test_the_registry_stamps_finished_at_once_for_every_ending"
        status: pass
      - kind: unit
        ref: "backend/tests/test_download_listing.py#test_pruning_drops_the_oldest_finished_job_and_never_a_running_one"
        status: pass
    human_judgment: false

duration: 12 min
completed: 2026-10-22
status: complete
---

# Phase 2 Plan 04: Job rows in the downloads list Summary

**Failed Download taps (rejected, unsupported, unavailable, failed) now stay in GET /api/downloads for 24 h with their plain reason and the search result's name, Preparing taps whose torrent is not in qBittorrent yet are listed with Cancel, and every torrent still appears exactly once.**

## Performance

- **Duration:** 12 min
- **Tasks:** 2 (1 tracer, 1 TDD auto)
- **Files modified:** 6

## Accomplishments

- D-29: `Job` carries `name` and `finished_at`; `JobRegistry._guard` stamps `finished_at` in a `finally`, so normal end, crash and cancellation are all stamped once. A failure row is listed while `now - finished_at < failed_visible_seconds` and hidden from exactly that age on.
- Torrent-less Preparing jobs (plugin page adds, Pitfall 5) are listed as `preparing` with action `cancel` and `id = job_id`; once the torrent appears (by hash or by the `fx-job-<id>` tag) only the torrent row remains.
- D-27 / Pitfall 11: a torrent named by its bare info-hash takes the name of the job that owns it; with no job the name stays `null`.
- D-30: preparing job rows sort in the active group (by `created_at`), failure rows in the second group (by `finished_at`), ties by id ascending.
- `pipeline.py` imports `TAG_PORTAL`, `TAG_PENDING`, `TAG_JOB_PREFIX`, `tags_of`, `job_tag_of` from `listing.py`; the private copies are gone. `submit` stores `cached.name`, `reconcile` the row name.
- `_prune` drops the oldest finished job first (an unstamped done job first), never a running one.
- Backend suite: 493 passed, 4 deselected (integration). `ruff check` and `ruff format --check` clean. `pyproject.toml` and `uv.lock` untouched.

## Task Commits

1. Task 1 (tracer): `aa9d5f7` feat(02-04) list failed download attempts in GET /api/downloads
2. Task 2 RED: `bdd4a9a` test(02-04) job rows never duplicate a torrent; names, order, pruning
3. Task 2 GREEN: `2125ad1` feat(02-04) job rows never duplicate a torrent, name hash-named magnets, prune oldest finished

Tracer gate: `<verify>` (pipeline and downloads API tests plus ruff) passed end to end before Task 2 started.

### RED run (Task 2)

Seven tests failed before the implementation, 82 passed: `test_a_preparing_job_without_a_torrent_is_listed_with_cancel`, `test_a_preparing_job_whose_hash_is_not_listed_still_shows`, `test_a_bare_hash_torrent_takes_the_name_of_the_job_with_its_hash`, `test_a_bare_hash_torrent_takes_the_name_of_the_job_its_tag_names`, `test_every_film_or_serie_torrent_appears_exactly_once`, `test_job_rows_join_the_order_by_group_then_newest_first`, `test_pruning_drops_the_oldest_finished_job_and_never_a_running_one`. After GREEN: 100 passed in the two listing and API files.

## Files Created/Modified

- `backend/app/download/jobs.py` - `Job.name`, `Job.finished_at`, `FAILED_STATES`, `JobRegistry(clock)`, `all()`, stamping `_guard`, `_prune` by oldest finished
- `backend/app/download/listing.py` - `FAILED_JOB_STATES`, `job_name`, `build_items(..., jobs=())` with job rows, dedupe and job names
- `backend/app/download/pipeline.py` - tag helpers imported from listing, job name capture
- `backend/app/routers/downloads.py` - passes `jobs=app.state.jobs.all()`
- `backend/tests/test_downloads_api.py` - two tracer tests through the pipeline rig (imported from `test_download_pipeline.py`)
- `backend/tests/test_download_listing.py` - job-row matrix, invariant, ordering, registry stamp and prune tests

## Decisions Made

See `key-decisions`. The existing `Rig` and `clock` fixtures are imported from `tests/test_download_pipeline.py` rather than duplicated.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. Docker and the running stack were not touched, as the plan requires.

## Known Stubs

None.

## Threat Flags

None. Job rows use the same seven-key item as torrent rows (T-02-12); `MAX_JOBS` is kept and pruning is oldest-finished-first with a unit test (T-02-13); `git diff --exit-code -- backend/pyproject.toml backend/uv.lock` is clean (T-02-SC).

## Next Phase Readiness

Ready for the remaining wave 2 and later plans. Job rows have `action: null` for failures and `cancel` for torrent-less Preparing jobs; the cancel route in a later plan must accept a job id for that second case.

## Self-Check: PASSED

All six files exist; commits `aa9d5f7`, `bdd4a9a`, `2125ad1` are ancestors of HEAD; the acceptance greps return the expected counts; the full backend suite and ruff pass.
