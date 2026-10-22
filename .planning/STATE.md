---
gsd_state_version: "1.0"
current_phase: 01
current_phase_name: Portal Search & Start Download
status: executing
stopped_at: Completed 01-13-PLAN.md
last_updated: "2026-10-22T11:21:15.267Z"
last_activity: 2026-10-22
last_activity_desc: Phase 01 execution started
state_head: 08c88e1b1e64aad16e5b96994b8d26d6797a8cfe
progress:
  total_phases: 7
  completed_phases: 0
  total_plans: 13
  completed_plans: 12
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-10-21)

**Core value:** A non-technical household member can get a film or series onto the TV using only a phone and the TV remote, and watch it in at least 1080p with no video transcoding.
**Current focus:** Phase 01 — Portal Search & Start Download

## Current Position

Phase: 01 (Portal Search & Start Download) — EXECUTING
Plan: 13 of 13
Status: Ready to execute
Last activity: 2026-10-22 — Phase 01 execution started

Progress: [░░░░░░░░░░] 0%

## Performance Metrics

**Velocity:**
- Total plans completed: 0
- Average duration: - min
- Total execution time: 0.0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| - | - | - | - |

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
- [Phase 01]: 01-12: added MSG.searchFailed so poll errors (e.g. 404 search_not_found) show plain Italian, never technical text
- [Phase 01]: A STARTED job dedupes a repeat tap only for 60 s; later taps hit the btih duplicate check
- [Phase 01]: A 404 from torrents/files right after a magnet add is retried like an empty list, bounded by METADATA_TIMEOUT
- [Phase 01]: Bootstrapper on_ready hook runs reconcile after readiness; reconciled jobs reuse the id from their fx-job tag
- [Phase 01]: A non-magnet torrent that never appears becomes unavailable; a late arrival keeps fx-pending and the next reconcile removes it
- [Phase 01]: 01-13: download POST and job polling live in Search (row state map keyed by result_id); ResultRow is a pure view
- [Phase 01]: 01-13: rows send the type of the search that produced them, captured at submit, not the live toggle

### Pending Todos

None yet.

### Blockers/Concerns

- [Phase 1]: Port map (W3) and media-folder contract (W2) must be set when the portal stack first comes up; do not reuse host port 8080 for two services.
- [Phase 1-2]: Do not preclude any naming option (W1): keep completed-torrent info (hash, name, category, content path) reachable from the backend and avoid freezing the download request body if Phase 3 picks portal-side renaming.
- [Phase 1]: Add torrents stopped and filter the file list (FILT-02) before starting; keep the download flow able to route completed files to quarantine later (Phase 2.1 changes the save path).
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

Last session: 2026-10-22T11:21:15.205Z
Stopped at: Completed 01-13-PLAN.md
Resume file: None
