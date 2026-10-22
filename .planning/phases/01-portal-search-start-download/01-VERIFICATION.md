---
phase: 01-portal-search-start-download
verified: 2026-10-22T12:40:00Z
status: human_needed
score: 5/6 must-haves verified
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
  - backend/Dockerfile
  - backend/app/auth.py
  - backend/app/download/pipeline.py
  - backend/app/proxy.py
  - backend/app/qbit/bootstrap.py
  - backend/app/search/filters.py
  - docker-compose.yml
  - frontend/src/ResultRow.jsx
  - frontend/src/Search.jsx
  - frontend/src/messages.js
  - web/Caddyfile
covered_digest: "v3:sha256:b8e8550a87cc6325f489e285f85a8d7630c0573350d51ac624f8ee4d29f08a45"
behavior_unverified: 1
overrides_applied: 0
behavior_unverified_items:
  - truth: "A torrent whose file list has no allowed video file is rejected before any data is downloaded (SC6): qBittorrent must really hold a magnet or .torrent at 0 payload bytes until the pipeline calls start"
    test: "With the admin override up (docker-compose.admin.yml) run QBIT_TEST_URL=http://127.0.0.1:8088 uv run --project backend --frozen pytest backend/tests/integration -m integration (4 tests: Sintel magnet asserts downloaded == 0 before start; two synthetic .torrent tests). Needs the owner's OK: it adds torrents to the live qBittorrent, and the magnet test fetches metadata from the swarm."
    expected: "All 4 pass; evidence[0] == 0 bytes before torrents/start; a metadata-complete .torrent added stopped stays at 0 bytes and reaches stoppedDL."
    why_human: "Real-engine behaviour is the only proof that qBittorrent honours stopCondition/stopped. The default suite uses FakeQbit, which models that behaviour but cannot prove it. I was told not to start downloads, so I did not run these; the 01-REVIEW-FIX.md claim that they passed is a report, not my evidence."
human_verification:
  - test: "Phone, 360 px layout (PUI-01, SC1/SC2)"
    expected: "On a real phone on the home Wi-Fi, open http://<laptop-ip>/. The English login screen appears first. After login the Movie / TV Series toggle, search box, and result rows fit with no sideways scroll, and buttons are easy to tap (48 px targets are in the CSS; usability is not machine-checkable)."
    why_human: "Real device layout and touch ergonomics."
  - test: "LAN reachability through the Windows firewall (SC1, SC4)"
    expected: "From the phone (not the laptop) http://<laptop-ip>/ loads the portal; http://<laptop-ip>:8088/ and :8000 do NOT answer."
    why_human: "Needs a second device and the Windows/Docker Desktop firewall; I could only see that the host listens on :80 alone."
  - test: "Tap Download on the phone and watch it land (SC3, DOWN-01..03)"
    expected: "Search an open-licensed title (e.g. Sintel, Blender), tap Download. The row shows Preparing then 'Started ✓'. After completion the file sits under the host Film folder (SerieTV for a series). No path, category or qBittorrent name appears anywhere on screen."
    why_human: "Real tap on a real phone with a real swarm. I was told not to start downloads or burn login attempts."
  - test: "First results within about 2 seconds (SRCH-03)"
    expected: "On the household network, first rows appear roughly 2 s after tapping Search."
    why_human: "Timing depends on the live indexers. The recorded smoke search showed rows after 717 ms (01-07 SUMMARY), but I did not log in to repeat it."
  - test: "Lockout behaviour with real client addresses (WR-07, docs/setup.md check)"
    expected: "Fail 5 logins from one phone; a second phone can still log in. If both phones count as one address (Docker Desktop/WSL2 userland proxy hides client IPs), one person's 5 wrong tries lock everyone for 15 min; this is documented in docs/setup.md."
    why_human: "Needs two devices; shows whether Caddy sees real client addresses on this host and on the Ubuntu box."
---

# Phase 1: Portal Search & Start Download Verification Report

**Phase Goal:** A household member can log in to the portal from her phone, search for a film or series, and start a download that lands in the correct predefined folder, without ever seeing qBittorrent, save paths or credentials.
**Verified:** 2026-10-22
**Status:** human_needed
**Re-verification:** No, initial verification

The code, stack and fixes are in place and working. No gaps were found. The status is `human_needed` because the real phone checks cannot be done from here, and because one engine-level invariant is only proven by an opt-in test that I did not run.

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | From a phone on the LAN, the portal asks for login and search/download pages and endpoints are unreachable without it | VERIFIED | Live, no login used: `GET /api/session`, `/api/search/abc`, `/api/download/abc` return 401; `POST /api/search`, `/api/download`, `/api/logout` return 401; `/api/docs` and `/api/openapi.json` return 404 (`/openapi.json` returns the SPA index.html, not a schema). `backend/app/auth.py` `protected_router()` puts `require_user` on every feature router. Only `POST /api/login` and `GET /api/health` are public. Route-enumeration test is in the 431 passing tests. The SPA starts on `/api/session` and falls back to Login. |
| 2 | Movie/TV toggle, keyword, first results about 2 s, name/size/seeders/leechers/source sorted by seeders, timeout shows a plain message | VERIFIED (timing on a real phone is a human item) | `Search.jsx` toggle + 700 ms polling of `/api/search/{id}`; `service.py` returns partial rows while qBittorrent is Running; `normalize_and_filter` sorts `(-seeders, -leechers, ...)`; `result_row()` whitelists the 7 fields; a timeout ends with `timed_out` and the UI shows `searchTimedOut` ("The search took too long. Try again."), not an error. Recorded smoke: rows after 717 ms (01-07 SUMMARY). Frontend tests 104/104. |
| 3 | Tapping Download starts it in qBittorrent; once complete the file is in the Film or SerieTV host folder for the chosen type; no path or category shown or chosen | VERIFIED (phone tap is a human item) | `POST /api/download` takes only `{result_id, type}` (`extra=forbid`, `strict`). The category comes from `qbit_category(settings, type)` and nowhere else, and the client has no re-categorize method. On disk: `data/media/Film/<Sintel...>/classicalhd-sintel.2010.en-1080p.mkv`, 576,700,012 bytes. `doctor --torrents` shows it with tag `fx`, category Film, save `/media/Film`, incomplete `/incomplete/Film`, state `stalledUP`, 100%. The SerieTV folder exists and is empty (no series download was made). `doctor`: Film -> /media/Film and SerieTV -> /media/SerieTV, auto TMM on. |
| 4 | qBittorrent not LAN-reachable; credentials and paths in no browser response; one `docker compose up` from `.env` built from `.env.example`; no secrets or LAN IPs in the repo | VERIFIED | `docker inspect` shows empty PortBindings for backend and qbittorrent; `ss -ltn` shows only `*:80`; `curl` to 127.0.0.1:8088 and :8000 fails. The `.env.example` carries only `change-me` placeholders; `.env`, `.dev-portal-password`, `data/` and `qbittorrent/config/` are gitignored and untracked (`git check-ignore` confirmed). `git grep` finds no private-IP literals outside the hygiene test. The served bundle has no `qbittorrent`, `/media/`, `SerieTV`, `savePath` or `category` strings. `docker compose config -q` is valid. `settings` rejects `change-me` values. 59 infra tests pass. |
| 5 | One documented port map and media-folder contract exist; no port collisions | VERIFIED | `docs/ports-and-media.md` holds the port map and the media contract (host paths, `PUID:PGID`, separate `/incomplete`). Compose publishes only `web` `${WEB_PORT:-80}`; qBittorrent WebUI is 8088, so the 8080 clash is resolved. The loopback-only admin override is `127.0.0.1:8088`. `scripts/init-host-dirs.sh` creates the folders with the owner, and compose uses `create_host_path: false`. Invariants enforced by `infra/tests/test_compose_invariants.py`. |
| 6 | A torrent with no allowed video is rejected before any data is downloaded, with a plain message; in an accepted torrent every non-video, non-subtitle file gets priority 0 and nothing else downloads | PRESENT_BEHAVIOR_UNVERIFIED (engine half) | Ordering and logic are verified. Magnet: `stopCondition=MetadataReceived`. Non-magnet: added `stopped`. `decide()` splits keep/zero. A torrent with no video is `_discard`ed with files. Priorities are set and re-read, and any mismatch deletes the torrent. Only then `start`. Exclusion list of 18 patterns is live (`doctor`: 18/18 present). Pipeline tests assert `downloaded == 0` before start on the fake. UI message: "This file doesn't contain a video. Try another result." Not proven by me: that real qBittorrent holds 0 bytes until `start`. The proof is the opt-in integration tests, which I did not run (see `behavior_unverified_items`). |

**Score:** 5/6 truths verified (1 present, behavior-unverified, routed to human verification)

### Code Review Fixes (01-REVIEW.md, 1 critical + 7 warnings)

Checked in the working tree. The running containers hold byte-identical copies of `proxy.py`, `pipeline.py`, `bootstrap.py`, `filters.py`, `auth.py` and `client.py`, and uvicorn runs with `--no-proxy-headers`.

| Finding | Holds? | Evidence |
|---------|--------|----------|
| CR-01 reconcile deleted running downloads | Yes | `pipeline.py` `_has_started()` (state not in `NOT_STARTED_STATES`, or downloaded/completed/progress > 0, or unreadable value counts as started). `reconcile()` deletes only `not started`; started goes back through `_process`. Tag cleanup retried 3x. Tests `test_reconcile_never_deletes_a_started_torrent_that_kept_its_pending_tag` and `..._stopped_torrent_that_already_holds_payload` pass. |
| WR-01 stuck torrent reported "Already added" | Yes | `_resume_or_duplicate()`: `fx-pending` with no live owner task resumes via `_process`; otherwise `duplicate`. |
| WR-02 XFF spoofing from the `qbit` network | Yes | `proxy.py` `TrustedProxyHeaders` honors XFF only from the DNS-resolved `web` peer and uses the right-most entry. Dockerfile has `--no-proxy-headers`. Caddyfile has `header_up X-Forwarded-For {remote_host}`. `test_proxy.py` including `test_a_container_that_spoofs_forwarded_for_is_throttled_as_itself` pass. I did not re-run the live spoof check (it would burn logins). |
| WR-03 unchecked plugin URLs | Yes | `is_safe_torrent_url` (magnet or public http(s), no userinfo/control chars/internal names), engine allowlist in `normalize_and_filter`, and `_url_is_public` resolves the host before any non-magnet add. Known limit (DNS rebinding) is documented in the fix report. |
| WR-04 stop-before-payload unproven | Partly (see truth 6) | Non-magnet adds use `stopped=True`; the fake models payload; real-engine tests exist and assert `evidence[0] == 0`. Not re-run by me. |
| WR-05 row stuck on "Preparing" | Yes | `Search.jsx`: 404 on job poll or 330 s give-up sets `lost`; `ResultRow.jsx` maps `lost` to a retryable button with `downloadLost` text. `RETRYABLE` includes `lost`. |
| WR-06 config drift | Yes | `repair_drift()` runs before every add (`pipeline.py`), covering the exclusion list, auto TMM, incomplete folder and both categories with save paths. Tests for changed path, missing category and switched-off exclusion pass. |
| WR-07 household lockout | Yes (documented trade-off) | `LoginThrottle` has a per-address limit and a global ceiling; only allowed attempts are recorded, so state is bounded; `docs/setup.md` documents the limits. |

### Required Artifacts

| Artifact | Status | Details |
|----------|--------|---------|
| `backend/app/{auth,config,main,proxy}.py`, `routers/*`, `download/*`, `search/*`, `qbit/*` | VERIFIED | Substantive, wired in `main.create_app`, data flows to real qBittorrent calls. |
| `frontend/src/{App,Login,Search,ResultRow,api,messages}` | VERIFIED | English only; the built bundle served by Caddy matches the source ("Log in", "TV Series", "Started ✓"). |
| `docker-compose.yml`, `docker-compose.admin.yml`, `web/Caddyfile`, `web/Dockerfile`, `backend/Dockerfile` | VERIFIED | Stack running; 3 services healthy. |
| `docs/ports-and-media.md`, `docs/setup.md`, `.env.example`, `scripts/*` | VERIFIED | Present and consistent with compose. |
| `backend/tests`, `infra/tests`, `frontend/src/__tests__` | VERIFIED | See spot-checks. |

### Key Link Verification

| From | To | Via | Status |
|------|----|-----|--------|
| Browser | backend | Caddy `/api/*` -> `backend:8000`, XFF set by Caddy | WIRED (live `/api/health` 200 through port 80) |
| backend | qBittorrent | `QbitClient` on network `qbit`; session cookie and creds only in backend | WIRED (`doctor` all OK, WebAPI 2.15.1) |
| Search row | pipeline | `result_id` -> `SearchService.get_result` -> `DownloadPipeline.submit` | WIRED |
| pipeline | qBittorrent category/save path | `qbit_category(settings, type)` + `repair_drift` | WIRED (Sintel in `/media/Film`) |
| bootstrap | readiness gate | `require_ready` on search/download routes | WIRED |
| bootstrap `on_ready` | `reconcile()` | `lambda: app.state.pipeline.reconcile()` | WIRED |

### Data-Flow Trace (Level 4)

| Artifact | Data | Source | Real data | Status |
|----------|------|--------|-----------|--------|
| `Search.jsx` rows | `snap.results` | `/api/search/{id}` -> qBittorrent `search/results` | Yes (smoke: 2 and 17 results) | FLOWING |
| `ResultRow.jsx` state | job status | `/api/download` + `/api/download/{job_id}` -> pipeline state | Yes | FLOWING |
| Health banner | `/api/health` | qBittorrent `webapi_version` + readiness | Yes (`{"status":"ok","qbittorrent":"up"}`) | FLOWING |

### Behavioral Spot-Checks and Test Runs

| Check | Command | Result | Status |
|-------|---------|--------|--------|
| Backend + infra suites | `uv run --project backend --frozen pytest backend/tests infra/tests -q` | 431 passed, 4 deselected (integration) | PASS |
| Frontend suite | `npm --prefix frontend test` | 104 passed (5 files) | PASS |
| Health | `curl http://127.0.0.1/api/health` | 200 `{"status":"ok","qbittorrent":"up"}`, CSP/nosniff/DENY headers | PASS |
| Stack | `docker compose ps` | web, backend, qbittorrent all healthy; only `0.0.0.0:80->80` published | PASS |
| qBittorrent config | `docker compose exec -T backend python -m app.tools.doctor` | every line OK (categories, auto TMM, temp path, 18/18 exclusions, share limits, 7 plugins) | PASS |
| Protected routes without login | curl, 6 routes | all 401 | PASS |
| Unpublished services | curl 127.0.0.1:8088, :8000 | no answer | PASS |
| Lint (info) | `ruff check backend infra scripts` | 5 style findings, no bugs | INFO |

Probe execution: none declared by the phase (step skipped).

### Requirements Coverage

Every ID in the ROADMAP Phase 1 list appears in at least one PLAN `requirements:` field, and REQUIREMENTS.md maps all 18 to Phase 1 as Complete. No orphans. SEC-05, SEC-06, DOWN-04..06 are mapped to Phase 2 and correctly absent.

| Requirement | Source Plans | Status | Evidence |
|-------------|--------------|--------|----------|
| AUTH-01 | 01-05, 01-11 | SATISFIED | Truth 1; own login, 30-day HttpOnly session, throttle. |
| SEC-01 | 01-02, 01-08, 01-09 | SATISFIED | Creds in backend env only; bundle and whitelisted responses carry none; `test_no_leaks.py`. |
| SEC-02 | 01-02, 01-04, 01-10 | SATISFIED | No published port except web; admin override loopback only. |
| SEC-03 | 01-07, 01-08, 01-13 | SATISFIED | `ContentType = Literal["film","serie"]`, strict, `extra=forbid` on both request bodies. |
| SEC-04 | 01-01, 01-02, 01-04, 01-05, 01-09, 01-10 | SATISFIED | Env-only `Settings`; placeholders rejected; hygiene tests; nothing tracked. |
| SRCH-01 | 01-07, 01-12 | SATISFIED | `PLUGIN_CATEGORY` film->movies, serie->tv. |
| SRCH-02 | 01-03, 01-07, 01-12 | SATISFIED | Truth 2. |
| SRCH-03 | 01-07, 01-12 | SATISFIED (timing: human) | Partial rows, `timed_out` message. |
| DOWN-01 | 01-08, 01-13 | SATISFIED | One tap, job, polling. |
| DOWN-02 | 01-06, 01-08 | SATISFIED | Server-side category map. |
| DOWN-03 | 01-06, 01-08, 01-09 | SATISFIED | Categories synced at start and before each add; auto TMM; no path from the browser. |
| PUI-01 | 01-04, 01-09, 01-11, 01-12, 01-13 | SATISFIED in code; phone layout is human | Mobile-first CSS, 48 px targets, viewport meta. |
| PUI-02 | 01-07, 01-08, 01-09, 01-11, 01-12, 01-13 | SATISFIED | Whitelisted responses; MSG-only copy; bundle scan. |
| INFRA-01 | 01-01, 01-02, 01-04, 01-06, 01-09, 01-10 | SATISFIED | One `docker compose up -d --build --wait`; `/api/health` reports status. |
| INFRA-02 | 01-04, 01-10 | SATISFIED | Truth 5. |
| MEDIA-01 | 01-04, 01-09, 01-10 | SATISFIED | Media contract doc; separate `/incomplete`; Sintel finished in `/media/Film` with partials in `/incomplete/Film`. |
| FILT-01 | 01-03, 01-06 | SATISFIED | `doctor`: exclusion list enabled, 18/18 patterns. |
| FILT-02 | 01-03, 01-08 | SATISFIED in code and fake-based tests; engine invariant is the human item | See truth 6. |

### Language check (user switched UI to English on 2026-10-22)

All UI copy is English: `frontend/src/messages.js`, the built bundle, `index.html lang="en"`. A repo-wide search (code, tests, docs, `.planning`) for Italian words and accented letters found no Italian UI text, and no `Scarica`, `Avviato`, `Esci` or `Accedi`. Leftovers are listed under Anti-Patterns (all non-UI).

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `frontend/src/__tests__/Login.test.jsx` | 38 | Test title says "Italian wrong-credentials message" (the text asserted is English) | Warning (stale wording) | Misleading test name; no user impact |
| `frontend/src/__tests__/ResultRow.test.jsx` | 64, 118 | Comment/title say "exact Italian text", "plain Italian message" | Warning (stale wording) | Same |
| `frontend/src/__tests__/Search.test.jsx` | 245, 403 | Titles say "plain Italian message" | Warning (stale wording) | Same |
| `.env.example` | `APP_USER=famiglia` | Italian word as the default username | Info | Never shown in the UI; the user types it. Consider `family` for consistency. |
| `scripts/dev_env.py --check` | n/a | Exits 1 on the live `.env` ("missing" 22 keys that all have defaults in `Settings`) | Info | The stack runs on defaults. Running `dev_env.py` without `--check` completes the file. |
| `infra/tests`, `scripts/qbit_login_check.py` | various | 5 ruff style findings (FURB167, SIM102, UP031) | Info | No behaviour impact. |

No TBD/FIXME/XXX/TODO/HACK markers in any phase file. No stub or hollow wiring found.

Open Info findings from the review (IN-01 to IN-07) remain open as recorded in `01-REVIEW-DISPOSITION.md`. None blocks the phase goal. Two are worth a look before the household uses it: IN-02 (a title containing the word "Sample", or `.ts/.mov/.webm` files, is rejected as "no video"), and IN-04 (web publishes on all interfaces, plain-HTTP cookie).

### Human Verification Required

See `human_verification` and `behavior_unverified_items` in the frontmatter:

1. Phone, 360 px layout and tap ergonomics.
2. Phone reaches `http://<laptop-ip>/`, and 8088 and 8000 are not reachable from the LAN (Windows firewall).
3. Tap Download on the phone: row goes Preparing then "Started ✓", and the file lands in the Film folder with nothing technical visible.
4. First results within about 2 s on the household network.
5. Two-phone lockout check (WR-07) to see whether real client addresses reach Caddy.
6. Run the 4 opt-in real-engine integration tests (needs the owner's OK; adds torrents).

### Gaps Summary

No gaps. The six success criteria hold in the code and on the running stack, all 18 requirement IDs are covered, and the eight review fixes hold. The remaining items need a real phone or a real qBittorrent session. The only non-blocking defect found is the stale "Italian" wording in five test titles or comments.

---

_Verified: 2026-10-22_
_Verifier: Claude (gsd-verifier)_

## Addendum (orchestrator, 2026-10-22)

Human item 6 resolved: the 4 opt-in real-engine integration tests were run against qBittorrent 5.2.4 via `docker-compose.admin.yml` (`QBIT_TEST_URL=http://127.0.0.1:8088 ... pytest backend/tests/integration -m integration`): **4 passed**. Only the Sintel open-movie magnet and locally bencoded synthetic torrents were added and deleted; base stack restored (8088 unpublished, `/api/health` ok). Success criterion 6 (rejected before any payload; 0 bytes before start) is now behavior-verified on the real engine.
