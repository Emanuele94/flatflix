---
phase: 03-jellyfin-server-tv-playback-gate
plan: 01
subsystem: infra
tags: [jellyfin, caddy, csp, docker-compose, infra-tests]

requires:
  - phase: 01-portal
    provides: Caddy single origin on port 80, compose stack, infra invariant tests
provides:
  - jellyfin service (pinned, hardened, unpublished) on its own network shared with web only
  - Caddy /jellyfin route with its own CSP, portal CSP scoped and pinned byte for byte, plain 502 text
  - BaseUrl /jellyfin seeded before Jellyfin's first start; gitignored /jellyfin/ folder
  - infra invariants (check_jellyfin, portal_csp_violations, jellyfin_route_violations) with mutation tests
affects: [03-02, 03-03, phase-04-media-mount, phase-05-tv-app]

actuals:
  tokens: 7400
  tasks: 2
  commits: 4
plan_head_before: f2d6d62108a456eb91faf7bfec42367469f9e702
commits: 4
plan_head_after: d4a0ef8a724d7741d0ed79919939d30037fbd49c

tech-stack:
  added: [jellyfin/jellyfin:12.3.20261023-013714 (image only, no packages)]
  patterns:
    - "Site-level header scoped with a negated path matcher instead of a route-level override"
    - "Pure check functions over config text plus mutation tests with teeth"

key-files:
  created:
    - infra/tests/test_caddyfile.py
  modified:
    - docker-compose.yml
    - web/Caddyfile
    - scripts/init-host-dirs.sh
    - .gitignore
    - infra/tests/test_compose_invariants.py
    - docs/ports-and-media.md
    - .planning/phases/03-jellyfin-server-tv-playback-gate/03-UI-SPEC.md

key-decisions:
  - "Portal CSP is scoped with @notjellyfin because a route-level header cannot override a site-level one (RESEARCH Pitfall 1)"
  - "/jellyfin/* policy adds 'wasm-unsafe-eval' for the ASS and PGS subtitle renderers (RESEARCH Pitfall 2)"
  - "Jellyfin has no DATA_ROOT mount, no env_file and no published port; only ./jellyfin/{config,cache,scratch}"

requirements-completed: [INFRA-03, JFIN-01]

coverage:
  - id: D1
    description: "Jellyfin answers under /jellyfin through Caddy only: 200 on /jellyfin/health, 308 on the bare path, one CSP with wasm-unsafe-eval, BaseUrl seeded"
    requirement: "JFIN-01"
    verification:
      - kind: other
        ref: "Task 1 verify block (curl checks, init-host-dirs.sh, smoke cache and login) run live on the laptop"
        status: pass
    human_judgment: false
  - id: D2
    description: "Portal policy unchanged byte for byte on /, with no unsafe-inline, pinned by tests"
    requirement: "INFRA-03"
    verification:
      - kind: unit
        ref: "infra/tests/test_caddyfile.py#test_the_portal_policy_is_pinned_byte_for_byte"
        status: pass
    human_judgment: false
  - id: D3
    description: "The jellyfin service hardening, network split, image pin and no-media-mount rules fail the suite when weakened"
    requirement: "INFRA-03"
    verification:
      - kind: unit
        ref: "infra/tests/test_compose_invariants.py#test_a_weakened_jellyfin_entry_is_caught"
        status: pass
    human_judgment: false
  - id: D4
    description: "With Jellyfin stopped, /jellyfin answers 502 with the plain sentence and the portal login still passes"
    requirement: "INFRA-03"
    verification:
      - kind: other
        ref: "Task 2 verify block: curl body and status, smoke.py login"
        status: pass
    human_judgment: false
  - id: D5
    description: "UI-SPEC amended with the research findings"
    verification: []
    human_judgment: true
    rationale: "Prose contract; a reader must confirm the amendments say what they should"

duration: ~35min (start time not captured, estimated)
completed: 2026-10-25
status: complete
---

# Phase 3 Plan 01: Jellyfin behind Caddy Summary

**Pinned, hardened, unpublished Jellyfin 12.3 served at /jellyfin through the existing Caddy origin with its own CSP, while the portal policy stays byte for byte and the infra tests fail on any weakening.**

## Performance

- **Duration:** ~35 min (start time not captured, estimated)
- **Completed:** 2026-10-25
- **Tasks:** 2 (1 tracer, 1 TDD)
- **Files modified:** 9 (1 created)

## Accomplishments

- `jellyfin` service in `docker-compose.yml`: image `jellyfin/jellyfin:12.3.20261023-013714`, `PUID:PGID` user, read-only root, `cap_drop ALL`, no-new-privileges, `/tmp` tmpfs, config and cache binds, read-only scratch bind, healthcheck on `/jellyfin/health`, rotated logs; own `jellyfin` network shared with `web` only; `web` does not wait for it.
- `web/Caddyfile`: portal CSP moved to `header @notjellyfin` (identical string), `redir /jellyfin /jellyfin/ 308`, `handle /jellyfin/*` with its own CSP (adds `'wasm-unsafe-eval'`) and `reverse_proxy jellyfin:8096`, `handle_errors` with the plain sentence.
- `scripts/init-host-dirs.sh` creates eight `jellyfin/...` folders and seeds `jellyfin/config/config/network.xml` (BaseUrl `/jellyfin`) only when absent (prints "seeded" or "kept"); `.gitignore` has root-anchored `/jellyfin/`.
- `infra/tests`: `check_jellyfin`, network membership and start-order tests, `_caddy_handle_blocks` ignores `handle_errors`, new `test_caddyfile.py` with `portal_csp_violations` and `jellyfin_route_violations` and 10 mutation tests; ports doc and UI-SPEC amended.

## Task Commits

1. **Task 1 (tracer): /jellyfin through Caddy** - `1f58132` (feat)
2. **Task 2 RED: failing tests** - `3f0cf7a` (test)
3. **Task 2 GREEN: checkers implemented, ports doc** - `f394896` (feat)
4. **Task 2: UI-SPEC amendments** - `d4a0ef8` (docs)

## TDD Gate Compliance

- **RED (`3f0cf7a`):** `check_jellyfin`, `portal_csp_violations`, `jellyfin_route_violations`, `site_lines` and `depth1_blocks` were stubs returning `[]`. Run: `34 failed, 106 passed`. Every failure is an assertion on the planned behavior (`any(expected in violation ...)` over an empty list, `len(blocks) == 1`, the handle_errors helper test, the ports-doc test); no import, collection or fixture errors. Semantic assessment: the target tests executed and failed for the intended reason. The stub-based RED was validated by inspection, not by `gsd_run check tdd-red-evidence` (pytest text output is not one of its supported report formats).
- **GREEN (`f394896`):** `140 passed` in `infra/tests`; `1128 passed, 19 deselected` for `backend/tests infra/tests`.
- **REFACTOR:** none.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Docker credential helper failed during `docker compose up --build`**
- **Found during:** Task 1, step 5
- **Issue:** `error getting credentials - err: exit status 1` from `desktop.exe` (WSL credential helper) while resolving the uv image for the backend build.
- **Fix:** ran Docker commands with `DOCKER_CONFIG` pointing at a scratch directory holding an empty `config.json` (public images only). `~/.docker/config.json` was not modified. Nothing in the repository changed.
- **Verification:** the stack came up healthy and all live checks passed.

**2. [Rule 1 - Bug] Plan-order detail: Task 1 leaves one existing infra test failing until Task 2**
- **Found during:** Task 1 to Task 2 hand-off
- **Issue:** `test_qbittorrent_and_web_share_no_network` asserted `web == {"edge"}`; Task 1 puts web on `{"edge", "jellyfin"}`, so that test was red between the two commits (the plan itself schedules its update in Task 2).
- **Fix:** updated in Task 2 (`f394896`). No separate action.

**Total deviations:** 2 (1 blocking environment workaround, 1 expected inter-task test gap). **Impact:** none on scope.

## Issues Encountered

- `ruff check` reports three FURB167 hints (`re.M`) in `test_compose_invariants.py` (two lines predate this plan) and `ruff format --check` disagrees with the existing 100-column style of `infra/tests`. Both predate the plan and `infra/tests` is not linted by the project; only my own `re.M` in `test_caddyfile.py` was changed to `re.MULTILINE`. Not fixed elsewhere (out of scope).

## Verification Results

- Task 1 acceptance criteria: all PASS (image pin 1, `@notjellyfin` 2, wasm 2, redir 1, error text 1, `network.xml` in the script, `/jellyfin/` 1, second `init-host-dirs.sh` run prints "kept", jellyfin not running at the end).
- Task 2 acceptance criteria: all PASS (`check_jellyfin` 1, `PORTAL_CSP` 8, "never published; no admin override" 1, "reserved for Phase 3" 0, UI-SPEC wasm, `cast_sender.js`, `D-98`, amendments heading).
- Live: `/jellyfin/health` 200; bare `/jellyfin` 308 to `/jellyfin/`; one CSP header on `/jellyfin/web/index.html` with `'wasm-unsafe-eval'`; `/` carries the unchanged portal policy; with Jellyfin stopped, `/jellyfin/web/index.html` answers `Jellyfin is not available right now. Ask the admin to check the server. 502`; `scripts/smoke.py cache` and `login` pass with Jellyfin both running and stopped; `caddy validate` reports a valid configuration.
- Wizard window: Jellyfin was left stopped after each task (`docker compose ps --status running --services` lists no jellyfin); plan 03-03 starts and provisions it in one step.

## Known Stubs

None.

## Threat Flags

None. All new surface (the `/jellyfin` route and the jellyfin container) is in the plan's threat model (T-03-01 to T-03-05).

## Next Phase Readiness

Ready for 03-02 (parallel, config keys) and 03-03 (provisioning). The jellyfin container is stopped and unprovisioned; its first-run wizard is open to the LAN until 03-03 runs.

## Self-Check: PASSED

All eight changed and created files exist; commits `1f58132`, `3f0cf7a`, `f394896` and `d4a0ef8` are ancestors of HEAD; RED (`test`) and GREEN (`feat`) commits for `03-01` are both present.
