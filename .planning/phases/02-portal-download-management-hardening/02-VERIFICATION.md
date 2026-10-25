---
phase: 02-portal-download-management-hardening
verified: 2026-10-25T09:00:00Z
status: passed
score: 4/4 must-haves verified
covered_files:
  - ".planning/phases/02-portal-download-management-hardening/02-01-PLAN.md"
  - ".planning/phases/02-portal-download-management-hardening/02-01-SUMMARY.md"
  - ".planning/phases/02-portal-download-management-hardening/02-02-PLAN.md"
  - ".planning/phases/02-portal-download-management-hardening/02-02-SUMMARY.md"
  - ".planning/phases/02-portal-download-management-hardening/02-03-PLAN.md"
  - ".planning/phases/02-portal-download-management-hardening/02-03-SUMMARY.md"
  - ".planning/phases/02-portal-download-management-hardening/02-04-PLAN.md"
  - ".planning/phases/02-portal-download-management-hardening/02-04-SUMMARY.md"
  - ".planning/phases/02-portal-download-management-hardening/02-05-PLAN.md"
  - ".planning/phases/02-portal-download-management-hardening/02-05-SUMMARY.md"
  - ".planning/phases/02-portal-download-management-hardening/02-06-PLAN.md"
  - ".planning/phases/02-portal-download-management-hardening/02-06-SUMMARY.md"
  - ".planning/phases/02-portal-download-management-hardening/02-07-PLAN.md"
  - ".planning/phases/02-portal-download-management-hardening/02-07-SUMMARY.md"
  - ".planning/phases/02-portal-download-management-hardening/02-08-PLAN.md"
  - ".planning/phases/02-portal-download-management-hardening/02-08-SUMMARY.md"
  - ".planning/phases/02-portal-download-management-hardening/02-09-PLAN.md"
  - ".planning/phases/02-portal-download-management-hardening/02-09-SUMMARY.md"
  - ".planning/phases/02-portal-download-management-hardening/02-10-PLAN.md"
  - ".planning/phases/02-portal-download-management-hardening/02-10-SUMMARY.md"
  - ".planning/phases/02-portal-download-management-hardening/02-11-PLAN.md"
  - ".planning/phases/02-portal-download-management-hardening/02-11-SUMMARY.md"
  - "backend/app/audit.py"
  - "backend/app/download/listing.py"
  - "backend/app/download/pipeline.py"
  - "backend/app/main.py"
  - "backend/app/routers/auth.py"
  - "backend/app/routers/download.py"
  - "backend/app/routers/downloads.py"
  - "backend/app/routers/search.py"
  - "backend/app/throttle.py"
  - "backend/tests/integration/test_real_downloads.py"
  - "docker-compose.yml"
  - "docs/setup.md"
  - "frontend/src/App.jsx"
  - "frontend/src/DownloadRow.jsx"
  - "frontend/src/Downloads.jsx"
  - "frontend/src/Search.jsx"
  - "frontend/src/messages.js"
  - "scripts/smoke.py"
  - "web/Caddyfile"
covered_digest: "v3:sha256:f64b3e357a293f23ad04d68dcf9e0ceab3886fc681923059b332828c0dd98da3"
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: passed
  previous_score: 4/4
  gaps_closed: []
  gaps_remaining: []
  regressions: []
advisory:
  - finding: "backend/tests/test_download_cancel.py is intermittently red: a random test of the file fails with 401, 404 or KeyError 'items' on a DELETE or list call that follows a successful login and POST (3 of 8 full-file runs here; each test passes alone)."
    category: other
    reason: "Reproduced at b343a00, the Phase 2 verified commit, before any Phase 2.1 code (3 failing runs of 10), so it is a pre-existing test-isolation flake, not a Phase 2.1 regression. The 401 source was not traced. The orchestrator's full run (988 passed) was green. Resolve by finding why the logged-in rig loses its session in some runs."
    evidence_status: "reproduced twice (current tree and b343a00), root cause not identified"
---

# Phase 2: Portal Download Management & Hardening Verification Report

**Phase Goal:** The user can follow and cancel her downloads from the phone, and the portal degrades gracefully, throttles abuse and keeps audit logs.
**Verified:** 2026-10-25
**Status:** passed
**Re-verification:** Yes. The earlier report (passed, 2026-10-23) went stale because Phase 2.1 (download quarantine + Firecracker check) changed `audit.py`, `listing.py`, `pipeline.py`, `main.py`, `routers/downloads.py`, `docker-compose.yml`, `docs/setup.md`, `DownloadRow.jsx`, `messages.js` and `scripts/smoke.py`. Every Phase 02 truth was re-checked against the current code.

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | The user sees a list of Film and SerieTV downloads, in progress and completed, with state and progress refreshing about every 5 s | VERIFIED | `GET /api/downloads` (`routers/downloads.py`) reads `qbit.torrents_info()` plus the job registry plus the outcome store and calls `build_items` (`download/listing.py`), which skips every category other than Film/SerieTV and gives each row the same eight keys (id, name, type, state, progress, eta_seconds, action, skipped). Phase 2.1 added `checking` (a finished torrent under quarantine with no verified tag) and `check_failed` / `ready` outcome rows; in-progress, stalled, preparing, problem, failed-attempt and ready rows follow the Phase 2 table unchanged. `Downloads.jsx` keeps `POLL_MS = 5000`, reschedules after each answer, and pauses on `visibilityState === 'hidden'` with a `visibilitychange` listener removed on cleanup. `DownloadRow.jsx` has a state entry for every state the backend can emit (preparing, downloading, stalled, checking, check_failed, ready, problem, rejected, unsupported, unavailable, failed). Tests: `test_download_listing.py`, `test_downloads_api.py` pass. |
| 2 | The user can cancel a download from the list and it also disappears from qBittorrent | VERIFIED | `DELETE /api/downloads/{id}` takes only the opaque id and calls `DownloadPipeline.cancel`. Read in full: it lists, finds the Film/SerieTV row by HMAC id, raises the HandoffGuard cancel flag, stops the job, and re-reads the single torrent inside the hand-off lock before `torrents/delete`, so a Cancel tapped during a probe wins. Files go per `delete_files_for`: under quarantine always (the household's own download, or a verified film whose media hardlink keeps it); outside quarantine the Phase 2 rule `cancel_deletes_files` (in-progress state, progress < 1, `completion_on` unset or <= 0), so WR-01/WR-02 still hold for Phase 1-2 torrents. The list button comes from `row_action`, which the same rules drive, so the confirm text matches the effect. A cancel whose delete fails after the job is cancelled still starts a sweep (WR-03); a Preparing job is swept before the first lookup; a ready outcome row is removed by deleting only its sidecar. Tests in `test_download_cancel.py` cover each path, including checking, problem and in-progress under quarantine, verified Remove keeping the film, a legacy torrent keeping the Phase 2 rule, and cancel during a probe. They pass (see the flake note in the advisory). |
| 3 | qBittorrent down, invalid torrent or wrong category path give plain messages (auto retry when unreachable), never a raw error | VERIFIED | The list and cancel routes turn any `QbitError` into 502 `qbit_unreachable` / `qbit_refused` through `qbit_failure`, which logs only the class name and status and never answers 401. `Downloads.jsx` shows a banner on failure (`refused` or `down`), keeps polling, and closes any open confirm. The 415 and 409 handling in `pipeline.py` and the copy in `messages.js` are unchanged in kind; Phase 2.1 only added keys (`checkingHint`, `cancelConfirmBodyDone`, `skippedOne/Many`, `checkFailed`). `test_downloads_api.py`, `test_download_pipeline.py` pass. |
| 4 | Rapid repeated search or download requests are throttled, and logs record logins, searches, downloads, cancels and errors without credentials | VERIFIED | `main.py` builds `search_throttle` and `download_throttle` as `SlidingWindowThrottle` (60 s window, rates from settings). `routers/search.py` and `routers/download.py` call `try_acquire`, then `audit.throttled` and answer 429 `too_many_requests`; `Search.jsx` maps 429 to a plain message. `audit.py` still has login, logout, search, throttled, download, download_done, cancel/remove (`removed`) and error events, with free text JSON-escaped and cut at 200 characters, class and status only for errors. Phase 2.1 added `quarantine.*` events through the same typed helpers (names via `_text`, reasons and counts via `_token`, no path, hash or tool output). `RedactingFilter` is installed by `configure_logging` on the root and uvicorn handlers; the only direct `logger` calls under `app/quarantine` log a class name. `docker-compose.yml` still applies the `x-logging` json-file anchor to every service. `test_audit.py`, `test_no_leaks.py`, `test_rate_limit.py` pass. |

**Score:** 4/4 truths verified, 0 behavior-unverified.

### Phase 2.1 impact check on the changed files

| File | What Phase 2.1 changed | Effect on Phase 02 truths |
|------|------------------------|---------------------------|
| `download/listing.py` | `plain_state(row, settings, now)` adds `checking` / `problem` for unverified quarantine rows; `delete_files_for`, `row_action`; outcome rows; window counts from Ready | With one argument `plain_state` still gives the Phase 2 answer; legacy torrents (outside quarantine) keep the Phase 2 table. Truths 1, 2 hold. |
| `download/pipeline.py` | `cancel` uses the guard lock and `delete_files_for`; `_remove_ready_outcome` | Cancel still stops the job first, re-reads the torrent, then deletes, with the WR-01..WR-03 safeguards. Truth 2 holds. |
| `routers/downloads.py` | Loads outcomes, passes them to `build_items` | List still read-only, 502 codes unchanged. Truths 1, 3 hold. |
| `main.py` | Adds guard, outcome store, runner client, verifier task in the lifespan; throttles and logging unchanged | Throttles and redaction still created before the first request. Truth 4 holds. |
| `audit.py` | Adds `quarantine_*` helpers | Existing helpers unchanged; new ones follow the same no-secret rules. Truth 4 holds. |
| `docker-compose.yml`, `docs/setup.md` | Quarantine bind, sandbox service, setup steps | Log rotation anchor and the documented rate limits still present. |
| `DownloadRow.jsx`, `messages.js` | Checking, check_failed, skipped note, confirm body for finished files | Cancel/Remove confirm and states unchanged for Phase 2 rows; the phone check of these was done in the Phase 2.1 UAT (tests 1 and 2, pass). |
| `scripts/smoke.py` | Eight-key contract, Ready and Remove steps | Shape check matches `build_items`; `test_smoke_contract.py` passes. |

### Required Artifacts

| Artifact | Status | Details |
|----------|--------|---------|
| `backend/app/download/listing.py` | VERIFIED | Substantive (386 lines), used by the router and the pipeline. |
| `backend/app/download/pipeline.py` | VERIFIED | `cancel`, `_cancel_job_without_torrent`, `_remove_ready_outcome`, `_start_sweep`, `_sweep_once` present and wired from `routers/downloads.py`. |
| `backend/app/routers/downloads.py` | VERIFIED | Included by `main.py`; behind `protected_router`. |
| `backend/app/throttle.py` | VERIFIED | Used for login, search and download. |
| `backend/app/audit.py` | VERIFIED | Called by auth, search, download and downloads routers; filter installed in `configure_logging`. |
| `frontend/src/Downloads.jsx`, `DownloadRow.jsx`, `messages.js` | VERIFIED | Polling, banner, row states and actions present. |
| `web/Caddyfile`, `docker-compose.yml` | VERIFIED | Not touched by Phase 2.1 except the compose services added; the logging anchor remains. |

### Key Link Verification

| From | To | Status |
|------|----|--------|
| `main.py` -> `routers/downloads.py` | included router | WIRED |
| `routers/downloads.py` -> `DownloadPipeline.cancel` via `app.state.pipeline` | DELETE route | WIRED |
| `routers/downloads.py` -> `build_items` with `jobs` and `outcomes` | list route | WIRED |
| `routers/search.py`, `routers/download.py` -> `search_throttle` / `download_throttle` -> `audit.throttled` -> 429 | throttling | WIRED |
| `main.configure_logging` -> `audit.install_redaction` | log redaction | WIRED |
| `Downloads.jsx` -> `/api/downloads` (GET every 5 s, DELETE with id only) | polling and cancel | WIRED |
| `listing.row_action` and `pipeline.cancel` -> `delete_files_for` | button matches effect | WIRED |

### Data-Flow Trace (Level 4)

| Artifact | Data | Source | Real data | Status |
|----------|------|--------|-----------|--------|
| `Downloads.jsx` items | `/api/downloads` | `qbit.torrents_info()` + `JobRegistry` + `OutcomeStore.load_all` -> `build_items` | Yes | FLOWING |
| Row `action` | `row_action(row, settings)` | the live torrent row (save path, tags, state, `completion_on`) | Yes | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full backend suite | orchestrator: `pytest backend/tests -q` | 988 passed, 19 integration deselected | PASS (orchestrator) |
| Infra suite | orchestrator: `pytest infra/tests -q` | 98 passed | PASS (orchestrator) |
| Frontend suite | orchestrator: `npm --prefix frontend test` | 271 passed | PASS (orchestrator) |
| Phase 02 area, run by me | `pytest test_download_listing test_download_cancel test_downloads_api test_rate_limit test_audit test_no_leaks test_smoke_contract` | 331 passed, 1 failed on the first run; `test_download_cancel.py` alone: 34 passed in 5 of 8 runs, 1 or 2 intermittent failures in the others (a different test each time); each failing test passes alone | PASS with advisory |
| Same file at the Phase 2 commit | `pytest backend/tests/test_download_cancel.py` in a worktree at b343a00 | 3 of 10 runs had failures | confirms the flake predates Phase 2.1 |

### Probe Execution

No `scripts/*/tests/probe-*.sh` exist and no plan declares one. `scripts/smoke.py` needs the running stack and was not run here (no stack running; Step 7b constraint: no starting services). The real-engine suite (`-m integration`) needs a live qBittorrent and was not re-run; the Phase 2 run (7 passed vs qBittorrent 5.2.4) pinned the `completion_on <= 0` assumption that the WR-01 guard relies on, and no Phase 2.1 change touches that rule for torrents outside quarantine.

### Requirements Coverage

| Requirement | Source Plans | Description | Status | Evidence |
|-------------|--------------|-------------|--------|----------|
| DOWN-04 | 02-01, 02-04, 02-06, 02-11 | List Film/SerieTV downloads, ~5 s refresh | SATISFIED | Truth 1 |
| DOWN-05 | 02-07, 02-10, 02-11 | Cancel from the list, removed from qBittorrent | SATISFIED | Truth 2 |
| DOWN-06 | 02-01, 02-02, 02-07, 02-08, 02-11 | Plain messages for 415, 502 with retry, 409, generic 401 | SATISFIED | Truth 3 |
| SEC-05 | 02-05, 02-08 | Search and download rate limited with a clear message | SATISFIED | Truth 4 |
| SEC-06 | 02-09, 02-03 | Audit logs, no credentials in any line | SATISFIED | Truth 4; `02-SECURITY.md` closed all threats |

All five IDs from the phase are in plan frontmatter, in REQUIREMENTS.md (checked, Complete, Phase 2) and in ROADMAP. No ORPHANED requirements.

### Anti-Patterns Found

No `TBD` / `FIXME` / `XXX` in `backend/app`, `frontend/src`, `web/Caddyfile`, `docker-compose.yml`, `docs/setup.md` or `scripts/smoke.py`. No stub patterns in the downloads path. IN-01..IN-03 from `02-REVIEW-DISPOSITION.md` remain info-level. The intermittent test flake is recorded in the `advisory` frontmatter (warning-level, does not block a must-have).

### Human Verification Required

None. Carry-forward of `02-UAT.md` (complete, 3/3 passed):

1. Phone check of cancel and audit (UAT 1): the behavior is unchanged for a download in progress (Cancel still deletes the partial files and removes the torrent; the audit `cancel` line is still written by `audit.removed`). The Phase 2.1 UAT test 1 re-ran the Downloads tab on a real phone through Downloading, Checking and Ready, including Cancel on a finished file; it passed.
2. Visual backstops (UAT 2): the Phase 2.1 changes to `DownloadRow.jsx` add rows and text but keep the layout contract; the Phase 2.1 UAT test 2 (320 px, 200-character name, buttons reachable) passed on the real device.
3. Review decision (UAT 3): recorded in `02-REVIEW-DISPOSITION.md`; unaffected.

The only open Phase 2.1 human item (test 3, Ubuntu Server build, blocked until the production box exists) belongs to Phase 2.1 and not to Phase 02.

### Gaps Summary

No gaps. All four roadmap truths still hold on the current code after the Phase 2.1 changes, requirements DOWN-04, DOWN-05, DOWN-06, SEC-05 and SEC-06 are covered, and the orchestrator's full-suite gate was green. One warning-level note: `backend/tests/test_download_cancel.py` is intermittently red (a pre-existing test-isolation flake, reproduced at the Phase 2 commit), which weakens the suite as a regression signal until its cause is found.

---

_Verified: 2026-10-25_
_Verifier: Claude (gsd-verifier)_
