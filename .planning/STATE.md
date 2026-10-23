---
gsd_state_version: "1.0"
current_phase: "02.1"
current_phase_name: Download Quarantine & Firecracker Validation (INSERTED)
status: executing
stopped_at: Completed 02.1-03-PLAN.md
last_updated: "2026-10-23T19:26:55.963Z"
last_activity: 2026-10-23
last_activity_desc: Phase 02.1 execution started
state_head: b0c616a8c065947fbf3df22d800e28c026ac87d7
progress:
  total_phases: 7
  completed_phases: 2
  total_plans: 36
  completed_plans: 30
  percent: 29
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-10-23)

**Core value:** A non-technical household member can get a film or series onto the TV using only a phone and the TV remote, and watch it in at least 1080p with no video transcoding.
**Current focus:** Phase 02.1 — Download Quarantine & Firecracker Validation (INSERTED)

## Current Position

Phase: 02.1 (Download Quarantine & Firecracker Validation (INSERTED)) — EXECUTING
Plan: 4 of 9
Status: Ready to execute
Last activity: 2026-10-23 — Phase 02.1 execution started

Progress: [███░░░░░░░] 29%

## Performance Metrics

**Velocity:**
- Total plans completed: 27
- Average duration: - min
- Total execution time: 0.0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01 | 16 | - | - |
| 02 | 11 | - | - |

**Recent Trend:**
- Last 5 plans: none yet
- Trend: n/a

*Updated after each plan completion*
**Per-Plan Metrics:**

| Plan | Duration | Tasks | Files |
|------|----------|-------|-------|
| Phase 01 P01 | 6 min | 3 tasks | 8 files |
| Phase 01 P03 | 12min | 3 tasks | 6 files |
| Phase 01 P10 | 12 min | 2 tasks | 8 files |
| Phase 01 P02 | 4 min | 2 tasks | 13 files |
| Phase 01 P04 | 8min | 2 tasks | 14 files |
| Phase 01 P05 | 10min | 3 tasks | 14 files |
| Phase 01 P11 | 10min | 2 tasks | 7 files |
| Phase 01 P06 | 6 min | 3 tasks | 12 files |
| Phase 01 P07 | 7 min | 2 tasks | 12 files |
| Phase 01 P12 | 15min | 2 tasks | 8 files |
| Phase 01 P08 | 18 min | 2 tasks | 14 files |
| Phase 01 P13 | 25 min | 2 tasks | 6 files |
| Phase 01 P09 | 40 min | 3 tasks | 10 files |
| Phase 01 P14 | 9 min | 3 tasks | 5 files |
| Phase 01 P15 | 8 min | 3 tasks | 4 files |
| Phase 01 P16 | 6 min | 3 tasks | 11 files |
| Phase 02 P01 | 25 min | 3 tasks | 10 files |
| Phase 02 P02 | 9 min | 2 tasks | 4 files |
| Phase 02 P03 | 8 min | 2 tasks | 4 files |
| Phase 02 P04 | 12 min | 2 tasks | 6 files |
| Phase 02 P05 | 20 min | 2 tasks | 8 files |
| Phase 02 P06 | 4min | 3 tasks | 10 files |
| Phase 02 P07 | 8min | 3 tasks | 8 files |
| Phase 02 P08 | 10 min | 2 tasks | 4 files |
| Phase 02 P09 | 25min | 3 tasks | 8 files |
| Phase 02 P10 | 30min | 2 tasks | 4 files |
| Phase 02 P11 | 7 min | 2 tasks | 3 files |
| Phase 02.1 P01 | 9 min | 3 tasks | 13 files |
| Phase 02.1 P02 | 8 min | 3 tasks | 7 files |
| Phase 02.1 P03 | 7 min | 3 tasks | 8 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table. No locked decisions (no ADRs ingested).
Recent decisions affecting current work:

- [Intake]: Build the qBittorrent portal first (Phases 1-2), then the home theater (Phases 3-6) — user decision
- [Intake]: Public MIT repo; no secrets, LAN IPs or real credentials committed — user constraint
- [Intake]: The 3 ingest warnings are explicit roadmap work: W1 naming (decide Phase 3, build Phase 4), W2 media wiring (Phase 1 then Phase 4), W3 port map (Phase 1 then Phase 3)
- [Phase 01]: 01-01: Lockfiles generated without install; package set (incl. transitive opentelemetry-api 1.45.1, annotated-doc 0.0.5) human-approved before first uv sync / npm ci
- [Phase 01]: Allowlist keys on the final lower-cased extension only; no-video torrents rejected with reason no_video
- [Phase 01]: Search result_id is sha1 of the dedupe key (btih alone for magnets), stable across engines and polls
- [Phase 01]: 01-10: research A2 holds - with-contenv init script provisions qBittorrent WebUI credentials from env on first run
- [Phase 01]: 01-10: qBittorrent admin access only via docker-compose.admin.yml on 127.0.0.1:8088; no service uses 8080
- [Phase 01]: 01-02: backend container healthcheck checks /api/health HTTP 200 (liveness), not status ok, so a qBittorrent outage does not make the portal unhealthy
- [Phase 01]: 01-02: QbitClient shares one re-login via session epoch plus asyncio.Lock; 900 s cool-down after 401, 3600 s after 403; transport errors never block
- [Phase 01]: 01-04: Hygiene scanner builds private blocks from tuples so it never flags its own source; git calls run from repo root
- [Phase 01]: 01-04: CSP default-src 'self' at Caddy, so no inline style attributes or third-party URLs in the portal
- [Phase 01]: 01-05: route-enumeration guard uses fastapi.routing.iter_route_contexts (FastAPI 0.159 nests included routers); every feature router must use protected_router()
- [Phase 01]: 01-05: LoginThrottle reserves the attempt slot synchronously before argon2 verify and lives on app.state.login_throttle (built in create_app)
- [Phase 01]: 01-11: login errors other than 401/429 render the serverUnreachable message so nothing technical reaches the screen
- [Phase 01]: 01-06: bootstrap stops for good on auth, ban or WebAPI below 2.15.1 (readiness failed, one ERROR line) and retries other qBittorrent errors with min(2 ** n, 30) s backoff; a createCategory 409 requires the category to appear in a re-read list, never an edit on a guess
- [Phase 01]: 01-06: downloads gated by require_ready (503 not_ready) until setPreferences and categories succeeded; search plugins install after categories and never block readiness
- [Phase 01]: 01-07: a cut-short search (timeout, eviction, shutdown) is done with timed_out true only when no row passed the filters; a non-empty SUSPICIOUS_TERMS replaces the built-in list — A timeout is an ordinary end, never an error; one documented rule for the term list
- [Phase 01]: 01-07: search_start 409 frees tracked searches and sweeps untracked leftovers, then retries once; qBittorrent failures answer 503 search_unavailable — A crashed backend must not block search permanently, and no qBittorrent body reaches the browser
- [Phase 01]: 01-12: added MSG.searchFailed so poll errors (e.g. 404 search_not_found) show plain English, never technical text
- [Phase 01]: A STARTED job dedupes a repeat tap only for 60 s; later taps hit the btih duplicate check
- [Phase 01]: A 404 from torrents/files right after a magnet add is retried like an empty list, bounded by METADATA_TIMEOUT
- [Phase 01]: Bootstrapper on_ready hook runs reconcile after readiness; reconciled jobs reuse the id from their fx-job tag
- [Phase 01]: A non-magnet torrent that never appears becomes unavailable; a late arrival keeps fx-pending and the next reconcile removes it
- [Phase 01]: 01-13: download POST and job polling live in Search (row state map keyed by result_id); ResultRow is a pure view
- [Phase 01]: 01-13: rows send the type of the search that produced them, captured at submit, not the live toggle
- [Phase 01]: 01-09: doctor --torrents is a separate list mode; every smoke subcommand ends with the leak scan; smoke downloads only Blender open movies
- [Phase 01]: 01-14: every torrents/add sends stopCondition=MetadataReceived and never the stopped field (reverts WR-04); qBittorrent 5.2.4 pauses a metadata-complete torrent under that condition
- [Phase 01]: 01-15: search persisted in sessionStorage (Search.jsx only); logout and a new search clear it, a 401 does not; saved ids must match 16 hex and a future startedAt is rejected
- [Phase 01]: 01-16: FILT-02 allowlist unchanged; non-allowlisted video formats (.webm etc.) give status unsupported with their own text (D-13 amended)
- [Phase 01]: 01-16: D-24 reload persistence via sessionStorage recorded; D-23 re-affirmed for plugin-printed magnets
- [Phase 02]: Downloads list route is read-only and not behind require_ready, so it keeps working while bootstrap retries
- [Phase 02]: A torrent is the primary identity of a list row (HMAC id of the info-hash); jobs are only a detail for rows with no torrent
- [Phase 02]: 02-02: sample ratio measured against the largest non-sample video of any format (10 %, inclusive); 415 from torrents/add is unavailable
- [Phase 02]: Hashed /assets/* never fall back to index.html: a missing asset is a plain 404, so no HTML page is cached for a year (D-42)
- [Phase 02]: Logs stay on stdout through Docker json-file 10m x 5 via one x-logging anchor; no log volume (D-40)
- [Phase 02]: 02-04: finished_at is stamped in a finally around the whole job task so a long Preparing job ages from its end, not its start
- [Phase 02]: 02-04: a failed job row is listed next to its torrent row; the torrent still appears once, and a hash-named job name is never shown
- [Phase 02]: 02-05: search and download throttles are per address only (no global ceiling); LoginThrottle kept as an alias of SlidingWindowThrottle
- [Phase 02]: 02-06: a known-empty Downloads list is not shown as 'No downloads yet' while an outage is active; only the banner shows
- [Phase 02]: 02-06: Downloads polling is a setTimeout chain with epoch check; only visibilityState 'hidden' pauses it (jsdom never reports 'visible')
- [Phase 02]: 02-07: deleteFiles is true only for a known in-progress raw state below progress 1; the list action derives from the same cancel_deletes_files rule
- [Phase 02]: 02-07: cancel sweep and job-tag lookup decide deleteFiles per row so no portal path deletes a completed download's files
- [Phase 02]: 02-08: cancelled is a JOB_STATES member (backend status, stops polling); throttled is a client-side ROW_STATES member; both retryable and restorable
- [Phase 02]: 02-09: failed logins audit outcome and address only, never the attempted username; download_done is written only for jobs that were not cancelled
- [Phase 02]: 02-09: RedactingFilter keeps record.args structure and is installed on root and uvicorn handlers (RESEARCH A3 confirmed: uvicorn handlers do not propagate)
- [Phase 02]: 02-10: Cancel and Remove share one id-only DELETE handler; a removed row is remembered with the poll number so an older poll cannot resurrect it
- [Phase 02]: 02-11: the list integration test asserts one item with the synthetic torrent's id, not one item overall, so it passes beside the household's real downloads
- [Phase 02]: Review fixes WR-01..WR-05: cancel keeps files of any torrent that ever finished (completion_on <= 0 pinned on the real engine); cancel re-reads before delete; sweep starts before the first lookup
- [Phase 02.1]: D-44 applied: one DATA_ROOT host folder bound once at /data in qbittorrent and backend; Settings field data_path (DATA_PATH) is the container side — Hardlinks need one mount; the host and container names differ because the backend receives the whole env file
- [Phase 02.1]: Settings refuse any save path outside DATA_PATH/quarantine; backend runs as PUID:PGID — A save path inside media would let a download skip the safety check; link() needs the owner uid under fs.protected_hardlinks
- [Phase 02.1]: 02.1-02: sandbox runner is a stdlib HTTP service; /selftest bypasses the 4096-byte floor, and the unauthenticated listener must stay on an internal compose network
- [Phase 02.1]: 02.1-02: host faults (kvm, artifacts, boot, permission) answer 503 runner_unavailable, never a verdict; console reader keeps the first MAX_CONSOLE_BYTES and drains the rest
- [Phase 02.1]: 02.1-03: bitrate band compared as bits against kbps*1000*duration so bounds are exactly inclusive; runner host faults are RunnerUnavailable (wait), refusals RunnerRefused (unprobeable)
- [Phase 02.1]: 02.1-03: check_subtitle never vouches for an unread file (no head bytes = subtitle_empty); summary() tokens are sanitised for audit lines

### Pending Todos

None yet.

### Blockers/Concerns

- [Phase 1]: Port map (W3) and media-folder contract (W2) must be set when the portal stack first comes up; do not reuse host port 8080 for two services.
- [Phase 1-2]: Do not preclude any naming option (W1): keep completed-torrent info (hash, name, category, content path) reachable from the backend and avoid freezing the download request body if Phase 3 picks portal-side renaming.
- [Phase 2.1]: Phase 2.1 changes the save path to quarantine; the Downloads list, cancel rule (cancel_deletes_files) and Film/SerieTV category filter must keep working for torrents saved under quarantine.
- [Phase 2]: Audit lines and rate limits see the Docker gateway address on the WSL2 dev host; confirm real client addresses on the Ubuntu Server box. Info-level review items IN-01..IN-03 remain open (02-REVIEW-DISPOSITION.md).
- [Phase 2.1]: Firecracker needs `/dev/kvm`: present on the WSL2 dev machine; the production Ubuntu Server box must be x86_64 with VT-x (Raspberry Pi 5 likely unsuitable). Guest kernel and rootfs must be built by repo scripts, not committed.
- [Phase 3]: Naming decision (NAME-01) must be recorded before Phase 4 starts; Phase 3's Jellyfin library stays on a scratch sample folder until then.
- [Phase 3]: TV compatibility gate may force a mitigation (re-encode, plan B stick, N100 hardware) that changes Phase 5 and 6 scope.
- [Phase 6]: Plan A (community VIDAA icon tool) is unofficial; a firmware update may break it.

### Roadmap Evolution

- Phase 02.1 inserted after Phase 2: Download Quarantine & Firecracker Validation: ffprobe in Firecracker microVM before files reach media folders; plus FILT-01/02 download filtering added to Phase 1 (user request)

## Deferred Items

Items acknowledged and deferred at milestone close, most recent first:

| Category | Item | Status | Deferred At | Milestone |
|----------|------|--------|-------------|-----------|
| *(none)* | | | | |

## Session Continuity

Last session: 2026-10-23T19:26:55.648Z
Stopped at: Completed 02.1-03-PLAN.md
Resume file: None
