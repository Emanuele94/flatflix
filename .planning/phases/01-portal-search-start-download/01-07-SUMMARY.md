---
phase: 01-portal-search-start-download
plan: 07
subsystem: api
tags: [fastapi, qbittorrent, search, pydantic, pytest, respx, validation]

requires:
  - phase: 01-portal-search-start-download
    provides: "01-03 normalize_and_filter and min_size_bytes; 01-05 protected_router; 01-06 require_ready, categories and the pinned search plugins"
provides:
  - "app.content_type: ContentType, CONTENT_TYPES, PLUGIN_CATEGORY, qbit_category(), save_path() as the only type-derived values"
  - "app.search.service: SearchService (start, snapshot, get_result, close), SearchSnapshot, CachedResult, SearchEntry; app.state.search"
  - "POST /api/search {q, type} and GET /api/search/{search_id} behind protected_router and require_ready"
  - "QbitClient search_start, search_status, search_results, search_stop, search_delete; QbitError.status"
  - "Settings and env: MIN_SEEDERS, MIN_FILM_SIZE_MB, MIN_SERIE_SIZE_MB, SEARCH_TIMEOUT, SUSPICIOUS_TERMS, MAX_RESULTS, RESULT_CACHE_TTL, MAX_ACTIVE_SEARCHES, plus Settings.suspicious_term_list"
  - "FakeQbit.script_search and the search endpoints; scripts/smoke.py search --q --type [--expect-results]"
affects: [01-08, 01-09, 01-12, 01-13]

plan_head_before: 724b78d9bf2f12d3fa5df1df812dee0437204748
plan_head_after: 2600698a939d5f8f0f37ca65365f943098d052f8

actuals:
  tokens: 17786
  tasks: 2
  commits: 3

tech-stack:
  added: []
  patterns:
    - "Fixed server-side type maps: the browser sends only film or serie, everything else is derived in app.content_type"
    - "Explicit DTO whitelist for search rows; engine and file_url live only in the server-side CachedResult"
    - "Search lifecycle owned by one service: per-entry lock so a search ends and is deleted once, a start lock for the active-search limit, lazy purge by injected clock"
    - "qBittorrent failures during search surface as 503 search_unavailable, never as a 500 or a leaked body"

key-files:
  created:
    - backend/app/content_type.py
    - backend/app/search/service.py
    - backend/app/routers/search.py
    - backend/tests/test_search_flow.py
    - backend/tests/test_validation.py
  modified:
    - backend/app/qbit/client.py
    - backend/app/config.py
    - backend/app/main.py
    - .env.example
    - backend/tests/fakeqbit.py
    - backend/tests/test_qbit_client.py
    - scripts/smoke.py

key-decisions:
  - "A cut-short search (timeout, eviction, shutdown) is done with timed_out true only when no row passed the filters; a search that stops on its own is never timed_out"
  - "A non-empty SUSPICIOUS_TERMS replaces the built-in list, an empty one keeps it; terms are comma-separated, trimmed and case-folded"
  - "QbitClient.search_stop and search_delete treat HTTP 404 as already gone, so cleanup is idempotent"
  - "A 409 from search/start frees tracked searches and sweeps untracked ones qBittorrent still lists (left by a crashed backend), then retries once"
  - "Search failures from qBittorrent answer 503 search_unavailable; a search qBittorrent forgot (404 on results) ends with the rows already seen"
  - "The raw q field is capped at 1000 characters before the cleaned 2..100 code point count is applied"

requirements-completed: []
# SRCH-01, SRCH-02, SRCH-03, SEC-03 and PUI-02 are declared by this plan but not marked:
# requirements.ready-ids listed all five as blocked (later plans in the phase, such as 01-12, still declare them).

coverage:
  - id: D1
    description: "A Film search sends category movies and plugins enabled, a Serie search category tv; the form has exactly pattern, category and plugins (SRCH-01)"
    requirement: "SRCH-01"
    verification:
      - kind: unit
        ref: "backend/tests/test_search_flow.py::test_film_search_sends_movies_category_and_enabled_plugins, ::test_serie_search_sends_tv_category_and_enabled_plugins"
        status: pass
      - kind: unit
        ref: "backend/tests/test_qbit_client.py::test_search_start_wire_format_is_exactly_pattern_category_plugins"
        status: pass
      - kind: integration
        ref: "python3 scripts/smoke.py --base http://127.0.0.1 search --q Sintel --type film --expect-results (2 results, rows after 717 ms) and --q 'Pioneer One' --type serie (17 results)"
        status: pass
    human_judgment: false
  - id: D2
    description: "Snapshots return partial rows while qBittorrent is Running, re-sorted by seeders and filtered by seeders, size and suspicious names; done on Stopped; timeout stops the search with timed_out only when no row passed (SRCH-02, SRCH-03, D-06..D-08)"
    requirement: "SRCH-03"
    verification:
      - kind: unit
        ref: "backend/tests/test_search_flow.py (partial_results_arrive, snapshots_hide_dead_tiny_and_suspicious_rows, serie_search_uses_the_per_episode_size_floor, timeout_without_rows, timeout_with_rows, rows_that_all_fail_the_filters, suspicious_terms_come_from_the_environment_setting)"
        status: pass
    human_judgment: false
  - id: D3
    description: "Search rows carry exactly result_id, name, size_human, seeders, leechers, source, quality; no URL, category or path reaches the browser (PUI-02, SEC-01)"
    requirement: "PUI-02"
    verification:
      - kind: unit
        ref: "backend/tests/test_search_flow.py::test_result_rows_carry_exactly_the_whitelisted_keys"
        status: pass
      - kind: integration
        ref: "scripts/smoke.py search checks the key set of every row of every snapshot on the real stack"
        status: pass
    human_judgment: false
  - id: D4
    description: "Only the exact strings film and serie are accepted; missing, null, empty, case, whitespace, NUL, fullwidth and extra fields give 422 and no qBittorrent call (SEC-03)"
    requirement: "SEC-03"
    verification:
      - kind: unit
        ref: "backend/tests/test_validation.py (type_other_than_the_exact_string, extra_body_fields, non_json_bodies, every_content_type_round_trips_through_the_fixed_maps)"
        status: pass
    human_judgment: false
  - id: D5
    description: "Query is cleaned (Cc and Cf stripped, trimmed) and counted in code points: 2..100 accepted, 1 and 101 rejected, accented and combining characters counted by code point"
    requirement: "SRCH-03"
    verification:
      - kind: unit
        ref: "backend/tests/test_validation.py (empty_short_or_overlong_query, hundred_accented_code_points, hundred_and_one_code_points, length_counts_code_points, control_and_format_characters_are_stripped)"
        status: pass
    human_judgment: false
  - id: D6
    description: "Cleanup and limits: finished searches deleted once, at most 3 active (oldest evicted), 409 recovery with one retry, results and search ids expire after 900 s, shutdown stops running searches; verified on the real qBittorrent (0 searches left after a smoke run)"
    requirement: "SRCH-03"
    verification:
      - kind: unit
        ref: "backend/tests/test_search_flow.py (finished_search_is_deleted_once, two_polls_at_the_end, fourth_concurrent_search, conflict_from_search_start, conflict_caused_by_searches_left_over, results_expire_with_the_cache_ttl, abandoned_running_search, close_stops_and_deletes, leaving_the_app_cleans_up)"
        status: pass
      - kind: integration
        ref: "after the smoke film search, QbitClient.search_status() inside the backend container returned 0 searches"
        status: pass
    human_judgment: false
  - id: D7
    description: "Searching never adds, starts or fetches a torrent (prohibition): no /api/v2/torrents/ call after bootstrap from a full search, polls, timeout, eviction and close"
    verification:
      - kind: unit
        ref: "backend/tests/test_search_flow.py::test_no_torrent_endpoint_is_ever_called_by_search_polling_timeout_or_cleanup"
        status: pass
    human_judgment: false
  - id: D8
    description: "Search routes need a session (401) and a bootstrapped qBittorrent (503 not_ready)"
    verification:
      - kind: unit
        ref: "backend/tests/test_validation.py::test_search_routes_answer_401_without_a_session, ::test_search_routes_answer_503_not_ready_before_bootstrap; backend/tests/test_routes_protected.py"
        status: pass
    human_judgment: false
  - id: D9
    description: "Whether the real plugin results are good enough for series (research A10): only that the serie smoke search answered; result quality depends on live trackers"
    verification: []
    human_judgment: true
    rationale: "Result relevance on live public trackers cannot be asserted by a test; the search screen (01-12) and the end-to-end plan (01-13) are where a person judges it."

duration: 7min
completed: 2026-10-22
status: complete
---

# Phase 1 Plan 07: Film and Serie search through qBittorrent plugins Summary

**POST /api/search and GET /api/search/{id} turn a film or serie keyword into filtered, seeder-sorted snapshot rows from qBittorrent's plugins, accept only the exact types and a cleaned 2..100 code point query, never hang or leave searches behind, and keep every URL server-side for the later download.**

## Performance

- **Duration:** 7 min
- **Started:** 2026-10-22T10:46:25Z
- **Completed:** 2026-10-22T10:53:36Z
- **Tasks:** 2 (one tracer, one TDD)
- **Files modified:** 12 (5 created, 7 modified)

## Accomplishments

- Tracer proven on the real stack through Caddy: a Film search (Sintel) returned 2 filtered rows with the first ones after about 0.7 to 1.4 s; a Serie search (Pioneer One) returned 17 rows. The smoke probe checks HTTP 200, the exact snapshot and row key sets, non-increasing seeders and that the search ends with `done` true.
- `app.content_type` is the only place where `type` becomes a plugin category, a qBittorrent category and a save path; an invariant test fails if a third type is added without updating every map.
- Strict input: the exact strings `film` and `serie` only (case, whitespace, NUL, fullwidth `ｆｉｌｍ`, `movies`, extra fields and non-JSON bodies all give 422 with zero qBittorrent calls); the query loses Unicode Cc and Cf characters, is trimmed and must be 2..100 code points.
- Lifecycle: timeout stops the search, a finished search is deleted once and its final snapshot served from memory, at most 3 run at once (oldest evicted), a 409 from qBittorrent frees tracked and leftover searches then retries once, entries and cached results expire after 900 s, shutdown stops running searches before the client closes. After the live smoke run qBittorrent held 0 searches.
- `SearchService.get_result(result_id)` returns the engine, URL and type for 01-08; nothing else exposes them.
- Suites: 299 pass (221 before: backend and infra), ruff check and format clean.

## Task Commits

1. **Task 1: Tracer, film keyword search through Caddy** - `722bd5f` (feat)
2. **Task 2: Strict input, timeout, cleanup and limits** (TDD)
   - RED: `8cd7b90` (test)
   - GREEN: `2600698` (feat)

**Plan metadata:** recorded in the docs(01-07) commit that follows this file.

## TDD Gate Compliance

`workflow.tdd_mode` is off, and pytest is not a report format the `check tdd-red-evidence` classifier supports, so RED was judged by hand from the pytest output (same method as 01-03 and 01-06).

- **RED (Task 2):** 34 failed, 59 passed, no collection or import errors. The failures were all on planned behaviour: 12 `200 == 422` (query too short or long, control characters accepted), 3 missing `Settings.suspicious_term_list`, the missing `SearchService.close`, `done` staying false past the timeout, no delete or stop calls on finish, eviction and expiry, 4 unhandled `QbitError` (409 conflict, 500 from qBittorrent) escaping as exceptions, and the wrong pattern reaching `search/start` for a dirty query.
- **Passing before GREEN:** the type tests, extra-field tests, 401/503 tests, the content-type invariant and the six new respx tests. They were already satisfied by the tracer (strict Literal, `extra="forbid"`, the router guards, the client methods) and lock that behaviour, as in 01-06.
- **GREEN:** 93 passed in the four plan files; 299 in the full backend and infra run.
- **REFACTOR:** none.

Tracer gate: Task 1 was `type="tracer"` with an automated-only `<verify>`; its end-to-end verify (pytest, rebuild, smoke on the live stack) passed before Task 2 started, so expansion continued without a checkpoint. After GREEN the stack was rebuilt and the film smoke search re-run.

## Files Created/Modified

- `backend/app/content_type.py` - ContentType, CONTENT_TYPES and the fixed type maps
- `backend/app/search/service.py` - SearchService with timeout, cleanup, limits, result cache
- `backend/app/routers/search.py` - SearchRequest validation, DTO whitelist, the two routes
- `backend/app/qbit/client.py` - search_* methods, QbitError.status
- `backend/app/config.py`, `.env.example` - eight search settings and `suspicious_term_list`
- `backend/app/main.py` - app.state.search, router, close before the client closes
- `backend/tests/fakeqbit.py` - script_search and the search endpoints (409 beyond 5 searches)
- `backend/tests/test_search_flow.py`, `test_validation.py`, `test_qbit_client.py` - 78 new tests (299 total, up from 221)
- `scripts/smoke.py` - `search` subcommand

## Decisions Made

See key-decisions in the frontmatter. The two with the most reach for later plans: a non-empty `SUSPICIOUS_TERMS` replaces (not extends) the built-in list, and `get_result` is the single door from a `result_id` to a URL.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] QbitError did not carry a status**
- **Found during:** Task 1
- **Issue:** the plan's interfaces say `QbitError` carries `.status`, but it only held a message, so the 409 recovery could not tell a conflict from another failure.
- **Fix:** `QbitError(*args, status=None)`; `_checked` and `create_category` pass the HTTP status. The message still never carries a response body.
- **Files modified:** backend/app/qbit/client.py
- **Commit:** 722bd5f

**2. [Rule 2 - Missing critical] Searches left by a crashed backend would block search for good**
- **Found during:** Task 2
- **Issue:** qBittorrent keeps at most five searches; ones a dead backend never deleted are untracked, so freeing only tracked searches on a 409 could leave every new search failing until a manual cleanup.
- **Fix:** after freeing tracked searches, the 409 path lists `search/status` and stops and deletes whatever is left, then retries once.
- **Files modified:** backend/app/search/service.py
- **Verification:** test_conflict_caused_by_searches_left_over_from_a_crash_is_swept_then_retried
- **Commit:** 2600698

**3. [Rule 2 - Missing critical] qBittorrent failures during search surfaced as unhandled errors**
- **Found during:** Task 2 (RED)
- **Issue:** a 409 that survives the retry or a 5xx from qBittorrent raised through the route as a 500.
- **Fix:** both routes answer 503 `search_unavailable` and log the class name and HTTP status only; a search qBittorrent no longer knows (404 on results) ends with the rows already seen; stop and delete treat 404 as already gone.
- **Files modified:** backend/app/routers/search.py, backend/app/search/service.py, backend/app/qbit/client.py
- **Verification:** test_a_conflict_that_survives_the_retry..., test_qbittorrent_failing_during_a_poll..., test_a_search_qbittorrent_no_longer_knows...
- **Commit:** 2600698

**4. [Rule 2 - Missing critical] Races on the search lifecycle and an unbounded raw query**
- **Found during:** Task 2
- **Issue:** two simultaneous polls at the end of a search could both delete it, two simultaneous starts could both pass the active-search limit, and `q` was only bounded after cleaning.
- **Fix:** a lock per search entry and one start lock; the raw `q` is capped at 1000 characters before the cleaned 2..100 code point rule applies.
- **Files modified:** backend/app/search/service.py, backend/app/routers/search.py
- **Verification:** test_two_polls_at_the_end_of_a_search_delete_it_only_once, test_empty_short_or_overlong_query... (the 1001 character case)
- **Commit:** 2600698

### Notes

- **Live keywords:** the plan's verify command uses `--q 1080p` and `--q "S01E01"`. Per the execution instructions to keep live queries to a minimum with benign keywords, the real-stack runs used `Sintel` (film, `--expect-results`) and `Pioneer One` (serie), three live searches in total. No download was started and no result name was printed.
- **config imports filters:** `Settings.suspicious_term_list` imports `DEFAULT_SUSPICIOUS_TERMS` from `app.search.filters`. The filters module stays free of config and framework imports; only the direction config to filters was added.

**Total deviations:** 4 auto-fixed (1 Rule 3, 3 Rule 2), 2 notes. **Impact:** all inside the plan's files and goals; no scope creep.

## Authentication Gates

None. The smoke probe logged in with the dev account (one successful login per run, which resets the throttle).

## Issues Encountered

None open. Two things not covered by an automated check: relevance of live results (D9 in the coverage block), and the `timed_out` message wording, which belongs to the search screen in 01-12.

## Known Stubs

None. `grep -rn "TODO\|FIXME" backend/app scripts/smoke.py` prints nothing.

## Threat Flags

None. The two new routes sit behind `protected_router()` and `require_ready` (checked by the route-enumeration test), and the threat register items T-01-25, T-01-26, T-01-27 and T-01-29 are covered by the tests listed in the coverage block. Query injection into plugin subprocesses (A11) remains with /gsd-secure-phase.

## User Setup Required

None - no external service configuration required. `.env.example` gained eight search keys with working defaults; an existing local env file needs no change.

## Next Phase Readiness

- 01-08 can call `request.app.state.search.get_result(result_id)` for `engine`, `file_url` and `type`, and take category and save path from `qbit_category(settings, type)` and `save_path(settings, type)`. An expired id returns None (the plan's 410 case).
- 01-12 can build the search screen on `POST /api/search` -> `{search_id}` and `GET /api/search/{id}` -> `{search_id, done, timed_out, results[]}`; errors are 401, 404 `search_not_found`, 422 and 503 `not_ready` or `search_unavailable`.
- 01-09 should list the eight new keys in the docs; `.env.example` already has them with comments.

## Self-Check: PASSED

- Files: backend/app/content_type.py, backend/app/search/service.py, backend/app/routers/search.py, backend/tests/test_search_flow.py, backend/tests/test_validation.py found.
- Commits 722bd5f, 8cd7b90, 2600698 are ancestors of HEAD (3 measured from the ledger base 724b78d).
- Acceptance criteria re-run: content_type.py has `"film": "movies"` and `"serie": "tv"`; the router uses `protected_router(` and `require_ready`; `grep -nE 'file_url|fileUrl|descrLink'` on the router prints nothing; the smoke film search printed a positive count and a first-rows time; the router has `unicodedata` and `extra="forbid"`; the service has `search_stop`, `search_delete` and `max_active_searches`; a test named `..._no_torrent_endpoint_...` asserts no `/api/v2/torrents/` call; test_validation.py contains `ｆｉｌｍ`.
- Plan verification: backend and infra suites 299 passed; film smoke search OK on the rebuilt stack.
