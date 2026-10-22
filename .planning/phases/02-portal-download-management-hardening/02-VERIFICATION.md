---
phase: 02-portal-download-management-hardening
verified: 2026-10-22T21:30:00Z
status: human_needed
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
covered_digest: "v3:sha256:0fd268e09e0318c44f890fb3da333aa29a13fdf7865704a2c7bbd77a11c44dc6"
behavior_unverified: 0
overrides_applied: 0
human_verification:
  - test: "Phone check, plan 02-11 Task 2 steps 1-8: follow a download with progress and time left, cancel one and confirm it is gone in qBittorrent, outage banner clears by itself, plain reload picks up a redeploy, rate-limit message, audit lines carry the phone address and no password"
    expected: "Each step behaves as the plan describes on a real phone on the LAN"
    why_human: "Needs a real phone and the running stack; the executor could not run it and no result was invented. On the WSL2 dev host audit lines show the Docker gateway address (documented household-wide caveat)"
  - test: "Visual backstops on iOS Safari and Android Chrome: 320 px layout, 200-character name does not break the row, progress bar colours and Preparing animation, 48 px buttons, side-by-side confirm buttons at 320 px, focus ring and tap feel"
    expected: "Layout holds at 320 px, bars and animation render, buttons are comfortably tappable"
    why_human: "Visual and touch behavior on real browsers cannot be checked with grep or jsdom"
  - test: "Decision on code-review WR-01 / WR-02 / WR-03 (see Gaps Summary): fix before shipping, or accept and record as deferred"
    expected: "A recorded disposition for each (currently all six review findings are still 'open' in 02-REVIEW-DISPOSITION.md)"
    why_human: "These weaken the 'never delete a finished film' contract (D-33) in edge cases and strand a cancelled torrent after a failed sweep. A developer decision on severity is needed"
---

# Phase 2: Portal Download Management & Hardening Verification Report

**Phase Goal:** The user can follow and cancel her downloads from the phone, and the portal degrades gracefully, throttles abuse and keeps audit logs.
**Verified:** 2026-10-22
**Status:** human_needed
**Re-verification:** No, initial verification

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | The user sees a list of Film and SerieTV downloads, in progress and completed, with state and progress refreshing about every 5 s | VERIFIED | `GET /api/downloads` (`routers/downloads.py`) reads `torrents_info()` and returns `build_items` (`download/listing.py`): Film/SerieTV only via `type_for_category`, plain state, integer progress, ETA, 7-day completed window, young failed attempts, torrent-less Preparing jobs. `frontend/src/Downloads.jsx` has `POLL_MS = 5000`, a 5 s timer rescheduled after each answer, paused when the page is hidden, immediate poll on visibility; Search / Downloads tabs in `App.jsx`. `DownloadRow.jsx` renders state, `<progress>`, ETA. Backend and frontend tests for these pass. |
| 2 | The user can cancel a download from the list and it disappears from qBittorrent | VERIFIED | `DELETE /api/downloads/{id}` takes only an opaque 16-hex id; `DownloadPipeline.cancel` re-reads the torrent, re-checks category, stops the job, then `torrents/delete` (files only when `cancel_deletes_files`). Frontend: two-step confirm, `act()` sends one DELETE, removes the row, handles 404/502/401. Real-engine integration (`test_real_downloads.py`) reported 7 passed against qBittorrent 5.2.4 (not re-run by me, needs a live engine). Edge-case weaknesses: see WR-01/02/03 below. |
| 3 | qBittorrent down, invalid torrent or wrong category path give plain messages (auto retry when unreachable), never a raw error | VERIFIED | 415 on add -> `JobState.UNAVAILABLE` ("Not available. Try another result."); 409 on add -> duplicate; refused category path -> job FAILED, only class and HTTP status logged (`pipeline.py`, tests `test_an_invalid_torrent_answered_415_is_unavailable`, `test_a_category_path_refused_with_409_...`). List route answers 502 with fixed codes `qbit_unreachable` / `qbit_refused` (never 401, so no false logout); `Downloads.jsx` shows "Can't reach the download service. Retrying..." and keeps polling every 5 s, so the retry is automatic; credential refusal shows only the generic "Ask the admin" message and is logged by class name. Search 503 -> plain message. All copy in `messages.js`. |
| 4 | Rapid repeated search or download requests are throttled, and logs record logins, searches, downloads, cancels and errors without credentials | VERIFIED | `SlidingWindowThrottle` (one generic limiter) wired in `main.py` for search (10/min) and download (20/min), per address, slot taken only after session/readiness/body checks; 429 `too_many_requests` with `Retry-After`; frontend maps 429 to a retryable "Too many requests" message. `audit.py` emits `event=login/logout/search/throttled/download/download_done/cancel|remove/error`; helpers take typed scalars only (no request/header/cookie), free text JSON-escaped and cut to 200 chars; failed-login username never logged. `RedactingFilter` installed on root and uvicorn handlers via `configure_logging` with SECRET_KEY, QBITTORRENT_PASS, APP_PASS_HASH. `docker-compose.yml` json-file rotation (10m x 5) on all services. `test_no_leaks.py`, `test_audit.py`, `test_rate_limit.py` pass. Summary reports no secret in `docker compose logs backend`. |

**Score:** 4/4 truths verified (WR-01..03 weaken the cancel contract in edge cases; see below)

### Required Artifacts

`verify.artifacts` on all 11 plans: every declared artifact exists and is substantive (6/6, 4/4, 4/4, 3/3, 4/4, 6/6, 5/5, 2/2, 3/3, 2/2, 3/3).

### Key Link Verification

`verify.key-links`: all verified except three links the tool could not evaluate because the plan wrote a non-file in the `from` field or a non-string pattern (02-03 compose `x-logging` anchor, 02-07 `build_items` -> `cancel_deletes_files`, 02-08 `Search.jsx` -> `messages.js`). I checked all three by hand: `x-logging: &default-logging` is applied with `logging: *default-logging` on every service; `build_items` sets `"action": "cancel" if cancel_deletes_files(row) else "remove"`; `Search.jsx` uses `MSG.throttled` on 429 and `ResultRow.jsx` maps `throttled` and `cancelled` states to messages. None is a real break.

### Data-Flow Trace (Level 4)

| Artifact | Data | Source | Real data | Status |
|----------|------|--------|-----------|--------|
| `Downloads.jsx` items | `/api/downloads` | `qbit.torrents_info()` + job registry -> `build_items` | Yes (real-engine test pins the raw field types) | FLOWING |
| `DownloadRow.jsx` bar/ETA | `item.progress`, `item.eta_seconds` | `percent()` / `eta_of()` over the live row | Yes | FLOWING |
| Cancel action | `item.action` | `cancel_deletes_files(row)`, same function DELETE uses | Yes | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Backend + infra suites | `uv run --project backend --frozen pytest backend/tests infra/tests -q` | 699 passed, 7 deselected (integration) | PASS |
| Frontend suite | `npm --prefix frontend test` | 241 passed | PASS |
| Frontend build | `npm --prefix frontend run build` | built OK | PASS |
| Cancel guard on a checking finished film (WR-01 probe) | `cancel_deletes_files({'state':'checkingResumeData','progress':0,'completion_on':<past>})` | `True` (would delete files) | Confirms the guard has no completion check; whether qBittorrent really reports such a row is unproven |
| Normal states | `stalledUP`/progress 1 -> False; `downloading`/0.999 -> True | as designed | PASS |
| Real-engine integration | needs `QBIT_TEST_URL` and a live qBittorrent | not re-run; summary claims 7 passed | SKIP (claimed, not independently verified) |

### Probe Execution

No `scripts/*/tests/probe-*.sh` exist and no plan declares one. `scripts/smoke.py` is the phase probe; it needs the running stack and was not re-run here (summary claims `all`, `cache`, `downloads` OK).

### Requirements Coverage

| Requirement | Source Plans | Description | Status | Evidence |
|-------------|--------------|-------------|--------|----------|
| DOWN-04 | 02-01, 02-04, 02-06, 02-11 | List Film/SerieTV downloads with state and progress, ~5 s refresh | SATISFIED | Truth 1 |
| DOWN-05 | 02-07, 02-10, 02-11 | Cancel from the list, removed from qBittorrent | SATISFIED (with WR-01..03 caveats) | Truth 2 |
| DOWN-06 | 02-01, 02-02, 02-07, 02-08, 02-11 | Plain messages for 415, 502 with retry, 409, generic on 401 | SATISFIED | Truth 3 |
| SEC-05 | 02-05, 02-08 | Search and download rate limited with clear message | SATISFIED | Truth 4 |
| SEC-06 | 02-09, 02-03 | Audit logs, no credentials in any line | SATISFIED (WR-04 is defence-in-depth gap only) | Truth 4 |

All five IDs appear in plan frontmatter, in REQUIREMENTS.md (marked Complete, mapped to Phase 2) and in ROADMAP. No orphaned requirements.

### Anti-Patterns Found

No `TBD`/`FIXME`/`XXX` in any file the phase touched. No stub patterns found in the downloads list, row, route or pipeline code. Code review (`02-REVIEW.md`): 0 critical, 4 warnings, 2 info, all still `open` in `02-REVIEW-DISPOSITION.md`.

### Human Verification Required

1. **Phone check (02-11 Task 2, steps 1-8).** Test: follow a download, cancel one and confirm it is gone in qBittorrent, trigger and clear the outage banner, plain-reload after a redeploy, hit the rate limit, read the audit lines. Expected: as the plan describes. Why human: real phone and stack; not run, nothing invented.
2. **Visual and touch backstops on iOS Safari and Android Chrome.** Test: 320 px layout, a 200-character name, bar colours and the Preparing animation, 48 px buttons, side-by-side confirm at 320 px, focus ring. Expected: no overflow, readable, tappable. Why human: real-browser rendering.
3. **Disposition of WR-01 / WR-02 / WR-03.** Fix now or accept and record. Why human: severity call on a data-loss contract.

### Gaps Summary

No must-have truth fails, so there is no blocking gap. The three review warnings are real and relate to the contract "never delete a finished film" (D-33). I judge them WARNING, not BLOCKER. They need a developer decision.

- **WR-01 (confirmed in code, trigger unproven).** `cancel_deletes_files` (`listing.py`) decides only from `state in IN_PROGRESS_RAW_STATES` and `progress < 1`. That set includes `checkingResumeData`, `checkingDL`, `queuedDL`, `error`, `missingFiles`. I ran it: a row with `state=checkingResumeData, progress=0, completion_on=<past>` returns True, so the row gets `action="cancel"` and DELETE would send `deleteFiles=true`. I could not establish that qBittorrent really reports a finished film as progress 0 while resuming (the review also did not reproduce it, and the real-engine suite has no such case). Exposure is narrow: a film finished within the 7-day list window, caught in a restart or checking state, and a household member who taps through the confirm panel that says "partly downloaded files will be deleted". The review's fix (also require `completion_on <= 0`) is small and testable.
- **WR-02 (confirmed by reading).** `pipeline.cancel` computes `deletes` before `await registry.cancel_for(...)` and does not re-check before `_discard`. A torrent at 99.x% can finish in that await and still lose its files. A tiny window, but it is the exact case D-33 promises to protect. Fix: re-read the single torrent right before the delete.
- **WR-03 (confirmed by reading).** In `_cancel_job_without_torrent`, `await self._sweep_once(job_tag)` runs before `_start_sweep`. If qBittorrent errors at that moment the route answers 502, the job is already `CANCELLED` (a retry gets 404), the torrent is hidden from the list and nothing will delete it; a restart within `METADATA_TIMEOUT` would let `reconcile` start a download the household cancelled. Needs a qBittorrent failure at the cancel instant plus a Preparing tap whose torrent appeared between list and tap, so it is rare. The sibling `cancel()` path already does it correctly.
- **WR-04 (defence in depth, not a leak today).** `RedactingFilter` skips non-string `record.msg` and secrets under 8 characters; no current code path logs such a value. Does not break SEC-06 as shipped, but docs promise "never written", so either enforce a minimum `QBITTORRENT_PASS` length or soften the docs.
- IN-01 (throttle dict never evicts idle addresses) and IN-02 (client-address helper duplicated five times) are minor.

The phase goal is met in code and tests (699 backend/infra, 241 frontend, build OK). Remaining: the unrun real-phone checks and the disposition of WR-01..03. Recommended: fix WR-01, WR-02, WR-03 (small, localized, test-first) before relying on cancel with real films, then run the phone check.

---

_Verified: 2026-10-22_
_Verifier: Claude (gsd-verifier)_
