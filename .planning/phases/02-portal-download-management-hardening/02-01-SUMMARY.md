---
phase: 02-portal-download-management-hardening
plan: 01
subsystem: api
tags: [fastapi, qbittorrent, downloads-list, hmac, pytest]

requires:
  - phase: 01-portal-search-start-download
    provides: protected_router, QbitClient.torrents_info, download pipeline tags, FakeQbit
provides:
  - "GET /api/downloads: Film and SerieTV torrents with plain state, integer progress, ETA, opaque id"
  - "app.download.listing: the one module that knows qBittorrent state names"
  - "content_type.type_for_category (exact category match)"
  - "COMPLETED_VISIBLE_DAYS / FAILED_VISIBLE_HOURS settings"
  - "FakeQbit.add_torrent_row, unreachable and refuse_logins switches"
affects: [02-02, 02-04, 02-06, 02-07, phase-2.1]

actuals:
  tokens: 8800
  tasks: 3
  commits: 4

commits: 4
plan_head_before: f8ea07385dbf7ca7737fe5fa1c73ba685dbb6fe9
plan_head_after: 31fe6b77beceb7e1462edb8819306ae724c90334

tech-stack:
  added: []
  patterns:
    - "Pure listing module (no FastAPI, httpx or qbit client imports) owns every qBittorrent state string"
    - "Opaque ids as HMAC-SHA256(SECRET_KEY, 'download-id:' + hash)[:16], no id storage"
    - "qBittorrent faults map to 502 with a code, never 401"

key-files:
  created:
    - backend/app/download/listing.py
    - backend/app/routers/downloads.py
    - backend/tests/test_download_listing.py
    - backend/tests/test_downloads_api.py
  modified:
    - backend/app/content_type.py
    - backend/app/main.py
    - backend/app/config.py
    - .env.example
    - backend/tests/fakeqbit.py
    - backend/tests/test_no_leaks.py

key-decisions:
  - "The list route is not behind require_ready: it is read-only and keeps working while bootstrap retries"
  - "A torrent is the primary identity of a list row; jobs become a detail for rows with no torrent (plan 02-04)"
  - "moving reads as downloading with no ETA, queuedDL as preparing, any unknown state as stalled; only ...UP states read ready"
  - "A ready row is hidden when now - (completion_on if > 0 else added_on) >= COMPLETED_VISIBLE_DAYS, boundary inclusive"

patterns-established:
  - "Sort key (active group, -timestamp, id) gives a stable order across polls"
  - "Log class name and HTTP status only for qBittorrent failures"

requirements-completed: [DOWN-04, DOWN-06]

coverage:
  - id: D1
    description: "GET /api/downloads lists every Film and SerieTV torrent (including admin-added ones) with the seven-key plain contract and opaque ids"
    requirement: "DOWN-04"
    verification:
      - kind: integration
        ref: "backend/tests/test_downloads_api.py"
        status: pass
      - kind: unit
        ref: "backend/tests/test_download_listing.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "qBittorrent outage or refusal answers 502 qbit_unreachable / qbit_refused and never logs the household out"
    requirement: "DOWN-06"
    verification:
      - kind: integration
        ref: "backend/tests/test_downloads_api.py#test_an_outage_answers_502_and_keeps_the_session"
        status: pass
      - kind: integration
        ref: "backend/tests/test_downloads_api.py#test_a_refused_login_answers_502_never_401"
        status: pass
    human_judgment: false
  - id: D3
    description: "No hash, path, category name or raw qBittorrent state reaches the browser from the list"
    requirement: "DOWN-04"
    verification:
      - kind: integration
        ref: "backend/tests/test_no_leaks.py#test_no_response_carries_a_secret_path_magnet_or_category"
        status: pass
    human_judgment: false

duration: 25 min
completed: 2026-10-22
status: complete
---

# Phase 2 Plan 01: Downloads list endpoint Summary

**`GET /api/downloads` returns Film and SerieTV torrents with plain states, integer progress, rough ETA and HMAC opaque ids, ordered active first, with 502 codes (never 401) for qBittorrent faults.**

## Performance

- **Duration:** about 25 min
- **Tasks:** 3 (tracer, TDD, test expansion)
- **Files:** 10 (4 created, 6 modified)

## Accomplishments

- `app/download/listing.py`: pure state mapper over the 19 qBittorrent 5.2.4 state strings plus `pausedUP`/`pausedDL`; progress floor-clamped to 0..99 (100 only when ready); ETA only for a real downloading estimate (0 < eta < 8640000, not `moving`); bare info-hash names become `null`; D-28 completed window; D-30 order with an id tie-break.
- `app/routers/downloads.py`: one unfiltered `torrents_info()` call, category filter by exact equality in the backend (Film/Extra, film and Other never appear), 502 `qbit_unreachable` / `qbit_refused`.
- Settings `completed_visible_days` (7) and `failed_visible_hours` (24) with seconds properties, documented in `.env.example`.
- `FakeQbit` gained richer rows, `add_torrent_row`, `unreachable` and `refuse_logins`; the leak sweep gained an info-hash marker and the list in the canary flow.

## Task Commits

1. **Task 1 (tracer): GET /api/downloads end to end** - `77ed899` (feat)
2. **Task 2 RED: failing window and settings tests** - `8a9fce0` (test)
3. **Task 2 GREEN: window and settings implemented** - `9e6f635` (feat)
4. **Task 3: admin torrents, outage, refusal, leak sweep** - `31fe6b7` (test)

## TDD Gate Compliance (Task 2)

RED run before the window and settings code (`pytest backend/tests/test_download_listing.py`): 4 failed, 62 passed. The failures were the intended ones: `test_a_ready_torrent_leaves_the_list_exactly_at_the_window` and `test_the_window_counts_from_the_add_time_without_a_completion_time` (a finished row was still listed, list-length assertion), `test_the_window_follows_the_setting` (row not hidden) and `test_downloads_list_windows_have_the_documented_defaults` (`Settings` had no `completed_visible_days`). Semantic assessment: each target test executed and failed on the planned assertion; none was a collection or import fault. The state table, progress, ETA, name, id, category and order tests passed at RED because the tracer already carried the Task 1 mapping, as the plan intended. GREEN `9e6f635` made all 66 pass. No REFACTOR commit was needed. The pytest report format is not one of the supported classifier formats, so `check tdd-red-evidence` was not run; the plan type is `execute`, not `tdd`.

## Verification

- Backend suite: 386 passed at start, 461 passed after (4 deselected integration tests unchanged); infra suite 61 passed.
- `ruff check backend` and `ruff format --check backend` clean.
- `git diff --exit-code -- backend/pyproject.toml backend/uv.lock frontend/package.json frontend/package-lock.json` clean (no package added).
- All acceptance greps of the three tasks print the expected counts.

## Deviations from Plan

None - plan executed exactly as written. (`ruff format` reflowed one signature in `listing.py` after the tracer was written; formatting only.)

## Issues Encountered

None.

## Known Stubs

None. `build_items` takes `now` as the plan specifies; it is used by the completed window.

## Threat Flags

None. The only new surface is `GET /api/downloads`, covered by T-02-01 to T-02-05 of the plan's threat model and by tests (protected route, exact categories, seven-key whitelist, 502 not 401, log without password).

## Next Phase Readiness

Plan 02-02 can rely on the unchanged `FakeQbit` add/files behaviour. Plans 02-04, 02-06 and 02-07 can import `listing.TAG_*`, `tags_of`, `job_tag_of`, `plain_state`, `download_id`, `build_items`. `pipeline.py` still has its private tag helpers; plan 02-04 switches it to `listing`.

## Self-Check: PASSED

- Created files exist: listing.py, routers/downloads.py, test_download_listing.py, test_downloads_api.py.
- Commits `77ed899`, `8a9fce0`, `9e6f635`, `31fe6b7` are ancestors of HEAD.
