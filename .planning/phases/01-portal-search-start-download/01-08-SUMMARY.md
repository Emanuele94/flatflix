---
phase: 01-portal-search-start-download
plan: 08
subsystem: backend-download
tags: [python, fastapi, qbittorrent, asyncio, pipeline, allowlist, integration-test, tdd]

requires:
  - phase: 01-portal-search-start-download
    provides: "01-03 decide() allowlist; 01-06 bootstrap, require_ready, FILT-01 exclusion list; 01-07 search cache get_result"
provides:
  - "POST /api/download {result_id, type} -> {status, job_id}; GET /api/download/{job_id}"
  - "app.download.pipeline.DownloadPipeline: submit, run, reconcile; ResultExpired, TypeMismatch"
  - "app.download.jobs: JobState, Job, JobRegistry (strong task references, per-result dedupe)"
  - "QbitClient torrent methods: add_torrent (AddResult), torrents_info, torrent_files, set_file_priority, start, delete, remove_tags, delete_tags; no set_category"
  - "Settings METADATA_TIMEOUT=300 and DOWNLOAD_WAIT_SECONDS=15; qBittorrent tags fx, fx-pending, fx-job-<id>"
  - "FakeQbit torrent endpoints and set_metadata; opt-in real-engine guard tests under backend/tests/integration"
affects: [01-09, 01-13]

plan_head_before: 164265b8ed3079d919d1c700e2356097d4d8bd89
plan_head_after: 7e8a53e18331f0a610692056c6aa939bf57e82f6

actuals:
  tokens: 18356
  tasks: 2
  commits: 3

tech-stack:
  added: []
  patterns:
    - "Add started with stopCondition=MetadataReceived + autoTMM; qBittorrent stops the torrent itself once the file list is known (D-23)"
    - "fx-pending tag from add until the allowlist ran: a restart can find and finish or delete every unfiltered torrent"
    - "submit() has no await between the dedupe check and spawn, so concurrent taps on one result share one job"
    - "Injected clock and sleep on the pipeline: tests advance a fake clock instead of waiting"

key-files:
  created:
    - backend/app/download/jobs.py
    - backend/app/download/pipeline.py
    - backend/app/routers/download.py
    - backend/tests/test_download_pipeline.py
    - backend/tests/integration/__init__.py
    - backend/tests/integration/conftest.py
    - backend/tests/integration/test_real_qbit.py
  modified:
    - backend/app/qbit/client.py
    - backend/app/qbit/bootstrap.py
    - backend/app/main.py
    - backend/app/config.py
    - .env.example
    - backend/tests/fakeqbit.py
    - backend/tests/test_validation.py

key-decisions:
  - "A STARTED job dedupes a repeat tap only for 60 s; after that the tap runs again and the btih check answers Gia presente (or re-adds a torrent the user deleted)"
  - "A 404 from torrents/files right after a magnet add is retried like an empty list (the real engine answers it for a moment), bounded by METADATA_TIMEOUT"
  - "A resumed (reconciled) job reuses the id from its fx-job tag, so a browser still polling the old job_id sees the outcome; torrents whose job tag belongs to a job of this process are skipped"
  - "Bootstrapper gets an on_ready hook that runs reconcile after readiness; a qBittorrent error there is retried with the bootstrap backoff, any other exception is logged and never marks readiness failed"
  - "A non-magnet torrent that never appears under its job tag becomes unavailable with nothing to delete; if it shows up later it keeps fx-pending and the next reconcile removes it once it is older than METADATA_TIMEOUT"
  - "Tag cleanup after start is best effort: the torrent is already filtered and running, so a cleanup error does not fail the job"

requirements-completed: [DOWN-02, FILT-02]
# DOWN-01, DOWN-03, SEC-03, SEC-01 and PUI-02 are declared by this plan but not marked:
# requirements.ready-ids listed them as blocked (01-09 or 01-13 still declare them).

coverage:
  - id: D1
    description: "A download request sends only {result_id, type}; the backend adds the torrent with category from the type, autoTMM=true, stopCondition=MetadataReceived, tags fx/fx-pending/fx-job-<id> and no stopped flag (DOWN-01, DOWN-02, D-23)"
    requirement: "DOWN-02"
    verification:
      - kind: unit
        ref: "backend/tests/test_download_pipeline.py::test_film_download_is_added_in_film_category_filtered_and_started, ::test_serie_download_uses_the_serie_category"
        status: pass
    human_judgment: false
  - id: D2
    description: "On the real qBittorrent 5.2.4 the Sintel magnet ends in category Film at /media/Film with Sintel.mp4 and every .srt at priority >= 1, poster.jpg at 0, started only after that (DOWN-03, FILT-02)"
    requirement: "FILT-02"
    verification:
      - kind: integration
        ref: "QBIT_TEST_URL=http://127.0.0.1:8088 pytest backend/tests/integration -m integration: 2 passed, 0 skipped (run 6 times)"
        status: pass
    human_judgment: false
  - id: D3
    description: "No video, only samples, filePrio mismatch and metadata timeout all delete the torrent with deleteFiles=true and never call start; season packs keep every episode (FILT-02, D-13, D-14, D-12)"
    requirement: "FILT-02"
    verification:
      - kind: unit
        ref: "backend/tests/test_download_pipeline.py (rejected x2, season_pack, priority_that_did_not_stick, no_metadata_before_the_timeout, reconcile x4)"
        status: pass
    human_judgment: false
  - id: D4
    description: "Slow metadata answers preparing within DOWNLOAD_WAIT_SECONDS and the background job later reaches started; duplicates (btih present, 409), non-magnet downloader flow, URL with a line break, double tap, concurrent film+serie categories"
    requirement: "DOWN-01"
    verification:
      - kind: unit
        ref: "backend/tests/test_download_pipeline.py (29 tests)"
        status: pass
    human_judgment: false
  - id: D5
    description: "POST /api/download rejects extra fields, bad type and result_id with 422, expired or unknown results with 410 search_expired, type mismatch with 422, answers 401 and 503 as needed, and only {status, job_id} ever leaves the backend (SEC-03, SEC-01, PUI-02)"
    requirement: "SEC-03"
    verification:
      - kind: unit
        ref: "backend/tests/test_validation.py (download section, 24 cases) and test_routes_protected.py"
        status: pass
    human_judgment: false
  - id: D6
    description: "Whether a real search result from a live plugin (not the Sintel demo) downloads end to end from a phone"
    verification: []
    human_judgment: true
    rationale: "Live trackers and plugin pages vary; by plan this is covered by the end-to-end phone check in 01-09 and the row UI in 01-13. Live search results were not added to the real qBittorrent."

duration: "about 18 min (start time not captured; estimated from commit times)"
completed: 2026-10-22
status: complete
---

# Phase 1 Plan 08: Download pipeline Summary

**POST /api/download turns {result_id, type} into a torrent that stops after metadata, is filtered by the allowlist with priorities set and re-read, and only then started, proven on the real qBittorrent 5.2.4 with the Sintel demo and a synthetic multi-file torrent**

## Performance

- **Duration:** about 18 min (start time not captured; estimated)
- **Completed:** 2026-10-22T11:13:35Z
- **Tasks:** 2 of 2
- **Files:** 7 created, 7 modified

## Accomplishments
- Tracer on the real engine: Sintel magnet added through the API ends with category `Film`, save path `/media/Film`, `Sintel.mp4` and `.srt` enabled, `poster.jpg` at 0, tags `fx` only. The synthetic torrent shows the three `.exe` variants at priority 0 straight after add and `decide()` keeps only `Movie/Movie.mkv`.
- A8 evidence: `downloaded=0` bytes just before `torrents/start` in every one of the 6 real-engine runs (5.2.4, magnet flow).
- Every outcome of D-10..D-14 is a tested job state: started, rejected, unavailable, duplicate, failed, plus preparing for a slow answer.
- A restart cannot strand or silently start an unfiltered torrent: `reconcile` runs right after readiness (expired `fx-pending` deleted with files, the rest resumed through the allowlist, category never changed).
- Backend suite 352 passed (was 299), infra tests included; frontend untouched (38 vitest tests not rerun, no frontend file changed).

## TDD Gate Compliance

Task 1 is `type="tracer"` (tests written with the code, committed once after the real-engine run). Task 2 is `tdd="true"`.

| Task | RED commit | GREEN commit |
|------|------------|--------------|
| 1 Tracer | - (tracer) | `a2a1f89` feat(01-08) |
| 2 Hardening | `0539b7c` test(01-08) | `7e8a53e` feat(01-08) |

No REFACTOR commit: nothing needed cleaning after GREEN.

### RED evidence and semantic assessment

pytest is not a report format `gsd_run check tdd-red-evidence` supports, so RED was assessed by hand from the real pytest output: 13 failed, 83 passed, 0 collection errors. Every failure was an assertion on planned behaviour (for example `'started' == 'rejected'`, `'preparing' == 'unavailable'`, `'failed' == 'duplicate'`, `2 == 1` adds for the double tap, `reconcile did not resume the torrent`). The 83 that passed already covered behaviour the tracer had (priority verify, preparing, validation 422/410/401/503, line-break rejection). The RED commit includes a no-op `reconcile()` placeholder so the reconcile tests fail on assertions instead of `AttributeError`.

### Tracer gate

Task 1 ran with an automated-only `<verify>`; it was re-run after the commit-ready state (unit tests, then the real-engine run with the admin override, then the base stack restored) before expanding: tracer verified end-to-end, expansion continued.

## Task Commits

1. **Task 1: Tracer, filtered download on the real qBittorrent** - `a2a1f89` (feat)
2. **Task 2: Hardening** - `0539b7c` (test), `7e8a53e` (feat)

**Plan metadata:** recorded in the docs(01-08) commit that follows this file.

## Files Created/Modified
- `backend/app/download/pipeline.py` - submit, run, reconcile; the add -> metadata -> decide -> priorities -> verify -> start sequence
- `backend/app/download/jobs.py` - job states and registry holding strong task references (500 finished jobs kept)
- `backend/app/routers/download.py` - routes, `DownloadRequest` (extra forbid, strict, `^[0-9a-f]{16}$`)
- `backend/app/qbit/client.py` - torrent methods, `AddResult`; newline guard; no re-categorize method
- `backend/app/qbit/bootstrap.py` - `on_ready` hook
- `backend/tests/fakeqbit.py` - torrent endpoints, `set_metadata`, knobs for delayed metadata, 404, ignored priorities, delayed downloader torrents
- `backend/tests/integration/*` - opt-in guard (skipped unless `QBIT_TEST_URL`, deselected by default through the existing marker)

## Decisions Made
See key-decisions in the frontmatter.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Real engine answers 404 for `torrents/files` right after a magnet add**
- **Found during:** Task 1, first real-engine run (one of the first two runs failed with `QbitError HTTP 404`; later runs passed, so it is a race)
- **Issue:** the tracer treated any non-2xx from `torrents/files` as a failure.
- **Fix:** 404 is retried like an empty list (bounded by the metadata deadline from Task 2 on). A fake knob (`files_404_calls`) and a test cover it.
- **Files modified:** backend/app/download/pipeline.py, backend/tests/fakeqbit.py, backend/tests/test_download_pipeline.py
- **Commit:** a2a1f89

**2. [Rule 2 - Missing critical] STARTED jobs dedupe a repeat tap for 60 s only**
- **Found during:** Task 2 design
- **Issue:** the plan says a job that is "preparing or started" absorbs a second tap. Kept forever, a user who deleted the torrent and tapped again would see Avviato while nothing happened.
- **Fix:** preparing jobs always absorb the tap; started jobs for `STARTED_DEDUPE_SECONDS = 60`. After that the btih check answers `duplicate` ("Gia presente") or the torrent is added again.
- **Files modified:** backend/app/download/pipeline.py, backend/app/download/jobs.py (newest job wins in `active_for_result`)
- **Commit:** 7e8a53e

**3. [Rule 3 - Blocking] `backend/app/qbit/bootstrap.py` was not in the plan's file list**
- **Issue:** the plan says to call `reconcile()` from the bootstrap task right after readiness; that needs a hook in `Bootstrapper`.
- **Fix:** optional `on_ready` callback, wired in `main.py` through a lambda that looks up `app.state.pipeline` at call time.
- **Commit:** 7e8a53e

**4. [Rule 3 - Blocking] Real qBittorrent login answers 204, not 200**
- **Found during:** Task 1, synthetic-torrent test setup; fixed in the test assertion (accept 200 or 204).
- **Commit:** a2a1f89

**Total deviations:** 4 auto-fixed (1 bug, 1 missing critical, 2 blocking). **Impact:** none on scope; all inside the plan's goal.

## Issues Encountered
- The Sintel swarm answered within about 2 s every time, so the plan's fallback (synthetic torrent as the only engine proof) was not needed.
- Real-engine runs recreate the qBittorrent and backend containers (admin override on and off). The base stack was restored after each run (`docker compose port qbittorrent 8088` prints nothing); `data/media/Film`, `data/media/SerieTV` and `data/incomplete` are empty.
- No live search result was added to the real qBittorrent; only the Sintel magnet and a locally bencoded torrent were, each deleted with its files in a `finally`.

## User Setup Required
None. `.env.example` gained `DOWNLOAD_WAIT_SECONDS` and `METADATA_TIMEOUT` (defaults apply when absent).

## Known Stubs
None. The RED placeholder `reconcile()` was replaced in the GREEN commit; `grep -rn "TODO\|FIXME\|placeholder" backend/app` prints nothing relevant.

## Threat Flags
None beyond the plan's threat model (T-01-30 to T-01-35 are mitigated and tested: extra fields 422, line break ValueError before any request, priorities verified before start, category only from the fixed map, two-key responses, startup reconcile).

## Next Phase Readiness
- 01-13 can build the Scarica button on `POST /api/download` and `GET /api/download/{job_id}` with states preparing, started, rejected, unavailable, duplicate, failed.
- Residual race accepted per A8: nothing was observed downloaded before the stop (`downloaded=0`), and disallowed files are priority 0 before `start`.

---
*Phase: 01-portal-search-start-download*
*Completed: 2026-10-22*

## Self-Check: PASSED
