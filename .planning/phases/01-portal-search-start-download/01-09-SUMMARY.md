---
phase: 01-portal-search-start-download
plan: 09
subsystem: testing
tags: [smoke, leak-scan, canary, docs, setup-guide, fastapi, caddy, qbittorrent]
status: complete

requires:
  - phase: 01-portal-search-start-download
    provides: "01-08 POST /api/download pipeline; 01-13 Scarica button; 01-06 doctor; 01-05 login and hash helper; 01-04 Caddy and compose"
provides:
  - "scripts/smoke.py subcommands download and all, and scan_for_leaks over every recorded response"
  - "doctor --torrents (portal torrents: name, category, save path, incomplete path, state, percent)"
  - "test_no_leaks: canary scan over every API route plus the full search and download flow"
  - "test_config: .env.example keys equal Settings fields plus the compose-level keys"
  - "docs/setup.md fresh-machine and admin guide; README pointer"
  - "CLAUDE.md Status with real commands; D-23 wording in CLAUDE.md and REQUIREMENTS.md FILT-02; PROJECT.md decisions"
affects: [phase-02, phase-02.1, phase-03]

plan_head_before: 31e2fa7eed1cd50f6ac0303e3025fb6efe6d97ce
plan_head_after: 8ef8d8a19ee432f82e7a61cf3a36d5bb0916c640

actuals:
  tokens: 11250
  tasks: 3
  commits: 3

tech-stack:
  added: []
  patterns:
    - "Leak scans name the marker, never the value; secret values are read from the local env file inside the script"
    - "Smoke downloads are limited by regex to the Blender open movies; no match means SKIP, never a wider search"
    - "doctor --torrents is a separate list mode so a grep on its output cannot be satisfied by the category checks"

key-files:
  created:
    - backend/tests/test_no_leaks.py
    - docs/setup.md
  modified:
    - scripts/smoke.py
    - backend/app/tools/doctor.py
    - backend/tests/test_config.py
    - backend/tests/test_bootstrap.py
    - README.md
    - CLAUDE.md
    - .planning/REQUIREMENTS.md
    - .planning/PROJECT.md

key-decisions:
  - "doctor --torrents prints only the torrent list (tag fx) and exits 0 unless qBittorrent is unreachable; the checks stay the default mode"
  - "Every smoke subcommand ends with the leak scan, not only all and download, so login and search runs are covered too"
  - "test_no_leaks sweeps every route twice (anonymous and logged in) and includes a planted-leak self-test of the detector"

requirements-completed: [SEC-01, SEC-04, INFRA-01, PUI-01, PUI-02, DOWN-03, MEDIA-01]

duration: about 40 min
completed: 2026-10-22
---

# Phase 1 Plan 09: End-to-end tracer, leak scans and setup guide Summary

**The household flow (login, search, Scarica) runs through Caddy on the real stack and starts a real Sintel torrent in the Film category; 27 responses scanned with no leak, a canary test covers every route, and docs/setup.md plus CLAUDE.md now match what was built.**

## Accomplishments

- Tracer on the real stack: `python3 scripts/smoke.py --base http://127.0.0.1 all` logged in, searched "1080p" (100 results, first rows after about 1.5 s), skipped "Big Buck Bunny" (no passing result), started the "Sintel" open-movie result (`OK download started`) and ended with `OK no-leaks (27 responses scanned)`. A second run answered `OK download duplicate`.
- `doctor --torrents` listed the torrent with category Film, save path `/media/Film`, incomplete path `/incomplete/Film`.
- MEDIA-01 edge observed live: while the torrent was at 3.9 percent its data sat only under `data/incomplete/Film` and `data/media/Film` was empty; after it completed (100 percent, seeding) the video was in `data/media/Film`.
- `backend/tests/test_no_leaks.py`: canary qBittorrent password, secret key, qBittorrent host, category names and save paths; every APIRoute called anonymous and logged in, plus search, poll, download and job poll; no canary, `/media/`, `/incomplete`, `magnet:`, `QBT_SID`, `save_path` or `"category"` in any body or header. A planted-leak test proves the detector fires.
- `test_config`: `.env.example` keys equal `{Settings fields upper-cased} + {WEB_PORT, MEDIA_ROOT, INCOMPLETE_DIR, PUID, PGID, TZ}` with both differences reported on failure.
- `docs/setup.md` (English, `<laptop-ip>` only): Docker Desktop WSL integration, `.env`, hash helper with single quotes, init-host-dirs, one `docker compose up`, doctor, Windows port 80 and Private-profile firewall rule, WEB_PORT, trusted plugins, seeding policy, pinned 5.2.4 upgrade guard, login lockout (Pitfall 14, `docker compose restart backend`), troubleshooting. README links it.
- `CLAUDE.md` Status lists the real commands and is committed to git; D-23 `stopCondition=MetadataReceived` wording in CLAUDE.md and REQUIREMENTS.md FILT-02; PROJECT.md records FastAPI (D-01) as decided and the W2 and W3 progress.
- Verification: backend and infra suites 357 pass, frontend vitest 100 pass, hygiene test passes on the new docs.

## Task Commits

| Task | Commit | Message |
| ---- | ------ | ------- |
| 1 tracer | 2a6e8df | feat(01-09): tracer smoke download/all with leak scan, doctor --torrents, canary no-leak test |
| 2 | a47dc7c | docs(01-09): setup guide for a fresh machine and the household admin |
| 3 | 8ef8d8a | docs(01-09): align CLAUDE.md, REQUIREMENTS.md and PROJECT.md with the built portal |

The Task 3 commit holds exactly CLAUDE.md, .planning/REQUIREMENTS.md and .planning/PROJECT.md.

## Tracer gate

`HUMAN_VERIFY_MODE` is end-of-phase and the tracer `<verify>` is automated-only, so it was re-run: `smoke all` again passed (`OK download duplicate`, `OK no-leaks`). Tracer verified end-to-end, expansion tasks followed.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality] doctor --torrents is a separate list mode**
- **Found during:** Task 1
- **Issue:** the plan's verify pipes `doctor --torrents` into `grep -q '/media/Film'`. The normal doctor output already contains `/media/Film` in its category lines, so the grep could pass with no torrent at all.
- **Fix:** `--torrents` prints only the portal torrent lines (plus a count line), so the grep proves a Film torrent exists.
- **Files modified:** backend/app/tools/doctor.py
- **Commit:** 2a6e8df

**2. [Rule 2 - Missing critical functionality] Unit test for the doctor torrent line**
- **Found during:** Task 1
- **Issue:** the new doctor output (truncation, percent, no hash) had no test.
- **Fix:** `test_doctor_torrent_line_has_paths_and_progress_but_no_hash` in test_bootstrap.py (file not in the plan's list).
- **Commit:** 2a6e8df

**3. [Rule 1 - Consistency] Stale "FastAPI or Node, undecided" in PROJECT.md**
- **Found during:** Task 3
- **Issue:** the portal-part context bullet in PROJECT.md still said the backend was undecided, contradicting the Key Decisions row the plan updates.
- **Fix:** one scoped replacement to "FastAPI, D-01".
- **Commit:** 8ef8d8a

**Total deviations:** 3 auto-fixed (2 Rule 2, 1 Rule 1). **Impact:** none on scope; all small and test-backed or doc-only.

## Authentication Gates

None. The smoke script reads the household password from `.dev-portal-password` internally; nothing was printed.

## Issues Encountered

- "Big Buck Bunny" returned no result that passed the filters; "Sintel" did, so the `all` fallback order worked as designed. The regex was not widened.
- The open-licensed Sintel torrent finished and is seeding (ratio 1.0 or 24 h, then stops). It is the household's first real file in `data/media/Film`.

## Human verification (queued for end-of-phase, not faked)

1. **Phone check (ROADMAP success criterion 1, PUI-01):** on a real phone on the home Wi-Fi, open `http://<laptop-ip>/`; the Italian login screen appears first and nothing is reachable without logging in; after login a Film search shows rows within about 2 seconds; tapping Scarica on an open-licensed Blender result turns the row into "Avviato" (or "In preparazione" then "Avviato"); big tap targets, no sideways scrolling, no qBittorrent, folder path, category name or English error visible. Record the result in `01-UAT.md` via `/gsd-verify-work 1`.
2. **LAN reachability:** the Windows firewall rule for TCP 80 on the Private profile and port publishing through Docker Desktop can only be proven from another device on the LAN.
3. **Flagged assumption (EDGE SEC-01):** the edge probe could not classify SEC-01; it is covered by test_no_leaks, the smoke leak scan and the backend-only QbitClient. Please review at verification.

Note: because the Sintel torrent already completed, a phone tap on the same result now answers "Già presente" (duplicate). To watch the in-progress behavior, pick another Blender open-movie result, for example Tears of Steel or Big Buck Bunny, when one passes the filters.

## Known Stubs

None.

## Threat Flags

None. No new network endpoint, auth path or schema; the new code is a CLI flag, a script, tests and docs.

## Requirements

All seven were `ready` per `requirements.ready-ids`. Marked complete from this run's evidence: SEC-01 (canary test and smoke scan), DOWN-03 (real Film torrent at `/media/Film`), INFRA-01 (one `docker compose up -d --build --wait`, health `ok`). SEC-04, PUI-02 and MEDIA-01 were already checked off and this run adds evidence. PUI-01 was already checked off by an earlier plan; its phone confirmation is the human item above.

## Next Phase Readiness

Phase 1 plans are all summarized. Phase 1 stays `human_needed` until the phone check is recorded with `/gsd-verify-work 1`. The stack is left running (web, backend, qbittorrent healthy).

## Self-Check: PASSED

- Files exist: scripts/smoke.py, backend/tests/test_no_leaks.py, backend/app/tools/doctor.py, docs/setup.md, CLAUDE.md (tracked), README.md.
- Commits 2a6e8df, a47dc7c, 8ef8d8a are ancestors of HEAD.
- Acceptance criteria re-run: smoke has `download`, `all`, `scan_for_leaks`; test_no_leaks iterates `app.routes` and holds the canary; doctor has `--torrents`; docs/setup.md has every required string and passes the hygiene test; CLAUDE.md, REQUIREMENTS.md and PROJECT.md greps pass; `git show --name-only HEAD` for Task 3 lists exactly the three files.
- Plan verification: backend and infra 357 pass, frontend 100 pass, smoke `all` OK.
