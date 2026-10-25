---
phase: 01-portal-search-start-download
verified: 2026-10-25T12:30:00Z
status: passed
score: 9/9 must-haves verified
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
covered_digest: "v3:sha256:097d826e9925551667eca3eb57afeb58ce5686e27b6c20c8d623637625f02628"
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: human_needed
  previous_score: 8/9
  gaps_closed:
    - "Previous behavior-unverified item G1 (real-engine proof of stopCondition=MetadataReceived on a magnet-printing plugin route): the real-engine guard was run by the owner and recorded as pass in 01-UAT.md test 3 (4 passed, 0 skipped); the Phase 2 verification also records 7 passed against qBittorrent 5.2.4 with the same test file. Not re-run by me (instructed not to)."
    - "Previous human items (UAT 3 phone re-tests, both routes): recorded pass in 01-UAT.md tests 1 and 2."
    - "Review warning WR-01 (largest video ignored non-allowlisted formats): fixed in code by Phase 2.x decision D-43; re-checked by running decide()."
  gaps_remaining: []
  regressions: []
---

# Phase 1: Portal Search & Start Download Verification Report

**Phase Goal:** A household member can log in to the portal from her phone, search for a film or series, and start a download that lands in the correct predefined folder, without ever seeing qBittorrent, save paths or credentials.
**Verified:** 2026-10-25T12:30:00Z
**Status:** passed
**Re-verification:** Yes. The earlier report (2026-10-22) went stale because Phases 2 and 2.1 changed ten files this phase covers. This report re-checks every must-have against today's code and tests.

Every phase-1 must-have still holds on today's code. One landing-path change is intentional (see "Intentional evolution"). No gaps, no regressions, no blockers.

## Intentional evolution (not a gap)

Phase 2.1 (QUAR-01..05, D-44, D-45) moved the landing of a finished download. In Phase 1 the file was saved straight into `/media/Film` or `/media/SerieTV`. Now qBittorrent saves into `/data/quarantine/Film` or `/data/quarantine/SerieTV` (`SAVE_PATH_FILM`, `SAVE_PATH_TV` in `.env.example` and `backend/app/config.py:78-79`), an ffprobe check runs in a microVM, and only a passing file is hardlinked into `/data/media/<Category>`. `Settings._check_quarantine_layout` makes the backend refuse to start if a save path sits outside the quarantine folder. This is a safer strengthening of Phase 1's intent, not a contradiction: the user still sees no path or category, the type still picks the folder, and the file still ends in the Film or SerieTV media folder of the chosen type. The roadmap text "once complete, the file is in the Film or SerieTV host folder" is read as "after the safety check".

## Goal Achievement

### Observable Truths (roadmap Success Criteria SC1-SC6, plus the gap-closure truths G1-G3)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| SC1 | Login required; search and download pages and endpoints unreachable without it | VERIFIED | `routers/search.py:24`, `routers/download.py:21`, `routers/downloads.py:29` all build on `protected_router()`; only `/api/health` and `POST /api/login` are public (`routers/health.py`, `routers/auth.py`). `App.jsx:58` gates the shell on `/api/session`; `clearSavedSearch()` runs on logout (`App.jsx:27`). The login limiter is now the shared `SlidingWindowThrottle` (`auth.py` aliases `LoginThrottle` to it); its tests pass in the backend suite. |
| SC2 | Movie/TV toggle, keyword, first results in about 2 s with name, size, seeders, leechers, source, sorted by seeders; timeout shows a plain message | VERIFIED | `POST /api/search` takes `type: ContentType` with `extra="forbid", strict=True` (`routers/search.py:35-38`); `search/service.py` maps type to plugin category `movies`/`tv`. Search polling and rows covered by 271 frontend tests and the backend search tests (all pass). Timing was confirmed on a phone in UAT 4 (earlier round). |
| SC3 | Tapping Download starts it in qBittorrent; the file ends in the Film or SerieTV folder of the chosen type; no path or category shown or chosen by the user | VERIFIED (landing path evolved, see above) | `DownloadRequest` allows only `result_id` and `type` (`extra="forbid"`, strict; `routers/download.py:30-36`). `pipeline.py:212-217` calls `add_torrent(url, qbit_category(settings, job.type), tags, downloader=...)`: the category comes only from the fixed server map in `content_type.py`. `add_torrent` sends `autoTMM=true` so the category's save path applies. `client.py` has no method that changes a torrent's category. Phone tap on both routes recorded pass in `01-UAT.md` tests 1-2. |
| SC4 | qBittorrent not LAN-reachable; credentials and paths in no browser response; one `docker compose up`; repo holds no secrets or LAN IPs | VERIFIED | `docker-compose.yml` has exactly one `ports:` entry (the `web` service, port 80); the qBittorrent service has none. `docker-compose.admin.yml` publishes `127.0.0.1:8088:8088` only (loopback). Fresh build of the frontend (`npm --prefix frontend run build`): 0 matches of `qbittorrent`, `savePath`, `save_path` in `dist/assets/*.js`. `frontend/src` (non-test) has no such strings. Infra tests (98) enforce compose and repo hygiene and pass. Docker was not run, per instruction. |
| SC5 | One documented port map and media contract; no port collisions | VERIFIED | `docs/ports-and-media.md` present; compose invariants and port-map tests pass (98 infra tests). The media contract now documents the single `/data` bind with quarantine, media, rejected and incomplete subfolders (separate incomplete folder kept: `INCOMPLETE_PATH=/data/incomplete`, guarded by config validation). |
| SC6 | No allowed video means rejected before any data is downloaded with a plain message; in an accepted torrent every non-video, non-subtitle file gets priority 0 | VERIFIED | `qbit/client.py` always sends `stopCondition=MetadataReceived` (never a stopped add). `pipeline._process` order: wait for files, `decide()`, `_discard` on reject, set priority 0 on `zero_ids` and 1 on `keep_ids`, re-read and compare, `start` last (`pipeline.py:286-311`). `EXCLUDED_FILE_PATTERNS` covers the 11 FILT-01 entries first, plus 7 more. Ran `decide()` directly: `a.mkv + a.srt + x.exe` gives accept, keep (0,1), zero (2); `a.mkv.exe` gives reject `no_video`; lone `.webm` gives reject `video_format`. |
| G1 | Every add carries `stopCondition=MetadataReceived`, never `stopped`; a plugin result whose downloader prints a magnet fetches metadata and starts | VERIFIED | `client.py:296` sends the condition; `add_torrent(self, url, category, tags, downloader=None)` has no stop flag; `pipeline.py:212` is the single add call. Tracer, four-route zero-payload and "never sends stopped" tests pass in the backend suite. The engine half (real qBittorrent behaves as the fake models) rests on the owner-run real-engine guard recorded as pass in `01-UAT.md` test 3 (4 passed, 0 skipped) and on the Phase 2 verification's 7 passed against 5.2.4. I did not run it (instructed not to, docker excluded). |
| G2 | A torrent whose only videos are outside the allowlist is deleted, never started, and says "This video format isn’t supported. Try another result."; a torrent with no video keeps the D-13 text | VERIFIED | `decide()` returns `reason='video_format'` for a lone `.webm`; `pipeline.py:294-298` maps it to `JobState.UNSUPPORTED` after `_discard`. `ResultRow.jsx:20` maps `unsupported` to `MSG.unsupportedFormat` with `retry:false`; `messages.js:29` holds the text. The fresh bundle contains "isn’t supported". Phone check recorded pass (`01-UAT.md` test 2). |
| G3 | A reload during Preparing restores rows, query, type and resumes job polling; cleared by a new search and logout | VERIFIED | `Search.jsx` persists to `sessionStorage` (bundle contains it), resumes `pollJob` with the saved `startedAt`, turns a 404 into `lost` (`Search.jsx:281-285`) and gives up after the cap; `App.jsx:27` calls `clearSavedSearch()` on logout. Reload, tamper, expiry and logout tests pass (271/271). Phone reload check recorded pass (`01-UAT.md` test 1). |

**Score:** 9/9 truths verified, 0 present-but-behavior-unverified.

### Required Artifacts (files changed by later phases)

| Artifact | Status | Details |
|----------|--------|---------|
| `backend/app/qbit/client.py` | VERIFIED | Single add form, `stopCondition=MetadataReceived`, `autoTMM=true`, category passed in, no category-change method. |
| `backend/app/download/pipeline.py` | VERIFIED | Allowlist before start, priority re-read check, UNSUPPORTED/REJECTED mapping; Phase 2/2.1 additions (cancel, quarantine-aware discard, outcomes) sit around, not inside, the phase-1 ordering. |
| `backend/app/download/allowlist.py` | VERIFIED | `VIDEO_EXTENSIONS` still exactly `.mkv .mp4 .avi .m4v`; subtitles unchanged; main-video sizing now spans allowed and other video formats (D-43). |
| `backend/app/download/jobs.py` | VERIFIED | `UNSUPPORTED` state present; used by pipeline and frontend. |
| `backend/tests/fakeqbit.py` | VERIFIED | Backs 988 passing backend tests. |
| `backend/tests/integration/test_real_qbit.py` | VERIFIED (existence) | 4 tests in the file collected (7 integration tests in the folder). Not run by me. |
| `frontend/src/{App,Search,ResultRow,messages}` | VERIFIED | Wired, substantive, present in a fresh build. |

### Key Link Verification

| From | To | Via | Status |
|------|----|-----|--------|
| `routers/download.py` | `pipeline.submit` | `body.result_id, body.type` only | WIRED |
| `pipeline._run` | `qbit/client.add_torrent` | `qbit_category(settings, job.type)` from the server map, no stop argument | WIRED |
| `client.add_torrent` | qBittorrent `/torrents/add` | form field `stopCondition=MetadataReceived`, `autoTMM=true` | WIRED |
| `pipeline._process` | `allowlist.decide` | reject -> `_discard`; `video_format` -> `UNSUPPORTED` | WIRED |
| `Search.jsx` | `ResultRow.jsx` | `unsupported` job state and message map | WIRED |
| `App.jsx` logout | `Search.jsx` | `clearSavedSearch()` | WIRED |
| `Settings` | save paths | `_check_quarantine_layout` rejects a save path outside quarantine | WIRED |

### Data-Flow Trace (Level 4)

| Artifact | Data | Source | Real data | Status |
|----------|------|--------|-----------|--------|
| `ResultRow.jsx` unsupported text | job status | `GET /api/download/{job_id}` returns `job.state.value` set by `_process` | Yes | FLOWING |
| `Search.jsx` restored rows | saved record | `sessionStorage` written from API snapshots, whitelisted on write and read | Yes | FLOWING |
| Add call category | `job.type` | validated `type` field, mapped by `qbit_category` | Yes | FLOWING |

### Behavioral Spot-Checks and Test Runs

| Check | Command | Result | Status |
|-------|---------|--------|--------|
| Backend suite | `uv run --project backend --frozen pytest backend/tests -q` | 988 passed, 19 deselected (integration) | PASS |
| Infra suite | `uv run --project backend --frozen pytest infra/tests -q` | 98 passed | PASS |
| Frontend suite | `npm --prefix frontend test` | 271 passed (8 files) | PASS |
| Frontend build leak scan | `npm --prefix frontend run build`, then grep `dist/assets/*.js` | 0 `qbittorrent`/`savePath`/`save_path`; has "isn’t supported" and `sessionStorage` | PASS |
| `decide()` accept/reject cases | direct call (mkv+srt+exe; mkv.exe; webm; 20 GB m2ts + 100 MB mp4) | accept (0,1) zero (2); no_video; video_format; video_format | PASS |
| Debt markers | grep `TBD\|FIXME\|XXX` in `backend/app frontend/src web docker-compose.yml` | none | PASS |
| Real-engine guard | not run (excluded by instruction) | recorded pass in `01-UAT.md` test 3 and Phase 2 verification | NOT RE-RUN |

Probe execution: none declared by this phase (skipped).

### Requirements Coverage

All 18 phase IDs (AUTH-01, SEC-01..04, SRCH-01..03, DOWN-01..03, PUI-01, PUI-02, INFRA-01, INFRA-02, MEDIA-01, FILT-01, FILT-02) appear in the union of the 16 PLAN `requirements:` fields and are marked Complete for Phase 1 in REQUIREMENTS.md. No orphaned requirement: REQUIREMENTS.md maps no other ID to Phase 1.

| Requirement | Status | Evidence |
|-------------|--------|----------|
| AUTH-01 | SATISFIED | SC1: `protected_router()` on all feature routers; `/api/session` gate in `App.jsx`. |
| SEC-01 | SATISFIED | Credentials only in backend env and client; fresh bundle has 0 `qbittorrent` strings. |
| SEC-02 | SATISFIED | One published port (web:80); admin override binds `127.0.0.1:8088` only. |
| SEC-03 | SATISFIED | Strict `Literal` type, `extra="forbid"`; category and path from the server map only. |
| SEC-04 | SATISFIED | `.env.example` holds placeholders (`change-me-...`); infra hygiene tests pass. Config comes from env. |
| SRCH-01, SRCH-02, SRCH-03 | SATISFIED | SC2; search tests and frontend tests pass; timing passed on a phone in UAT 4. |
| DOWN-01 | SATISFIED | SC3, G1, G3; phone tap recorded pass. |
| DOWN-02 | SATISFIED | `qbit_category()` maps `film` to Film and `serie` to SerieTV, server side. |
| DOWN-03 | SATISFIED (evolved) | Categories created at startup and `repair_drift` before each add; "append category name" stays off; the save path now sits under the quarantine folder (D-44/D-45), the checked file reaches `/media/<Category>`. |
| PUI-01 | SATISFIED | Phone layout passed in UAT 1; no layout regression from later phases (frontend tests green). |
| PUI-02 | SATISFIED | No path, category, hash or credential in the bundle; saved search holds only whitelisted API row fields. |
| INFRA-01 | SATISFIED | `/api/health` route present; compose has qbittorrent, backend, web (plus Phase 2.1 sandbox); compose tests pass. |
| INFRA-02 | SATISFIED | `docs/ports-and-media.md` and port-map tests; no host port collisions in compose. |
| MEDIA-01 | SATISFIED (evolved) | One `DATA_ROOT` bind, separate `INCOMPLETE_PATH`; config guard keeps incomplete outside quarantine, media and rejected folders. |
| FILT-01 | SATISFIED | `EXCLUDED_FILE_PATTERNS` begins with the 11 required entries; sent at bootstrap and re-checked by `repair_drift`. |
| FILT-02 | SATISFIED | SC6, G1, G2. |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `backend/app/download/pipeline.py` | 299-311 | No runtime check of `downloaded == 0` before `start` (earlier review WR-02) | Warning (carried, not a blocker) | The "no payload before the allowlist" guarantee relies on engine behaviour. Mitigations: qBittorrent image pinned to 5.2.4, the opt-in real-engine guard (passed in UAT), the allowlist deleting rejected torrents with files, and Phase 2.1 quarantine as a second layer. |
| `frontend/src/Search.jsx` | 244-247, 374-376 | Stale saved search not marked done on a missing search (earlier review WR-03) | Warning (carried, not a blocker) | Cosmetic repeated error after a backend restart or TTL expiry; the Download path still ends in the existing `expired` message. Open in `01-REVIEW-DISPOSITION.md`. |
| `frontend/src/Search.jsx` | 70 | `ID.test` coerces non-strings (IN-01) | Info | Self-inflicted only. |
| `backend/app/download/allowlist.py` | 19-34 | `.ts` in `OTHER_VIDEO_EXTENSIONS` (IN-02) | Info | Wording and sizing only. |

Earlier warning WR-01 (a 20 GB `.m2ts` plus a 100 MB `.mp4` started only the trailer) is fixed: today `decide()` rejects that torrent with `video_format`. No TBD, FIXME or XXX markers. No stubs or hollow wiring found in the covered files.

### Human Verification Required

None. The items the earlier report listed were completed by the owner and recorded in `01-UAT.md` (status complete, 3 passed, 0 issues, 1 skipped).

Informational, not blocking: UAT test 4 (two-phone lockout check) was deliberately skipped ("defer") because it needs real client addresses on the Ubuntu production server. It is tracked in `.planning/STATE.md` (Phase 2 note) and `docs/setup.md` ("Login lockout"). It does not gate the Phase 1 goal.

### Gaps Summary

No gaps. The phase goal holds on today's code: login-gated access, search by type, a one-tap download whose category and folder are chosen only on the server, an allowlist that runs before any payload, and no qBittorrent name, path or credential reaching the browser. The only difference from the original phase is the intentional quarantine step before the media folder. Remaining items are two carried review warnings (WR-02 hardening, WR-03 cosmetic) and the deferred production lockout check.

---

_Verified: 2026-10-25T12:30:00Z_
_Verifier: Claude (gsd-verifier)_
