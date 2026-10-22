---
phase: 01-portal-search-start-download
plan: 04
subsystem: infra
tags: [caddy, preact, vite, vitest, docker-compose, pytest, csp]

requires:
  - phase: 01-portal-search-start-download
    provides: "01-02 backend service with GET /api/health and networks edge + qbit; 01-10 admin override, docs/ports-and-media.md, .env.example; 01-01 approved frontend lockfile"
provides:
  - "web/Dockerfile and web/Caddyfile: node:24.15-alpine build stage into caddy:2.11.7-alpine, SPA at /, /api/* proxied to backend:8000, /tv/* and /jellyfin/* reserved with 404, CSP default-src 'self' and security headers"
  - "docker-compose.yml service web: the only published port (${WEB_PORT:-80}:80), edge network only, waits for backend healthy"
  - "Root .dockerignore allowlist (*, !frontend/, !web/Caddyfile) keeping the env file, qbittorrent/config and data/ out of the image"
  - "frontend shell: index.html (lang it, viewport), main.jsx, App.jsx health banner, api.js (api, ApiError), messages.js (MSG), styles.css"
  - "infra/tests: Docker-free compose invariants (published_host_ip, check_qbittorrent_ports) and repo hygiene scanners (find_lan_ips, find_secret_material)"
affects: [01-05, 01-06, 01-07, 01-08, 01-09, 01-11, 01-12, 01-13]

plan_head_before: 574039b8cb4b831eef7dff63db76f1b2f8545006
plan_head_after: 68a8357e9e0af2b4d50df42cb42c84dcdd10808f

actuals:
  tokens: 6857
  tasks: 2
  commits: 3

tech-stack:
  added: ["node:24.15-alpine (pinned image, build stage)", "caddy:2.11.7-alpine (pinned image)"]
  patterns:
    - "Single origin: Caddy serves the SPA, proxies /api/*, reserves /tv and /jellyfin; no CORS anywhere"
    - "CSP default-src 'self' means no inline style= attributes and no third-party URL; enforced by no-third-party.test.js"
    - "Compose rules enforced as plain-YAML tests; host IP compared by exact string equality"
    - "Hygiene scanners keep their own source free of full addresses by building synthetic samples at run time"

key-files:
  created:
    - web/Dockerfile
    - web/Caddyfile
    - .dockerignore
    - frontend/index.html
    - frontend/src/main.jsx
    - frontend/src/App.jsx
    - frontend/src/api.js
    - frontend/src/messages.js
    - frontend/src/styles.css
    - frontend/src/__tests__/App.test.jsx
    - frontend/src/__tests__/no-third-party.test.js
    - infra/tests/test_compose_invariants.py
    - infra/tests/test_repo_hygiene.py
  modified:
    - docker-compose.yml

key-decisions:
  - "Hygiene scanner derives the private blocks from (octet, octet, prefix) tuples: the first GREEN run flagged the test file's own network literals, which is exactly the self-flagging trap the plan warned about"
  - "Hygiene git calls run with cwd at the repo root, not the test directory: relative paths such as .env.example were resolved against infra/tests and gave false failures"
  - "App.jsx treats any non-ApiError rejection as degraded and any ApiError (including HTTP errors from Caddy when the backend is down) as unreachable, so the household sees one of the three planned messages and never a technical string"

patterns-established:
  - "UI copy only in frontend/src/messages.js; later plans add keys"
  - "Frontend calls go through api(); ApiError.status is 0 for network failures and .code is the backend detail string or 'network'"

requirements-completed: [INFRA-02, SEC-02, SEC-04, MEDIA-01, PUI-01]
# INFRA-01 is declared by this plan but not marked: requirements.ready-ids did not list it as ready.

coverage:
  - id: D1
    description: "Caddy on host port 80 serves the SPA at / with fallback for /search and /login, proxies /api/* to the backend on the same origin, answers 404 on the reserved /tv/* and /jellyfin/*"
    requirement: "INFRA-01"
    verification:
      - kind: integration
        ref: "Plan verify command: docker compose up -d --build --wait; curl / and /search contain id=app; /api/health contains \"qbittorrent\":\"up\"; /tv/ is 404; CSP header present (re-run once as the tracer gate, all pass). /login and /jellyfin/x also checked by hand (id=app and 404)"
        status: pass
    human_judgment: false
  - id: D2
    description: "The portal page shows backend status in Italian for ok, degraded and unreachable"
    requirement: "PUI-01"
    verification:
      - kind: unit
        ref: "frontend/src/__tests__/App.test.jsx (three tests: Portale pronto, Servizio in avvio, Server non raggiungibile)"
        status: pass
    human_judgment: false
  - id: D3
    description: "Page is phone-usable: viewport meta, lang it, controls at least 48 px tall"
    requirement: "PUI-01"
    verification:
      - kind: unit
        ref: "frontend/src/__tests__/no-third-party.test.js#index.html is Italian and mobile-ready (lang and width=device-width only)"
        status: pass
      - kind: other
        ref: "styles.css sets min-height 48px on button, input, select and max-width 40rem with no fixed widths; no browser check at 360 px was run"
        status: unknown
    human_judgment: true
    rationale: "No headless-browser check of horizontal scroll at 360 px exists. The CSS follows the rule, but a person should open the page on a phone (01-09 covers LAN reachability)."
  - id: D4
    description: "No third-party resource: index.html and src contain no http(s) URL and Caddy sends a same-origin Content-Security-Policy"
    requirement: "SEC-04"
    verification:
      - kind: unit
        ref: "frontend/src/__tests__/no-third-party.test.js#index.html and src contain no http(s) URL"
        status: pass
      - kind: integration
        ref: "curl -I http://127.0.0.1/ prints Content-Security-Policy: default-src 'self' ... frame-ancestors 'none'; X-Frame-Options DENY; no Server header"
        status: pass
    human_judgment: false
  - id: D5
    description: "qBittorrent publish rule is exact at the edge: only 127.0.0.1 entries pass; 8088:8088, 0.0.0.0, 127.0.0.10, 127.0.0.1.nip.io, [::] and long syntax without host_ip fail; absent and empty ports both count as unpublished; a bad entry fails in any position"
    requirement: "SEC-02"
    verification:
      - kind: unit
        ref: "infra/tests/test_compose_invariants.py (test_published_host_ip_is_exact, test_non_loopback_entry_fails, test_loopback_entry_passes_the_boundary, test_absent_or_empty_ports_are_unpublished, test_bad_entry_fails_wherever_it_sits)"
        status: pass
    human_judgment: false
  - id: D6
    description: "Base stack publishes only web; admin override adds only loopback ports to qbittorrent; qbittorrent and web share no network; docker compose port qbittorrent 8088 shows nothing outside 127.0.0.1"
    requirement: "SEC-02"
    verification:
      - kind: unit
        ref: "infra/tests/test_compose_invariants.py::test_only_web_publishes_a_port, test_qbittorrent_publishes_nothing_in_the_base_stack, test_admin_override_only_adds_loopback_ports_to_qbittorrent, test_qbittorrent_and_web_share_no_network"
        status: pass
      - kind: integration
        ref: "docker compose -f docker-compose.yml -f docker-compose.admin.yml config --quiet exits 0; docker compose port qbittorrent 8088 in the running base stack prints no published port"
        status: pass
      - kind: other
        ref: "Behaviour of docker compose port while the backend restarts (concurrency edge) was not exercised; no restart test was run"
        status: unknown
    human_judgment: true
    rationale: "The plan marks the restart edge as a backstop. Publishing is static compose config, so a restart cannot change it, but nothing here ran that check."
  - id: D7
    description: "Port map and media contract enforced without Docker: unique host ports, no 8080, WEBUI_PORT distinct from the other services and equal to the QBITTORRENT_URL port, media binds refuse missing folders, incomplete folder outside MEDIA_ROOT, pinned images"
    requirement: "INFRA-02"
    verification:
      - kind: unit
        ref: "infra/tests/test_compose_invariants.py (test_host_ports_are_unique_across_base_and_admin, test_port_8080_is_used_nowhere, test_webui_port_avoids_the_other_services, test_media_binds_refuse_missing_host_folders[3], test_incomplete_folder_lives_outside_media_root, test_images_are_pinned_and_compose_is_versionless)"
        status: pass
    human_judgment: false
  - id: D8
    description: "Startup order and health: web waits for backend healthy, backend waits for qbittorrent healthy, every service has a healthcheck, qBittorrent's never calls /api/v2"
    requirement: "INFRA-01"
    verification:
      - kind: unit
        ref: "infra/tests/test_compose_invariants.py::test_startup_order_is_enforced_by_health, test_every_service_has_a_healthcheck_and_qbittorrent_stays_unauthenticated"
        status: pass
    human_judgment: false
  - id: D9
    description: "Repo hygiene: env file ignored and untracked, example tracked, generated secrets ignored, placeholders only, no private/link-local/CGNAT address and no complete argon2id or qBittorrent hash in any tracked text file, all offenders reported together"
    requirement: "SEC-04"
    verification:
      - kind: unit
        ref: "infra/tests/test_repo_hygiene.py (scanner unit tests plus test_local_env_file_is_ignored_and_untracked, test_env_example_is_tracked_and_not_ignored, test_generated_secrets_are_ignored[2], test_secret_like_example_values_are_placeholders, test_no_tracked_file_contains_a_lan_address, test_no_tracked_file_contains_a_complete_password_hash)"
        status: pass
    human_judgment: false
  - id: D10
    description: "The web image does not carry the env file, qbittorrent/config or data/"
    requirement: "SEC-04"
    verification:
      - kind: integration
        ref: "docker compose exec -T web ls /srv/portal shows only assets and index.html; .dockerignore first non-comment line is *, with !frontend/ and !web/Caddyfile"
        status: pass
      - kind: other
        ref: "Image layers were not listed to prove no env file is present; the build COPY lines only take frontend/ and web/Caddyfile, so the allowlist plus those lines make it structurally absent"
        status: unknown
    human_judgment: false

duration: 8min
completed: 2026-10-22
status: complete
---

# Phase 1 Plan 04: Caddy Portal Tracer and Infra Invariant Tests Summary

**Caddy now serves the Preact portal on host port 80 with same-origin /api proxying, a reserved /tv and /jellyfin, a strict CSP and an allowlist .dockerignore, and 59 Docker-free tests pin the port map, media contract and repo hygiene so qBittorrent can never be published to the LAN or a secret slip into the public repo without a failure.**

## Performance

- **Duration:** about 8 min (start time was not captured at launch; estimated from file timestamps)
- **Completed:** 2026-10-22T10:25Z
- **Tasks:** 2 (one tracer, one TDD task)
- **Files modified:** 14 (13 created, docker-compose.yml modified)

## Accomplishments

- Tracer proven end to end before expansion: `http://127.0.0.1/` and `/search` and `/login` return the SPA, `/api/health` through Caddy returns `{"status":"ok","qbittorrent":"up"}`, `/tv/` and `/jellyfin/x` answer 404, the CSP and X-Frame-Options headers are present, and the `Server` header is removed. The full verify command was re-run once as the tracer gate with the same result (`Tracer verified end-to-end, expanding`).
- Host port 80 bound without conflict (`0.0.0.0:80->80/tcp`), so the open item from 01-01 needed no WEB_PORT override on this machine. Reachability from a phone on the LAN (Windows firewall) is still for the human in 01-09.
- 59 infra tests pass: exact host-IP parsing, the SEC-02 publish rule, network adjacency, port uniqueness and no 8080, health chain, media binds, pinned images, ignored env file, placeholder-only secrets, no LAN addresses or full password hashes in any tracked file.
- Frontend: 5 vitest tests pass (three health messages, no http(s) URL anywhere in src, lang and viewport).

## Task Commits

1. **Task 1: Tracer, Caddy serves the SPA and proxies /api** - `fb937e8` (feat)
2. **Task 2: Compose invariants and repo hygiene** (TDD)
   - RED: `e5b2945` (test)
   - GREEN: `68a8357` (feat)

## TDD Gate Compliance

- RED: the helper functions `published_host_ip`, `check_qbittorrent_ports`, `find_lan_ips` and `find_secret_material` live inside the test files (plan design), so the RED commit carries the full tests with stub helpers that return `None` or `[]`. Result: 24 failed, 35 passed. The failures are the helper tests (parametrized host-IP cases, non-loopback entries, bad-entry-position cases, private-range scanner cases, hash scanner), each on the planned assertion. `gsd_run check tdd-red-evidence` on the JUnit XML with target `test_bad_entry_fails_wherever_it_sits` returned `RED_EVIDENCE_OK` (`target_test_failed`). A first attempt with the parametrized `test_published_host_ip_is_exact` as target returned `INVALID_RED / no_target_test_failure` only because parametrized IDs were not given in the emitted form; the non-parametrized target was used instead.
- Semantic assessment: the target called `check_qbittorrent_ports([bad, good])`, expected one violation and got `[]` from the stub, which is the intended reason. The 35 tests that passed in RED are the repo-state tests (compose files, `.gitignore`, `.env.example`, tracked-tree scans) and the "ignores public addresses" cases. They pass against configuration that already exists from 01-02 and 01-10 by design, and the stubbed scanners cannot flag anything. This is the unexpected-green case from the fail-fast rules, investigated and accepted: this task adds enforcement for existing artifacts, so only the new helpers can start red.
- The first RED run also showed two failures that were test bugs, not RED: `_git` ran with cwd `infra/tests`, so `git check-ignore .env.example` was evaluated against the wrong directory. Fixed (cwd is the repo root) before the RED commit, and the evidence above comes from the fixed run.
- GREEN: real helpers restored. First run: 58 passed, 1 failed (the tracked-file LAN scan flagged the five network literals inside `test_repo_hygiene.py`). Fixed in the same GREEN commit by deriving the blocks from tuples. Final: 59 passed.
- REFACTOR: none.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Hygiene test resolved git paths against the wrong directory**
- **Found during:** Task 2 (RED run)
- **Issue:** `_git` used `Path(__file__).parent` as cwd, so relative paths like `.env.example` and `qbittorrent/config/...` were checked from `infra/tests` and reported as not tracked or not ignored.
- **Fix:** `_git` runs from the repo root; the root is found with a separate bootstrap `git rev-parse`.
- **Files modified:** infra/tests/test_repo_hygiene.py
- **Commit:** e5b2945 (fixed before commit)

**2. [Rule 1 - Bug] Hygiene scan flagged its own source**
- **Found during:** Task 2 (GREEN run)
- **Issue:** the `PRIVATE_NETWORKS` list wrote the five blocks as full dotted quads, which the tracked-tree scan then reported.
- **Fix:** blocks stored as `(octet, octet, prefix)` tuples and the networks built at import time.
- **Files modified:** infra/tests/test_repo_hygiene.py
- **Commit:** 68a8357

No deviation changed scope or touched files outside the plan's list.

## Authentication Gates

None.

## Known Stubs

None. The `/tv/*` and `/jellyfin/*` 404 responses are intentional reservations for Phases 5 and 3 and are commented as such in `web/Caddyfile`; they are not recorded in the broken-windows ledger.

## Issues Encountered

- Windows host port 80 (open item from 01-01): bound without error by Docker Desktop on first `up`, so no WEB_PORT change was needed here.
- `docker compose ps` shows `8080/tcp` for qbittorrent. That is the image's EXPOSE metadata only (documented in docs/ports-and-media.md); the invariant test checks the compose configuration, not image metadata.

## Next Phase Readiness

- Later plans can call `api()` and add keys to `MSG`; new routes must live under `/api/*` to reach the backend through Caddy.
- Any new service or published port must fit the invariants: a new published port, a use of 8080 or a second service on both networks fails `infra/tests`. Update `docs/ports-and-media.md` and the tests together.
- The Caddy `:80` site has no TLS; plain HTTP on the home LAN is the planned posture.

## Self-Check: PASSED

- Files: all 13 created files and docker-compose.yml present; commits fb937e8, e5b2945 and 68a8357 are ancestors of HEAD.
