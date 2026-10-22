---
phase: 01-portal-search-start-download
plan: 03
subsystem: backend-rules
tags: [python, pytest, tdd, allowlist, search-filters, btih, dedupe]

requires:
  - phase: 01-portal-search-start-download
    provides: "Plan 01-01 approved backend/uv.lock and pinned pyproject (pytest, ruff)"
provides:
  - "backend/app/download/allowlist.py: pure per-file allowlist decide() plus the FILT-01 EXCLUDED_FILE_PATTERNS tuple"
  - "backend/app/search/filters.py: pure normalize_and_filter() with dedupe by btih, stable result_id, deterministic sort, quality badge, human size"
  - "58 passing tests (17 allowlist, 41 filters) using verbatim qBittorrent 5.2.4 rows"
affects: [01-06, 01-07, 01-08, 01-10]

plan_head_before: 41b87863818545ada7e3618427db086a8467850c
plan_head_after: f086eec26d17208bb8de15dff3cd2948ebe8e6cb

actuals:
  tokens: 6168
  tasks: 3
  commits: 6

tech-stack:
  added: []
  patterns:
    - "Pure rule modules: no I/O, no fastapi/httpx/app.config imports; thresholds and term lists arrive as arguments"
    - "Integer math for the sample boundary (size * 10 >= largest), so exactly 10 percent is kept"
    - "RED skeleton: wrong-valued placeholders so RED tests fail on assertions, never on import"

key-files:
  created:
    - backend/app/download/__init__.py
    - backend/app/download/allowlist.py
    - backend/tests/test_allowlist.py
    - backend/app/search/__init__.py
    - backend/app/search/filters.py
    - backend/tests/test_filters.py
  modified: []

key-decisions:
  - "Allowlist keys on the final lower-cased extension only; movie.mkv.exe is zeroed, movie.exe.mkv is kept"
  - "A torrent with no non-sample allowed video is rejected with reason no_video and every index zeroed"
  - "result_id is sha1(dedupe_key)[:16] where a magnet key is the btih alone, so it survives a change of winning engine"
  - "human_size rolls over to the next unit when rounding reaches 1024.0, so it never prints 1024.0 KB"

patterns-established:
  - "Pure functions first: wire-up (01-07 search service, 01-08 download pipeline) only adapts I/O to these rules"

requirements-completed: [FILT-02, FILT-01, SRCH-02]

coverage:
  - id: D1
    description: "decide() keeps non-sample allowed videos and subtitles, zeroes everything else, rejects torrents without a main video with reason no_video (FILT-02, D-13, D-14)"
    requirement: "FILT-02"
    verification:
      - kind: test
        ref: "backend/tests/test_allowlist.py (17 tests)"
        status: pass
    human_judgment: false
  - id: D2
    description: "EXCLUDED_FILE_PATTERNS starts with the 11 FILT-01 patterns in order, all lower-case, no domain-like suffixes"
    requirement: "FILT-01"
    verification:
      - kind: test
        ref: "backend/tests/test_allowlist.py::test_excluded_file_patterns_start_with_the_filt01_list_in_order, ::test_excluded_file_patterns_are_lower_case_and_unique"
        status: pass
    human_judgment: false
  - id: D3
    description: "normalize_and_filter() hides dead, tiny, unknown (-1) and suspicious results, dedupes by btih or (engine, fileUrl), sorts deterministically, adds badge and size_human (SRCH-02, D-07, D-08, D-09)"
    requirement: "SRCH-02"
    verification:
      - kind: test
        ref: "backend/tests/test_filters.py (41 tests)"
        status: pass
    human_judgment: false

duration: 12min
completed: 2026-10-22
status: complete
---

# Phase 1 Plan 03: Allowlist and search filters Summary

**Two pure, exhaustively tested rule sets: a final-extension file allowlist with sample and no-video rejection (FILT-01/02), and search-result normalization with btih dedupe, stable ids, deterministic sort, badge and human size (SRCH-02)**

## Performance

- **Duration:** about 12 min (start time not captured by the executor; estimated from commit times)
- **Completed:** 2026-10-22T10:06:30Z
- **Tasks:** 3 of 3
- **Files modified:** 6 (all created)

## Accomplishments
- `decide()` turns a real qBittorrent file list into `keep_ids`/`zero_ids`, or rejects it with `no_video` before any data would download.
- `EXCLUDED_FILE_PATTERNS` is ready for 01-06 to send to qBittorrent (11 FILT-01 patterns first, then `*.pif *.vbs *.jar *.dll *.apk *.dmg *.cab`).
- `normalize_and_filter()` is ready for 01-07: drops seeders below 5, size below the configured floor, unknown `-1` values and suspicious names; merges duplicates keeping the highest seeders; returns server-only `engine` and `file_url` alongside the public fields.
- Both modules import nothing from fastapi, httpx or app.config (grep confirmed empty).

## TDD Gate Compliance

The plan is `type: execute` with `tdd="true"` tasks, so the RED then GREEN order was followed per task. `workflow.tdd_mode` is not enabled in config.json.

| Task | RED commit | GREEN commit |
|------|------------|--------------|
| 1 Tracer | `453cdeb` test(01-03) | `37271aa` feat(01-03) |
| 2 Allowlist edges | `47f57a8` test(01-03) | `8a11444` feat(01-03) |
| 3 Search filters | `7971f07` test(01-03) | `f086eec` feat(01-03) |

No REFACTOR commit: formatting and the `human_size` simplification happened before the Task 3 GREEN commit, with tests green.

### RED evidence and semantic assessment

pytest is not a report format the `gsd_run check tdd-red-evidence` classifier supports (TAP, JUnit from Maven, go test, swift-testing, unittest), so the classifier was not run. RED was assessed by hand from the real pytest output. For each RED run, every failing target test failed on an `AssertionError` (or `DID NOT RAISE` for the `ValueError` test) on the planned behaviour, with zero collection errors.

- **Task 1:** 2 failed, 0 passed. `test_real_torrent_file_list_is_split_into_keep_and_zero_indexes` failed because the skeleton `decide()` returned `accept=False, reason="not_implemented"`; `test_from_qbit_maps_index_name_size_priority` failed with `index: -1 != 5`.
- **Task 2:** 10 failed, 7 passed. The failures are the sample, boundary, season, no-video and pattern tests. The 7 that passed (double extension, case, no extension, non-ASCII, single video, tracer behaviours) were already satisfied by the Task 1 implementation, which is expected because Task 1 built the extension logic they test.
- **Task 3:** 32 failed, 9 passed. The 9 that passed assert things a wrong-valued skeleton satisfies by accident (for example an empty input giving `[]`, or `quality is None` for a nameless row). Each failing assertion named the planned expected value (for example `'' == '4.2 GB'`, `['four', 'five'] == ['five']`).
- A first Task 2 RED attempt ended in `ImportError` at collection (INVALID_RED style). It was not committed; placeholder constants were added so the tests fail on assertions, then committed.

The RED commits of Tasks 1 to 3 also contain the skeleton module (the tests need importable names); the skeleton returns wrong values on purpose.

### Tracer gate

Task 1 was `type="tracer"` with an automated-only `<verify>`; it was re-run after GREEN (`2 passed`) before expanding: tracer verified end-to-end, expansion continued.

## Task Commits

1. **Task 1: Tracer, real file list through decide()** - `453cdeb` (test), `37271aa` (feat)
2. **Task 2: Allowlist edge cases** - `47f57a8` (test), `8a11444` (feat)
3. **Task 3: Search-result filters** - `7971f07` (test), `f086eec` (feat)

**Plan metadata:** recorded in the docs(01-03) commit that follows this file.

## Files Created/Modified
- `backend/app/download/allowlist.py` - decide(), final_extension(), is_sample_name(), constants
- `backend/tests/test_allowlist.py` - 17 tests incl. verbatim Sintel rows
- `backend/app/search/filters.py` - RawResult/FilterConfig/FilteredResult and the filter functions
- `backend/tests/test_filters.py` - 41 tests incl. verbatim limetorrents row
- `backend/app/download/__init__.py`, `backend/app/search/__init__.py` - docstring-only package markers

## Decisions Made
- See key-decisions in the frontmatter. `SAMPLE_SIZE_RATIO = 0.10` is exported as the documented threshold, but `decide()` applies it with integer math (`size * 10 >= largest`) to avoid float error at the exact boundary; changing the constant alone will not change behaviour.

## Deviations from Plan

None - plan executed exactly as written. Two additions inside the plan's scope: the `human_size` unit rollover guard and the extra test cases (ties on equal seeders, 1023 B and 1024 B boundaries, infohash rejection of malformed values).

## Issues Encountered
- `uv sync --frozen` was run once to build `backend/.venv` from the approved lockfile (the venv is git-ignored). No package was added or changed; `uv.lock` is untouched.
- The executor did not capture a start timestamp, so the duration is approximate.

## User Setup Required

None.

## Known Stubs

None. The RED skeletons were replaced in the GREEN commits; `grep -rn "TODO\|FIXME" backend/app` prints nothing.

## Threat Flags

None. T-01-07 (allowlist tampering) and T-01-08 (fake results) are mitigated by the tests above; no new network, auth or file-access surface was added.

## Next Phase Readiness
- 01-06 can import `EXCLUDED_FILE_PATTERNS`; 01-07 can wire `normalize_and_filter` and `min_size_bytes`; 01-08 can wire `decide`.
- Note for 01-08: `FileDecision.zero_ids` on a rejected torrent lists every index; the pipeline should delete the torrent on `accept=False` rather than set priorities.

---
*Phase: 01-portal-search-start-download*
*Completed: 2026-10-22*

## Self-Check: PASSED
