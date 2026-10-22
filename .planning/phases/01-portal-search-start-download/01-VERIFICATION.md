---
phase: 01-portal-search-start-download
verified: 2026-10-22T17:10:00Z
status: passed
score: 8/9 must-haves verified
covered_files:
  - .planning/phases/01-portal-search-start-download/01-01-PLAN.md
  - .planning/phases/01-portal-search-start-download/01-01-SUMMARY.md
  - .planning/phases/01-portal-search-start-download/01-02-PLAN.md
  - .planning/phases/01-portal-search-start-download/01-02-SUMMARY.md
  - .planning/phases/01-portal-search-start-download/01-03-PLAN.md
  - .planning/phases/01-portal-search-start-download/01-03-SUMMARY.md
  - .planning/phases/01-portal-search-start-download/01-04-PLAN.md
  - .planning/phases/01-portal-search-start-download/01-04-SUMMARY.md
  - .planning/phases/01-portal-search-start-download/01-05-PLAN.md
  - .planning/phases/01-portal-search-start-download/01-05-SUMMARY.md
  - .planning/phases/01-portal-search-start-download/01-06-PLAN.md
  - .planning/phases/01-portal-search-start-download/01-06-SUMMARY.md
  - .planning/phases/01-portal-search-start-download/01-07-PLAN.md
  - .planning/phases/01-portal-search-start-download/01-07-SUMMARY.md
  - .planning/phases/01-portal-search-start-download/01-08-PLAN.md
  - .planning/phases/01-portal-search-start-download/01-08-SUMMARY.md
  - .planning/phases/01-portal-search-start-download/01-09-PLAN.md
  - .planning/phases/01-portal-search-start-download/01-09-SUMMARY.md
  - .planning/phases/01-portal-search-start-download/01-10-PLAN.md
  - .planning/phases/01-portal-search-start-download/01-10-SUMMARY.md
  - .planning/phases/01-portal-search-start-download/01-11-PLAN.md
  - .planning/phases/01-portal-search-start-download/01-11-SUMMARY.md
  - .planning/phases/01-portal-search-start-download/01-12-PLAN.md
  - .planning/phases/01-portal-search-start-download/01-12-SUMMARY.md
  - .planning/phases/01-portal-search-start-download/01-13-PLAN.md
  - .planning/phases/01-portal-search-start-download/01-13-SUMMARY.md
  - .planning/phases/01-portal-search-start-download/01-14-PLAN.md
  - .planning/phases/01-portal-search-start-download/01-14-SUMMARY.md
  - .planning/phases/01-portal-search-start-download/01-15-PLAN.md
  - .planning/phases/01-portal-search-start-download/01-15-SUMMARY.md
  - .planning/phases/01-portal-search-start-download/01-16-PLAN.md
  - .planning/phases/01-portal-search-start-download/01-16-SUMMARY.md
  - backend/app/download/allowlist.py
  - backend/app/download/jobs.py
  - backend/app/download/pipeline.py
  - backend/app/qbit/client.py
  - backend/tests/fakeqbit.py
  - backend/tests/integration/test_real_qbit.py
  - frontend/src/App.jsx
  - frontend/src/ResultRow.jsx
  - frontend/src/Search.jsx
  - frontend/src/messages.js
covered_digest: "v3:sha256:e7d62013373d262b6a3970fad314287bb831c54b4aeab9fb57c9695b84aba4b9"
behavior_unverified: 1
overrides_applied: 0
re_verification:
  previous_status: human_needed
  previous_score: 5/6
  gaps_closed:
    - "G-01-3 (a): page-URL results whose downloader prints a magnet were added fully stopped and never fetched metadata"
    - "G-01-3 (b): a .webm-only torrent said 'doesn't contain a video'"
    - "G-01-3 (c): a reload during Preparing lost the rows and job ids"
  gaps_remaining: []
  regressions: []
behavior_unverified_items:
  - truth: "G-01-3 (a): on the real qBittorrent 5.2.4 a result whose plugin downloader prints a magnet (limetorrents, torrentproject) fetches metadata under stopCondition=MetadataReceived, is held at 0 payload bytes, and ends started; a metadata-complete torrent added with that condition is held paused by the engine itself"
    test: "With docker-compose.admin.yml up: QBIT_TEST_URL=http://127.0.0.1:8088 uv run --project backend --frozen pytest backend/tests/integration -m integration -q -rs. Needs the owner's OK (adds Blender open-movie torrents; the plugin test skips if no Blender result is found, so check for 0 skipped). Close port 8088 afterwards."
    expected: "4 passed, 0 skipped, including test_a_plugin_result_whose_downloader_prints_a_magnet_fetches_metadata_with_zero_payload"
    why_human: "The default suite runs on FakeQbit, which was written to model the claimed engine behaviour (01-REVIEW WR-02), so it cannot prove it. The 4/4 real-engine pass is reported by the 01-16 executor and the orchestrator. I did not re-run it myself because it adds live torrents and opens the admin port."
human_verification:
  - test: "UAT 3 phone re-test: tap Download on a limetorrents / torrentproject result (e.g. Tears of Steel)"
    expected: "Row shows Preparing, then 'Started ✓'. Reload the tab during Preparing: the same results and the Movie/TV Series choice come back, the row is still Preparing and then ends on Started. After completion the file is in the host Film folder. No path, category or qBittorrent name is visible."
    why_human: "Real phone, real swarm, real indexer. This is the exact scenario that failed in UAT."
  - test: "UAT 3 phone re-test: tap a .webm-only result (piratebay Tears of Steel 1080p webm)"
    expected: "Row says 'This video format isn’t supported. Try another result.', no Started or check mark, the button is disabled, nothing appears in qBittorrent, and a reload still shows the same message."
    why_human: "Depends on what the live indexers return; the logic is covered by automated tests."
  - test: "Re-run the real-engine guard (see behavior_unverified_items)"
    expected: "4 passed, 0 skipped"
    why_human: "Needs the owner's OK; see above."
  - test: "Two-phone lockout check on the Ubuntu production server (UAT 5, deferred)"
    expected: "5 wrong logins from phone A do not lock phone B out when the server sees real client addresses."
    why_human: "Cannot be tested on the WSL2 dev box where Docker Desktop hides client addresses. Documented in docs/setup.md. Not a Phase 1 blocker; carried as a deferred follow-up."
---

# Phase 1: Portal Search & Start Download Verification Report

**Phase Goal:** A household member can log in to the portal from her phone, search for a film or series, and start a download that lands in the correct predefined folder, without ever seeing qBittorrent, save paths or credentials.
**Verified:** 2026-10-22T17:10:00Z
**Status:** human_needed
**Re-verification:** Yes, after gap closure (plans 01-14, 01-15, 01-16 for UAT gap G-01-3). This report overwrites the earlier one.

G-01-3 is closed in the code and on the rebuilt stack. No regression, no new blocker. Status is `human_needed` because the UAT 3 phone re-test cannot be done from here, and because the real-engine proof for the new magnet-printing plugin route rests on reports, not on a run of mine.

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| SC1 | Login required; search and download pages and endpoints unreachable without it | VERIFIED (regression check) | Unchanged since the previous report. `App.jsx` still gates on `/api/session`. `backend/app/auth.py` untouched by 01-14..16. Backend + infra suite still green (route enumeration test included). |
| SC2 | Movie/TV toggle, keyword, first results about 2 s, sorted rows, plain timeout message | VERIFIED (timing passed in UAT 4) | `Search.jsx` toggle and polling intact; frontend 135 tests pass. UAT 4 recorded pass on a phone. |
| SC3 | Tapping Download starts it; file lands in Film or SerieTV; no path or category visible | VERIFIED in code (phone tap is a human item) | `pipeline.py` `qbit_category(settings, type)` unchanged; the add call at pipeline.py ~178 passes only the server-side category, three tags and `downloader`. Previous Sintel run still on disk under `data/media/Film`. UAT 3 re-test is the open item. |
| SC4 | qBittorrent not LAN-reachable; no credentials or paths in responses; one `docker compose up` | VERIFIED (live) | Just re-checked: `docker compose ps` shows only `0.0.0.0:80->80`; `ss -ltn` shows only `*:80`; served bundle has 0 `qbittorrent` and 0 `savePath` strings; `/api/health` returns `{"status":"ok","qbittorrent":"up"}`. |
| SC5 | One port map and media contract, no collisions | VERIFIED (regression check) | `docs/ports-and-media.md` and compose invariants tests pass (61 infra tests). |
| SC6 | No allowed video means rejected before any data; non-video and non-subtitle files get priority 0 | VERIFIED | `allowlist.decide()` and `_process` ordering read directly: metadata, decide, discard on reject, priorities set and re-read, start last. The video list is `{.mkv .mp4 .avi .m4v}`, unchanged and pinned by a test. Real-engine proof from the previous round's integration run (orchestrator addendum, 4 passed on 5.2.4), carried forward. |
| G1 | G-01-3 (a): a result whose downloader resolves to a magnet fetches metadata and starts; every add carries `stopCondition=MetadataReceived`, never `stopped` | PRESENT_BEHAVIOR_UNVERIFIED (engine half) | Verified by me: `client.py:296` sends `"stopCondition": "MetadataReceived"`; `add_torrent` signature is `(self, url, category, tags, downloader)`, no stop flag (read in the live backend container too); `grep stopped` finds no add parameter in `client.py` or `pipeline.py` (only the unrelated `NOT_STARTED_STATES` names); `pipeline.py` makes one `add_torrent` call for all routes. Tests for the tracer, four-route zero payload and "never sends stopped" pass (backend 386, run by me: 447 with infra). Not verified by me: that real qBittorrent behaves as the fake models. 4 integration tests are collected; the 4/4 pass is reported, not mine (see `behavior_unverified_items`). |
| G2 | G-01-3 (b): a torrent whose only videos are outside the allowlist is deleted, never started, and says "This video format isn’t supported. Try another result."; a torrent with no video keeps the D-13 text | VERIFIED | Ran `decide()` directly: a lone `.webm` returns `accept=False, reason='video_format'`. `pipeline.py:262-264` maps `video_format` to `JobState.UNSUPPORTED`, else `REJECTED`, after `_discard` (delete with files) and before any priority call or `start`. `jobs.py:30` has `UNSUPPORTED`. `ResultRow.jsx:19` maps it to `MSG.unsupportedFormat` with `retry:false`, `Search.jsx:17` lists it in the restorable states, `messages.js:29` holds the text. `VIDEO_EXTENSIONS` is still exactly `.mkv .mp4 .avi .m4v`. The live bundle contains "isn’t supported". Frontend tests (never-success, disabled button, reload restore) pass. |
| G3 | G-01-3 (c): a reload during Preparing restores rows, query, type and resumes job polling; cleared by a new search and logout; saved data is untrusted | VERIFIED | `Search.jsx` writes `flatflix.search` to `sessionStorage` (per tab), validates on restore, resumes `pollJob` with the saved `startedAt` (future or older than 330 s becomes `lost`), a module-level `generation` counter drops late writes after `clearSavedSearch()`. `App.jsx:20` calls `clearSavedSearch()` on logout, and `submit()` clears on a new search (Search.jsx:315). Reload, tamper, 330 s, throwing-storage and logout tests pass (frontend 135/135, run by me). The live bundle contains `sessionStorage`. |

**Score:** 8/9 truths verified (1 present, behavior-unverified, routed to human verification)

### Gap G-01-3 Closure

| Part | Root cause (from UAT) | Closed? | Evidence |
|------|------------------------|---------|----------|
| a | `stopped=not is_magnet` decided from the search URL; downloader-printed magnets inherited the stop and never got metadata | Yes in code, tests and rebuilt stack; engine confirmation is reported | No stop flag left anywhere; fake now models downloader-to-magnet; tracer test `test_a_page_result_whose_downloader_prints_a_magnet_fetches_metadata_and_starts` passes. Running backend image has the new signature. |
| b | One `rejected` status could not distinguish "no video" from "video format not accepted" | Yes | See G2. |
| c | Rows and job ids lived only in component state | Yes | See G3. |

### Weighing the code review warnings (01-REVIEW.md, 0 critical, 3 warnings)

None of the three blocks the phase goal. All three stay open in `01-REVIEW-DISPOSITION.md`. I would fix WR-01 before the household relies on the portal.

| Finding | Verdict | Reasoning |
|---------|---------|-----------|
| WR-01 `largest` ignores non-allowlisted videos | Real, confirmed by me, WARNING (not a blocker) | `decide()` on a 20 GB `Movie.m2ts` plus a 100 MB `Trailer.mp4` returns `accept=True, keep_ids=(1,)`. The row says "Started ✓" but only the trailer downloads. Safety holds: only an allowed file type is fetched, so FILT-02 and the SEC goals are intact. It is a content-quality defect that can mislead the user on exactly the format family G-01-3 (b) targeted (a `.webm` film that also ships a small `.mp4` extra). It does not contradict the phase goal wording, but it is the first thing I would fix: compute `largest` over `VIDEO_EXTENSIONS | OTHER_VIDEO_EXTENSIONS` as the review suggests, and add a test. |
| WR-02 zero-payload relies on engine behaviour; no runtime check of `downloaded` before `start` | Real, WARNING (not a blocker) | Valid: the fake is built to match the assumption, so its `downloaded == 0` assertions cannot catch an engine that behaves differently. That is why I did not count the engine half as VERIFIED (truth G1). The mitigation is a pinned qBittorrent image tag (compose uses `5.2.4`, confirmed in `docker compose ps`), the opt-in real-engine guard, and the allowlist still deleting a rejected torrent with its files. A cheap `downloaded > 0` check in `_process` before `start` is worthwhile hardening, and Phase 2.1 quarantine adds a second layer. |
| WR-03 expired saved search leaves a stale record and an error on every reload | Real, WARNING (not a blocker) | Cosmetic and only after a backend restart or TTL expiry; rows are still shown and a Download tap ends in the existing `expired` message. It does not touch the safety or goal path, but a non-technical user will see a repeated error. Small frontend fix (mark the record `done` on a 404). |

### Required Artifacts

| Artifact | Status | Details |
|----------|--------|---------|
| `backend/app/qbit/client.py` | VERIFIED | Always sends the stop condition; no stopped parameter. |
| `backend/app/download/pipeline.py` | VERIFIED | One add call; `video_format` mapped to `UNSUPPORTED`; data flows to real qBittorrent calls. |
| `backend/app/download/allowlist.py` | VERIFIED | `VIDEO_EXTENSIONS` unchanged; `OTHER_VIDEO_EXTENSIONS` used for wording only; see WR-01. |
| `backend/app/download/jobs.py` | VERIFIED | `UNSUPPORTED`, not in `ACTIVE_STATES` (confirmed in the review). |
| `backend/tests/fakeqbit.py` | VERIFIED (with caveat) | `downloader_magnets`, stop-condition semantics; fidelity rests on engine source reading (WR-02). |
| `backend/tests/integration/test_real_qbit.py` | VERIFIED | 4 tests collected. Not run by me. |
| `frontend/src/{Search,App,ResultRow,messages}` | VERIFIED | Wired, substantive, served in the live bundle. |
| `01-CONTEXT.md` D-13 amendment, D-23 re-affirmation, D-24 | VERIFIED | All three present (lines 39, 53, 56). |

### Key Link Verification

| From | To | Via | Status |
|------|----|-----|--------|
| pipeline | client | `add_torrent(url, category, tags, downloader=...)` with no stop argument | WIRED |
| client | qBittorrent `/torrents/add` | form field `stopCondition=MetadataReceived` | WIRED |
| pipeline `_process` | allowlist | `decision.reason == "video_format"` selects `UNSUPPORTED` | WIRED |
| Search.jsx | ResultRow.jsx | `unsupported` in the job states and `MESSAGE` map | WIRED |
| App.jsx logout | Search.jsx | `clearSavedSearch()` | WIRED |
| Search.jsx mount | `/api/download/{job_id}` | restored preparing jobs call `pollJob` with saved `startedAt` | WIRED |

### Data-Flow Trace (Level 4)

| Artifact | Data | Source | Real data | Status |
|----------|------|--------|-----------|--------|
| `Search.jsx` restored rows | saved record | sessionStorage written from API snapshots, whitelisted to 7 fields on write and read | Yes | FLOWING |
| `ResultRow.jsx` unsupported text | job status | `/api/download/{job_id}` returns `job.state.value` | Yes | FLOWING |

### Behavioral Spot-Checks and Test Runs

| Check | Command | Result | Status |
|-------|---------|--------|--------|
| Backend + infra | `uv run --project backend --frozen pytest backend/tests infra/tests -q` | 447 passed, 4 deselected (386 + 61, matches the orchestrator) | PASS |
| Frontend | `npm --prefix frontend test` | 135 passed (5 files) | PASS |
| Allowlist: `.webm` alone | `decide()` | `accept=False, reason='video_format'` | PASS |
| Allowlist: large `.m2ts` + small `.mp4` | `decide()` | `accept=True, keep=(1,)` | WARNING (WR-01) |
| Live backend signature | `docker compose exec backend python -c ...` | `add_torrent` params `[self,url,category,tags,downloader]`; `UNSUPPORTED == "unsupported"` | PASS |
| Live bundle | curl of `/assets/index-D0xfx9Od.js` | has `sessionStorage` and "isn’t supported"; 0 `qbittorrent`, 0 `savePath` | PASS |
| Stack and ports | `docker compose ps`, `ss -ltn`, `/api/health` | 3 services healthy; only `:80` listens; health ok | PASS |
| Integration tests exist | `pytest backend/tests/integration -m integration --collect-only` | 4 collected | PASS (existence only) |
| Real-engine guard run | not run by me | reported 4 passed by 01-16 executor and orchestrator | NOT RE-RUN |

Probe execution: none declared by the phase (skipped).

### Requirements Coverage

All 18 IDs (AUTH-01, SEC-01..04, SRCH-01..03, DOWN-01..03, PUI-01, PUI-02, INFRA-01, INFRA-02, MEDIA-01, FILT-01, FILT-02) appear in at least one PLAN `requirements:` field and are marked Complete for Phase 1 in REQUIREMENTS.md. No orphans. The gap plans declare FILT-02, DOWN-01, DOWN-03 (01-14), DOWN-01, PUI-01, PUI-02 (01-15), FILT-02, DOWN-01, PUI-02 (01-16).

| Requirement | Status | Evidence |
|-------------|--------|----------|
| AUTH-01, SEC-01..04, SRCH-01..03, DOWN-02, INFRA-01, INFRA-02, MEDIA-01, FILT-01 | SATISFIED | Unchanged by 01-14..16; suites green; live stack re-checked (SC4). |
| DOWN-01 | SATISFIED in code; phone re-test pending | G1, G3. |
| DOWN-03 | SATISFIED | Categories and `repair_drift` before every add are untouched; the single add form passes the server-side category. |
| PUI-01 | SATISFIED in code; phone layout passed in UAT 1 | Reload persistence adds no layout change. |
| PUI-02 | SATISFIED | Saved record holds only the 7 API row fields and ids; no credentials, URLs, hashes, paths or categories; bundle scan clean. |
| FILT-02 | SATISFIED in code and tests; engine half reported | G1, G2, SC6. |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `backend/app/download/allowlist.py` | 115-126 | `largest` computed over allowed videos only (WR-01) | Warning | A mixed-format torrent can start only a small extra. |
| `backend/app/download/pipeline.py` | 183-188 | No runtime `downloaded` check before `start` (WR-02) | Warning | Safety guarantee rests on engine behaviour. |
| `frontend/src/Search.jsx` | 244-247, 374-376 | Stale saved search not cleared on 404 (WR-03) | Warning | Repeated error after a backend restart. |
| `frontend/src/Search.jsx` | 70 | `ID.test` coerces non-strings (IN-01) | Info | Self-inflicted only. |
| `allowlist.py` | 19-34 | `.ts` in `OTHER_VIDEO_EXTENSIONS` (IN-02) | Info | Wording only. |
| `test_real_qbit.py` | 220 | Test name over 100 columns (IN-03) | Info | Style. |
| Previous report | n/a | Stale "Italian" wording in five frontend test titles; `APP_USER=famiglia` default | Info | Carried over; no user impact. |

No TBD, FIXME or XXX markers in `backend/app`, `frontend/src`, `web` or `docker-compose.yml`. No stub or hollow wiring found.

### Human Verification Required

See `human_verification` and `behavior_unverified_items` in the frontmatter.

1. UAT 3 phone re-test, route (a): limetorrents or torrentproject result, Preparing then Started, reload mid-Preparing, file lands in Film.
2. UAT 3 phone re-test, route (b): `.webm`-only result shows the format message and nothing starts.
3. Re-run the real-engine guard (needs the owner's OK), or accept the executor and orchestrator reports.
4. Deferred: two-phone lockout check on the Ubuntu production server (UAT 5).

### Gaps Summary

No gaps. G-01-3 parts a, b and c are implemented, tested and served by the rebuilt stack, and nothing regressed. The three review warnings are real but none blocks the phase goal. I recommend fixing WR-01 (small change, plus one test) before the household uses the portal.

---

_Verified: 2026-10-22T17:10:00Z_
_Verifier: Claude (gsd-verifier)_
