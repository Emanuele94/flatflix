---
phase: 02-portal-download-management-hardening
verified: 2026-10-23T10:15:00Z
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
covered_digest: "v3:sha256:a968fb926554bbb41c0ac2b58280c437889ec70bbfbce0fcad4a7f2d310260bb"
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: human_needed
  previous_score: 4/4
  gaps_closed:
    - "WR-01 cancel_deletes_files now requires no completion_on (finished-once torrent keeps files)"
    - "WR-02 cancel re-reads the single torrent right before torrents/delete"
    - "WR-03 cancel sweep for a Preparing job starts before the first lookup can fail"
    - "WR-04 RedactingFilter redacts non-string messages; short-secret limit documented"
    - "WR-05 real-engine test pins completion_on <= 0 and action cancel (7 passed vs qBittorrent 5.2.4)"
    - "Human items 1-3 satisfied by 02-UAT.md (3/3 passed)"
  gaps_remaining: []
  regressions: []
---

# Phase 2: Portal Download Management & Hardening Verification Report

**Phase Goal:** The user can follow and cancel her downloads from the phone, and the portal degrades gracefully, throttles abuse and keeps audit logs.
**Verified:** 2026-10-23
**Status:** passed
**Re-verification:** Yes. The earlier report (human_needed) went stale when review fixes WR-01..WR-05 landed and the human UAT finished.

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | The user sees a list of Film and SerieTV downloads, in progress and completed, with state and progress refreshing about every 5 s | VERIFIED | `GET /api/downloads` (`routers/downloads.py`) -> `build_items` (`download/listing.py`). `frontend/src/Downloads.jsx` has `POLL_MS = 5000`, timer rescheduled after each answer, paused when the page is hidden (`visibilityState`, `visibilitychange` listener with cleanup). `DownloadRow.jsx` renders state, progress and ETA. Frontend tests pass (241). |
| 2 | The user can cancel a download from the list and it also disappears from qBittorrent | VERIFIED | `DELETE /api/downloads/{id}` (opaque id) -> `DownloadPipeline.cancel`: re-reads the row, stops the job, re-reads the single torrent (WR-02), decides `deletes` on that fresh row via `cancel_deletes_files` (requires in-progress state, progress < 1 and `completion_on` unset/<= 0, so a finished film is never deleted, WR-01), then `torrents/delete`. Failure after the job is cancelled starts a sweep (`_start_sweep`); Preparing-job cancel starts its sweep before the first lookup (WR-03). Real phone: UAT 1 cancelled a downloading film; audit cancel line `outcome=done`, torrent gone from qBittorrent, no files left. Real-engine suite: 7 passed against qBittorrent 5.2.4 (run by the orchestrator, not re-run by me, needs a live engine). |
| 3 | qBittorrent down, invalid torrent or wrong category path give plain messages (auto retry when unreachable), never a raw error | VERIFIED | 415 -> "Not available", 409 -> duplicate/refused path handled in `pipeline.py` with class and status only logged; list route answers 502 `qbit_unreachable` / `qbit_refused` (never 401); `Downloads.jsx` shows a retrying banner and keeps its 5 s poll; copy centralised in `messages.js`. Covered by backend and frontend tests (all pass). |
| 4 | Rapid repeated search or download requests are throttled, and logs record logins, searches, downloads, cancels and errors without credentials | VERIFIED | `SlidingWindowThrottle` created in `main.py` (search and download), `try_acquire` + `audit.throttled` + 429 in `routers/search.py` and `routers/download.py`. `audit.py` events: login, logout, search, throttled, download, download_done, cancel/remove, error; `RedactingFilter` (secrets >= `MIN_SECRET_LENGTH`, cookie patterns, non-string msg and args, exc_text, stack_info) installed via `configure_logging`. `docker-compose.yml` `x-logging` json-file rotation applied per service. UAT: no secrets in backend logs after a real cancel. `test_no_leaks.py`, `test_audit.py`, `test_rate_limit.py` pass. |

**Score:** 4/4 truths verified, 0 behavior-unverified.

### Required Artifacts

Substantive and wired, confirmed by reading: `listing.py` (`cancel_deletes_files`, `build_items`), `pipeline.py` (`cancel`, `_cancel_job_without_torrent`, `_sweep_once`), `throttle.py`, `audit.py`, `Downloads.jsx`, `DownloadRow.jsx`, `Caddyfile` (`immutable` on hashed assets, `no-cache` on index), `docker-compose.yml` logging anchor. The previous run's `verify.artifacts` result (all 11 plans passed) still applies: none of those artifact paths were removed.

### Key Link Verification

Router -> pipeline (cancel), router -> throttle -> audit (search, download), main -> `configure_logging` / throttles, `App.jsx` tabs -> `Downloads.jsx` -> `/api/downloads`: all present in the code read. Action shown in the list and files deleted by DELETE both come from `cancel_deletes_files` (the same function), so the confirm text always matches the effect.

### Data-Flow Trace (Level 4)

| Artifact | Data | Source | Real data | Status |
|----------|------|--------|-----------|--------|
| `Downloads.jsx` items | `/api/downloads` | `qbit.torrents_info()` + job registry -> `build_items` | Yes (real-engine test pins raw field types incl. `completion_on` int <= 0) | FLOWING |
| Cancel action | `item.action` | `cancel_deletes_files(row)` | Yes | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Backend + infra suites | `uv run --project backend --frozen pytest backend/tests infra/tests -q` | 722 passed, 7 deselected (integration) | PASS |
| Frontend suite | `npm --prefix frontend test` | 241 passed in 8 files | PASS |
| Frontend build | `npm --prefix frontend run build` | built OK | PASS |
| Real-engine integration | `QBIT_TEST_URL=... pytest -m integration` | 7 passed vs qBittorrent 5.2.4, per orchestrator run | PASS (reported, not re-run here) |

### Probe Execution

No `scripts/*/tests/probe-*.sh` exist and no plan declares one. `scripts/smoke.py` needs the running stack; not re-run here (UAT exercised the live stack on a real phone).

### Requirements Coverage

| Requirement | Source Plans | Description | Status | Evidence |
|-------------|--------------|-------------|--------|----------|
| DOWN-04 | 02-01, 02-04, 02-06, 02-11 | List Film/SerieTV downloads, ~5 s refresh | SATISFIED | Truth 1 |
| DOWN-05 | 02-07, 02-10, 02-11 | Cancel from list, removed from qBittorrent | SATISFIED | Truth 2, UAT 1 |
| DOWN-06 | 02-01, 02-02, 02-07, 02-08, 02-11 | Plain messages for 415, 502 with retry, 409, generic 401 | SATISFIED | Truth 3 |
| SEC-05 | 02-05, 02-08 | Search and download rate limited with clear message | SATISFIED | Truth 4 |
| SEC-06 | 02-09, 02-03 | Audit logs, no credentials in any line | SATISFIED | Truth 4, 02-SECURITY.md (53/53 closed, threats_open 0) |

All five IDs appear in plan frontmatter, in REQUIREMENTS.md (Complete, Phase 2) and in ROADMAP. No orphaned requirements.

### Anti-Patterns Found

No `TBD`/`FIXME`/`XXX` in `backend/app`, `frontend/src`, `web/Caddyfile`, `docker-compose.yml`, `docs/setup.md` or `scripts/smoke.py`. No stub patterns in the downloads path. Review: WR-01..WR-05 fixed with regression tests; IN-01 (throttle never evicts idle addresses), IN-02 (client-address helper duplicated), IN-03 (cancel sweep decides on files without a re-read) remain `open` as info-level, recorded in `02-REVIEW-DISPOSITION.md`. None blocks a must-have.

### Human Verification Required

None. The three earlier items are satisfied by `02-UAT.md` (status complete, 3/3 passed): real-phone cancel and audit check, iOS/Android visual backstops, and the review decision (resolved by the fixes).

### Gaps Summary

No gaps. All four roadmap truths hold in code and tests, WR-01..WR-05 are fixed and the real-engine run confirms the `completion_on` assumption the WR-01 guard depends on. Open items are IN-01..IN-03 (info). One limit worth knowing, not a gap: on the WSL2 dev host audit lines show the Docker gateway address (documented household-wide caveat).

---

_Verified: 2026-10-23_
_Verifier: Claude (gsd-verifier)_
