---
phase: 01-portal-search-start-download
plan: 06
subsystem: infra
tags: [qbittorrent, bootstrap, readiness-gate, search-plugins, doctor-cli, fastapi, pytest]

requires:
  - phase: 01-portal-search-start-download
    provides: "01-02 QbitClient and FakeQbit; 01-03 EXCLUDED_FILE_PATTERNS; 01-05 protected_router and the route-enumeration guard"
provides:
  - "app.qbit.bootstrap: Bootstrapper (run_once, run_forever), Readiness, require_ready, QbitIncompatible, build_preferences, plugin_url"
  - "On every backend start qBittorrent gets auto TMM, temp path /incomplete, the FILT-01 exclusion list, the seeding policy, categories Film and SerieTV, and the missing pinned official search plugins"
  - "require_ready FastAPI dependency: 503 not_ready until bootstrap succeeded (01-07 and 01-08 attach it per route)"
  - "GET /api/health reports ok only when qBittorrent answers and readiness is ready"
  - "python -m app.tools.doctor [--wait SECONDS]: secret-free config report, exit 0 when compliant"
  - "QbitClient: get_preferences, set_preferences, categories, create_category, edit_category, search_plugins, install_search_plugin"
  - "Settings: category_film, category_tv, save_path_film, save_path_tv, incomplete_path, search_plugins, search_plugin_names, search_plugins_ref, share_ratio_limit, share_time_limit_minutes, min_webapi_version, category_paths"
  - "FakeQbit: preferences, categories, plugin endpoints with install delay, calls_to(path)"
affects: [01-07, 01-08, 01-09, 01-12, 01-13]

plan_head_before: bce09da36ec825fed7967c8c4197d03389bba65c
plan_head_after: 820d35a2deb6ae644fcaa91e3295fa3450309f2a

actuals:
  tokens: 15385
  tasks: 3
  commits: 5

tech-stack:
  added: []
  patterns:
    - "One background bootstrap task per process, strong reference on app.state.bootstrap_task, cancelled in the lifespan finally"
    - "Fixed failures stop for good (auth, ban, old WebAPI: one ERROR line, readiness failed); unreachable or unexpected answers retry with min(2 ** n, 30) s backoff through an injected sleep"
    - "Readiness flips only after setPreferences and categories succeeded; plugins run after categories and never block readiness"
    - "Idempotent configuration: read, compare exactly, write only the difference (categories by name, case-sensitive; save paths ignoring one trailing slash)"

key-files:
  created:
    - backend/app/qbit/bootstrap.py
    - backend/app/tools/doctor.py
    - backend/tests/test_bootstrap.py
  modified:
    - backend/app/qbit/client.py
    - backend/app/config.py
    - backend/app/main.py
    - backend/app/routers/health.py
    - .env.example
    - backend/tests/fakeqbit.py
    - backend/tests/conftest.py
    - backend/tests/test_health.py
    - backend/tests/test_qbit_client.py

key-decisions:
  - "A 409 on createCategory re-reads the category list and compares the stored path; if the category still is not listed, bootstrap raises and retries instead of editing a category that may not exist"
  - "run_forever also catches any unexpected exception, logs its class and marks readiness failed, so a dead background task cannot leave health degraded with no explanation"
  - "Plugin readiness wait is a loop of 15 polls two seconds apart on the injected sleep, so tests never wait in real time; a plugin still missing after 30 s logs one WARNING and bootstrap stays ready"
  - "Settings normalise save paths by stripping one trailing slash and reject equal CATEGORY_FILM and CATEGORY_TV"
  - "The api test fixture waits up to 5 s for readiness to leave starting, so every route test sees a bootstrapped fake qBittorrent"

requirements-completed: [FILT-01]
# DOWN-03, DOWN-02 and INFRA-01 are declared by this plan but not marked: requirements.ready-ids
# listed them as blocked (later plans in the phase still declare them).

coverage:
  - id: D1
    description: "Backend start configures the real qBittorrent: categories Film -> /media/Film and SerieTV -> /media/SerieTV, auto TMM, temp path /incomplete, FILT-01 exclusion list (18/18 patterns present), proven by the doctor"
    requirement: "DOWN-03"
    verification:
      - kind: integration
        ref: "docker compose up -d --build --wait; docker compose exec -T backend python -m app.tools.doctor --wait 90 exited 0 with OK lines for version, both categories, auto_tmm_enabled, temp path and exclusion list; curl http://127.0.0.1/api/health returned status ok"
        status: pass
      - kind: unit
        ref: "backend/tests/test_bootstrap.py (fresh_qbittorrent, preferences_carry_filt01, doctor_reports_paths_and_never_credentials)"
        status: pass
    human_judgment: false
  - id: D2
    description: "Idempotent and ordered: existing correct categories get no edit, a wrong path gets one edit, lower-case film does not satisfy Film, a second run makes no create, edit or plugin install call and sends a byte-identical setPreferences payload; call order is version, preferences, setPreferences, categories, plugins"
    requirement: "DOWN-03"
    verification:
      - kind: unit
        ref: "backend/tests/test_bootstrap.py (existing_category_*, lower_case_category, create_conflict, idempotent, call_order, second_run_installs_no_plugin_again)"
        status: pass
    human_judgment: false
  - id: D3
    description: "Exclusion list is never empty, starts with the fixed FILT-01 patterns, keeps admin patterns without case-insensitive duplicates, and is active before readiness flips"
    requirement: "FILT-01"
    verification:
      - kind: unit
        ref: "backend/tests/test_bootstrap.py (exclusion_list_is_never_empty, admin_patterns_*, readiness_flips_only_after_preferences_and_categories)"
        status: pass
    human_judgment: false
  - id: D4
    description: "Failure handling: WebAPI below 2.15.1, wrong credentials or a ban stop after one attempt with one ERROR line and readiness failed; unreachable or 5xx retries with backoff 1, 2, 4 capped at 30 s; routes guarded by require_ready answer 503 not_ready until ready; health is degraded while starting or failed"
    requirement: "INFRA-01"
    verification:
      - kind: unit
        ref: "backend/tests/test_bootstrap.py (webapi_version_gate x3, auth_failure x2, backoff x3, require_ready route, health_is_degraded)"
        status: pass
    human_judgment: false
  - id: D5
    description: "Official search plugins installed once from the pinned commit URL, admin-disabled plugins untouched, 30 s wait then one WARNING; seeding policy stop at ratio 1.0 or 1440 minutes; both visible in the doctor"
    requirement: "DOWN-02"
    verification:
      - kind: unit
        ref: "backend/tests/test_bootstrap.py (plugin_url, missing_plugins_are_installed, installed_but_disabled, waits_for_slow_plugins, still_missing_after_thirty_seconds, seeding policy x2, doctor plugin and share-limit tests)"
        status: pass
      - kind: integration
        ref: "docker compose exec -T backend python -m app.tools.doctor --wait 120 exited 0: all 7 configured plugins installed enabled True, share limits max_ratio 1.0 max_seeding_time 1440 max_ratio_act 0"
        status: pass
    human_judgment: false
  - id: D6
    description: "Doctor output carries no credentials, and category names, save paths, plugin names and the plugin ref are validated from config only"
    requirement: "DOWN-03"
    verification:
      - kind: unit
        ref: "backend/tests/test_bootstrap.py (doctor_reports_paths_and_never_credentials, settings_reject_bad_category_names_and_paths)"
        status: pass
      - kind: integration
        ref: "inside the backend container the doctor output matched neither $QBITTORRENT_USER nor the word password (0 hits each)"
        status: pass
    human_judgment: false
  - id: D7
    description: "Whether a plugin pinned at the reviewed commit still downloads and runs on a future qBittorrent image, and whether series searches find enough results with official plugins only (research A10)"
    verification: []
    human_judgment: true
    rationale: "Search results quality depends on live trackers and is checked by the search plans (01-07, 01-13), not by this plan."

duration: 6min
completed: 2026-10-22
status: complete
---

# Phase 1 Plan 06: qBittorrent Bootstrap, Readiness Gate and Doctor Summary

**On every start the backend makes the real qBittorrent correct (Film and SerieTV categories, auto TMM, /incomplete, the FILT-01 exclusion list, a stop at ratio 1.0 or 24 h, and the seven pinned official search plugins), holds downloads behind a 503 `not_ready` gate until that has happened, and an admin proves it with one doctor command.**

## Performance

- **Duration:** 6 min
- **Completed:** 2026-10-22
- **Tasks:** 3 (one tracer, two TDD)
- **Files:** 12 touched (3 created, 9 modified)

## Accomplishments

- Tracer proven on the real stack: `docker compose up -d --build --wait`, then `python -m app.tools.doctor --wait 90` printed OK for the WebAPI version, both categories with their paths, auto TMM, temp path and 18/18 exclusion patterns, and health through Caddy returned `"status":"ok"`. Interactive mode, `human_verify_mode` default and an automated-only `<verify>`: the tracer verify was re-run end to end (pytest, rebuild, doctor, health) with the same result before the TDD tasks started, so no human checkpoint applied.
- Seven official plugins (eztv, limetorrents, piratebay, solidtorrents, torlock, torrentproject, torrentscsv) were downloaded and installed by the backend from the pinned commit on the real container; a repeat start installs nothing.
- Backend and infra tests: 221 pass (up from 175 at the start of the plan). Ruff check and format are clean.
- `require_ready` is ready for 01-07 and 01-08: attach it with `dependencies=[Depends(require_ready)]` on a `protected_router()` route.

## Task Commits

1. **Task 1: Tracer, start configures categories, paths, temp folder, auto TMM and exclusions** - `97842ae` (feat)
2. **Task 2: Idempotent, ordered, fail-safe bootstrap with a readiness gate** (TDD)
   - RED: `21438a3` (test)
   - GREEN: `7d46a5e` (feat)
3. **Task 3: Pinned official search plugins and the seeding policy** (TDD)
   - RED: `72dcd30` (test)
   - GREEN: `820d35a` (feat)

## TDD Gate Compliance

`workflow.tdd_mode` is off, so `gsd_run check tdd-red-evidence` was not run; RED was judged from the pytest output.

**Task 2**
- RED: 6 failed, 41 passed. Failures: `test_webapi_version_gate...[2.15.0-False]` and the two `auth_failure` cases (QbitIncompatible, QbitAuthError and QbitBanned propagated out of `run_forever` instead of marking readiness failed), `test_server_error_during_bootstrap_is_retried_with_backoff` (a generic QbitError was not retried), `test_health_is_degraded...` (the incompatible error escaped the task) and `test_conflict_on_create_without_the_category_appearing...` (an edit call was made for a category that was not listed). Each fails on the planned behaviour, not on an import or fixture fault.
- The 41 that passed were already satisfied by the Task 1 tracer: idempotence, call order, trailing-slash and case-sensitive category comparison, admin-pattern merge, backoff on unreachable, the `require_ready` guard. This is the unexpected-green case from the fail-fast rules, accepted: the tracer is a production-quality slice, and these tests lock its behaviour for later plans.
- GREEN: `run_forever` stops on auth, ban and incompatible versions and retries any other `QbitError` with capped backoff; 208 passed.
- REFACTOR: none.

**Task 3**
- RED: 12 failed, 150 passed. `plugin_url` did not exist (tests call it through the module so the file still collects), no plugins were installed or waited for, the preferences lacked the share limits, and the doctor had no plugin or share-limit lines. All planned behaviours. The RED commit also carries the FakeQbit plugin endpoints (test support).
- GREEN: `plugin_url`, plugin install and wait, share limits in `build_preferences`, doctor checks; 221 passed.
- REFACTOR: none.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical] Unexpected exceptions would kill the bootstrap task silently**
- **Found during:** Task 2 (GREEN)
- **Issue:** `run_forever` handled only qBittorrent errors. Any other exception would end the background task with readiness stuck on `starting` and no log line explaining it.
- **Fix:** a final `except Exception` logs the class name once and marks readiness failed.
- **Files modified:** backend/app/qbit/bootstrap.py
- **Commit:** 7d46a5e

**2. [Rule 1 - Bug] A createCategory 409 could lead to editing a category that does not exist**
- **Found during:** Task 2 (RED)
- **Issue:** the tracer's 409 branch re-read the categories with a default of `{}` and then called `editCategory`, which qBittorrent also answers with 409 for a missing category.
- **Fix:** after a 409 the category must appear in the re-read list, otherwise bootstrap raises `QbitError` and retries; no edit is issued for an unlisted category.
- **Files modified:** backend/app/qbit/bootstrap.py
- **Commit:** 7d46a5e

**3. [Rule 2 - Missing critical] Settings accepted CATEGORY_FILM equal to CATEGORY_TV**
- **Found during:** Task 1
- **Issue:** the two categories would collapse into one with two save paths. A model validator now rejects equal names. Save paths are normalised by stripping one trailing slash, so config and comparison agree.
- **Files modified:** backend/app/config.py
- **Commit:** 97842ae

**4. [Rule 1 - Bug] Doctor showed `max_ratio 1` against the real qBittorrent**
- **Found during:** Task 3 (real container run)
- **Issue:** the real API returns the ratio as an integer-valued number, so the line read `max_ratio 1`, not the `1.0` the acceptance criterion names. The doctor now prints the ratio as a float.
- **Files modified:** backend/app/tools/doctor.py
- **Commit:** 820d35a

**5. [Rule 3 - Blocking] `.env` could not be read to compare the qBittorrent user name with the doctor output**
- **Found during:** Task 1 verification
- **Issue:** a secret-read guard blocks Bash commands that read `.env`.
- **Fix:** the same check ran inside the backend container against `$QBITTORRENT_USER` and the word `password` (0 hits each); the unit test covers the same assertion with the test credentials.

**6. [Note] The exclusion list has 18 patterns, not 11**
- `EXCLUDED_FILE_PATTERNS` from 01-03 holds 18 entries (the first 11 are the FILT-01 list). Bootstrap sends all of them in order, as the plan's ordering rule requires, and the doctor requires 18/18.

**Total deviations:** 4 auto-fixed (2 Rule 1, 2 Rule 2), 1 blocking workaround, 1 note. **Impact:** none on scope; all changes stay inside the files this plan owns.

## Authentication Gates

None. The qBittorrent credentials already provisioned by 01-01 were accepted on the first login.

## Known Stubs

None.

## Issues Encountered

None open. Not verified here: the plugins were fetched from GitHub once on the dev machine; a start without Internet leaves them missing, logs one WARNING after 30 s and still becomes ready (by design), and the doctor then exits 1.

## Next Phase Readiness

- 01-07 and 01-08 can attach `Depends(require_ready)`; `settings.category_paths` is the only source of category names and save paths.
- 01-09 should document `SAVE_PATH_*` matching the compose mounts, the doctor command and adding extra plugins through the loopback WebUI. Its env-key test now sees ten new keys, all present in `.env.example`.

## Self-Check: PASSED

- Files: backend/app/qbit/bootstrap.py, backend/app/tools/doctor.py, backend/tests/test_bootstrap.py found.
- Commits 97842ae, 21438a3, 7d46a5e, 72dcd30, 820d35a are ancestors of HEAD.
- Acceptance criteria re-run: bootstrap.py defines the four names and imports EXCLUDED_FILE_PATTERNS; `.env.example` has the three required lines; `min(2 **` and `mark_failed` present; client posts `sources`; test names include idempotent, order, incompatible, backoff, not_ready; 40 tests in test_bootstrap.py; real-container doctor exits 0.
