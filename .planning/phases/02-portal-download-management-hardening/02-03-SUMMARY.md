---
phase: 02-portal-download-management-hardening
plan: 03
subsystem: infra
tags: [caddy, cache-control, docker-compose, json-file, log-rotation, smoke]

requires:
  - phase: 01-portal-search-start-download
    provides: Caddyfile, compose stack, scripts/smoke.py
provides:
  - "Caddy: index.html and the SPA fallback answer no-cache; hashed /assets/* answer a one-year immutable cache for 2xx only, with no fallback (D-42)"
  - "Compose: json-file log rotation 10 MB x 5 on qbittorrent, backend and web through one x-logging anchor (D-40)"
  - "smoke.py cache subcommand"
affects: [02-04, 02-06, phase-3]

actuals:
  tokens: 1450
  tasks: 2
  commits: 2

commits: 2
plan_head_before: cbed50f9f7b477cdfd9126f2389745ea4e38878b
plan_head_after: a1b68510caaa399af2a0961076af9e7a097ebf4c

tech-stack:
  added: []
  patterns:
    - "Hashed Vite assets under handle /assets/* with header match status 2xx and no try_files"
    - "One x-logging YAML anchor in the base compose file, referenced by every service"

key-files:
  created: []
  modified:
    - web/Caddyfile
    - docker-compose.yml
    - infra/tests/test_compose_invariants.py
    - scripts/smoke.py

key-decisions:
  - "Hashed assets never fall back to index.html: a missing /assets file is a plain 404, so an HTML page is never cached for a year"
  - "Logs stay on stdout through Docker; no log volume, file or service is added"

requirements-completed: [SEC-06]

coverage:
  - id: D1
    description: "GET / and the SPA fallback (/downloads) answer Cache-Control: no-cache through the running Caddy"
    requirement: "SEC-06"
    verification:
      - kind: command
        ref: "python3 scripts/smoke.py --base http://127.0.0.1 cache (cache-index-no-cache, cache-spa-fallback-no-cache)"
        status: pass
      - kind: unit
        ref: "infra/tests/test_compose_invariants.py#test_index_and_spa_fallback_are_revalidated"
        status: pass
    human_judgment: false
  - id: D2
    description: "A hashed asset answers 200 with public, max-age=31536000, immutable; a missing asset answers 404 and is never immutable"
    requirement: "SEC-06"
    verification:
      - kind: command
        ref: "python3 scripts/smoke.py --base http://127.0.0.1 cache (cache-asset-immutable, cache-missing-asset-404)"
        status: pass
      - kind: unit
        ref: "infra/tests/test_compose_invariants.py#test_hashed_assets_are_immutable_only_for_2xx_and_never_fall_back"
        status: pass
    human_judgment: false
  - id: D3
    description: "Every service rotates logs with json-file 10m x 5, no log volume; docker inspect of the running containers shows it"
    requirement: "SEC-06"
    verification:
      - kind: unit
        ref: "infra/tests/test_compose_invariants.py#test_every_service_rotates_its_logs"
        status: pass
      - kind: unit
        ref: "infra/tests/test_compose_invariants.py#test_no_service_writes_logs_to_a_volume"
        status: pass
      - kind: command
        ref: "docker inspect --format '{{json .HostConfig.LogConfig}}' on backend, qbittorrent, web"
        status: pass
    human_judgment: false

duration: 8 min
completed: 2026-10-22
status: complete
---

# Phase 2 Plan 03: Cache headers and log rotation Summary

**Caddy now revalidates index.html and the SPA fallback on every load while hashed `/assets/*` are cached for a year as immutable (2xx only, no fallback), and all three containers log through Docker's json-file driver rotated at 10 MB x 5.**

## Performance

- **Duration:** 8 min
- **Tasks:** 2 (1 tracer, 1 auto)
- **Files modified:** 4

## Accomplishments

- D-42: a phone picks up a redeploy on its next load; `Cache-Control: no-cache` on `/` and `/downloads`, `public, max-age=31536000, immutable` on the hashed JS asset, 404 with no immutable header for a missing asset.
- D-40: one `x-logging` anchor in `docker-compose.yml`, `logging: *default-logging` on `qbittorrent`, `backend`, `web`. `docker inspect` of all three shows `{"Type":"json-file","Config":{"max-file":"5","max-size":"10m"}}`.
- `python3 scripts/smoke.py --base http://127.0.0.1 cache` runs four steps and the leak scan (`OK no-leaks`).
- Infra tests: 63 -> 67 passing (cache blocks parsed by brace depth, per-service rotation, no log volume).

## Task Commits

1. Task 1 (tracer): `933705c` feat(02-03) revalidate index.html and cache hashed assets as immutable
2. Task 2: `a1b6851` feat(02-03) rotate container logs with json-file, 10 MB x 5

Tracer gate: `<verify>` re-run end to end (pytest, web-only rebuild, smoke `cache`) passed before Task 2 started.

## Files Created/Modified

- `web/Caddyfile` - `handle /assets/*` (immutable, 2xx only, no try_files) and a no-cache catch-all
- `docker-compose.yml` - `x-logging` anchor and three `logging` keys
- `infra/tests/test_compose_invariants.py` - four invariant tests (two parametrized to three for logging)
- `scripts/smoke.py` - `run_cache`, `cache` subcommand, docstring updated

## Decisions Made

See `key-decisions`. The shared compose project was touched as the plan says: Task 1 rebuilt only `web` (`--no-deps`), Task 2 ran `docker compose up -d --wait` without `--build`.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. `docker-compose.admin.yml` merged cleanly (`config --quiet` passed) and carries no `x-logging`.

## Known Stubs

None.

## Threat Flags

None. T-02-09 to T-02-11 mitigations applied as planned; `git diff --exit-code -- web/Dockerfile backend/uv.lock frontend/package-lock.json` is clean (T-02-SC).

## Next Phase Readiness

Ready for 02-04.

## Self-Check: PASSED

- web/Caddyfile, docker-compose.yml, infra/tests/test_compose_invariants.py, scripts/smoke.py: FOUND
- Commits 933705c and a1b6851: FOUND in HEAD history
- All acceptance criteria of both tasks re-run and passing; plan verification (`pytest infra/tests`, `docker compose config --quiet`, `smoke.py cache`) green
