---
phase: 01-portal-search-start-download
plan: 01
subsystem: infra
tags: [fastapi, uv, preact, vite, npm, lockfile, docker, gitignore]

requires:
  - phase: none
    provides: first plan of the first phase
provides:
  - Pinned backend manifest (FastAPI 0.159.1) and reviewed uv.lock (35 packages, pypi.org only)
  - Pinned frontend manifest (Preact 11.0.1, Vite 8.3.5) and reviewed package-lock.json (243 packages, registry.npmjs.org only)
  - frontend/.npmrc with ignore-scripts=true
  - Vite config (base '/', /api dev proxy, vitest jsdom)
  - Root .gitignore covering env files, dev password, qbittorrent config, runtime data
  - Human approval of the package set (T-01-SC)
  - Confirmed Docker Engine and Compose v2+ reachable from WSL (D-20)
affects: [01-02, 01-03, 01-04, 01-10, all later phase-1 plans that install packages or run compose]

plan_head_before: f7d891cf068cd9488b1ea2fef192eebe61c1723b
plan_head_after: 3ad5bb8f5b317ca226ad39a58d964ae3a0cf455e

actuals:
  tokens: 42824
  tasks: 3
  commits: 1

tech-stack:
  added: [fastapi 0.159.1, uvicorn 0.54.0, httpx 0.28.1, argon2-cffi 25.1.0, pydantic-settings 2.16.1, itsdangerous 2.2.0, pytest 9.1.1, pytest-asyncio 1.4.0, respx 0.23.1, pyyaml 6.0.3, ruff 0.17.1, preact 11.0.1, vite 8.3.5, "@preact/preset-vite 2.10.6", vitest 5.0.5, "@testing-library/preact 3.2.4", jsdom 30.1.3]
  patterns:
    - "Lockfiles generated without installing (uv lock --no-build, npm --package-lock-only --ignore-scripts)"
    - "Exact version pins in both manifests (no ^ or ~)"
    - "Backend is an application, not a package: [tool.uv] package = false"

key-files:
  created:
    - backend/pyproject.toml
    - backend/uv.lock
    - backend/app/__init__.py
    - frontend/package.json
    - frontend/package-lock.json
    - frontend/.npmrc
    - frontend/vite.config.js
    - .gitignore
  modified: []

key-decisions:
  - "No python-multipart and no uvicorn[standard]: login is JSON and the reviewed package set stays small"
  - "Task 3 verified automatically instead of stopping: Docker already answered from WSL, so no human action was needed"

patterns-established:
  - "Package-legitimacy gate: lockfile review by a human before the first uv sync or npm ci"

requirements-completed: [INFRA-01, SEC-04]

coverage:
  - id: D1
    description: "Backend and frontend manifests pin the researched versions exactly; both lockfiles exist, are consistent with the manifests, and resolve only from pypi.org and registry.npmjs.org; nothing installed"
    requirement: "INFRA-01"
    verification:
      - kind: other
        ref: "uv lock --project backend --check; node check of frontend/package-lock.json resolved hosts and preact 11.0.1; test ! -d backend/.venv; test ! -d frontend/node_modules"
        status: pass
    human_judgment: false
  - id: D2
    description: ".gitignore ignores .env, .env.*, .dev-portal-password, qbittorrent/config/, data/ and keeps !.env.example before any secret exists"
    requirement: "SEC-04"
    verification:
      - kind: other
        ref: "git check-ignore on qbittorrent/config/qBittorrent.conf, .dev-portal-password, data/media/Film/x.mkv; .env and !.env.example lines confirmed by reading the file"
        status: pass
    human_judgment: false
  - id: D3
    description: "A human reviewed and approved the locked package set, including transitive opentelemetry-api 1.45.1 and annotated-doc 0.0.5 pulled in by fastapi 0.159.1 (T-01-SC)"
    requirement: "SEC-04"
    verification: []
    human_judgment: true
    rationale: "Package legitimacy is a human trust decision; recorded as the user's reply 'approved' to the blocking-human checkpoint"
  - id: D4
    description: "Docker Engine 29.7.2 and Docker Compose v5.4.0 reachable from the WSL distro; hello-world runs"
    requirement: "INFRA-01"
    verification:
      - kind: other
        ref: "docker version --format '{{.Server.Version}}'; docker compose version; docker run --rm hello-world"
        status: pass
    human_judgment: false

duration: 6min
completed: 2026-10-22
status: complete
---

# Phase 1 Plan 01: Toolchain and host gate Summary

**Exact-pinned FastAPI and Preact+Vite manifests with human-approved, install-free lockfiles (pypi.org and registry.npmjs.org only), a secrets-first .gitignore, and Docker/Compose confirmed from WSL**

## Performance

- **Duration:** 6 min (this continuation; the first executor run built Task 1 but could not commit on a protected branch)
- **Started:** 2026-10-22T09:56:18Z (approx., from planning HEAD commit time)
- **Completed:** 2026-10-22T10:02:11Z (approx.)
- **Tasks:** 3 of 3
- **Files modified:** 8 (all created)

## Accomplishments
- Both lockfiles generated with no install step: `backend/uv.lock` (35 packages) and `frontend/package-lock.json` (243 packages). `backend/.venv` and `frontend/node_modules` do not exist.
- Every top-level package pinned exactly to the 01-RESEARCH.md versions; `frontend/.npmrc` sets `ignore-scripts=true`.
- `.gitignore` in place before any secret or runtime file exists (T-01-01).
- Package set approved by the user (T-01-SC), including the two transitive packages named below.
- Docker Engine 29.7.2, Compose v5.4.0, and `docker run --rm hello-world` all work from WSL (D-20).

## Task Commits

1. **Task 1: Write manifests and generate lockfiles without installing** - `3ad5bb8` (chore)
2. **Task 2: Package-legitimacy review (checkpoint:human-verify, blocking-human)** - no files; user replied "approved"
3. **Task 3: Confirm Docker Desktop WSL integration (checkpoint:human-action)** - no files; verified automatically, no human step needed

**Plan metadata:** recorded in the docs(01-01) commit that follows this file.

## Files Created/Modified
- `backend/pyproject.toml` - Backend manifest, pytest (asyncio auto, integration marker deselected by default) and ruff config
- `backend/uv.lock` - Reviewed Python lockfile, 35 packages, pypi.org only
- `backend/app/__init__.py` - Package marker with docstring
- `frontend/package.json` - Frontend manifest and scripts (dev, build, test)
- `frontend/package-lock.json` - Reviewed npm lockfile, 243 packages, registry.npmjs.org only
- `frontend/.npmrc` - ignore-scripts, save-exact, engine-strict, no fund
- `frontend/vite.config.js` - base '/', /api proxy to 127.0.0.1:8000, vitest jsdom
- `.gitignore` - Ignore rules for secrets and runtime data

## Decisions Made
- Followed the plan: no python-multipart, no uvicorn[standard].
- Task 3 was a quick confirmation at planning time and still passed at execution time, so it was closed by running the plan's own verification commands rather than stopping for a human.

## Package approval record (T-01-SC)

The user responded "approved" to the blocking-human review of the locked package set. The approval explicitly covers the transitive packages `opentelemetry-api 1.45.1` and `annotated-doc 0.0.5`, which `fastapi 0.159.1` pulls in. Lockfile registries: only `https://pypi.org/simple` and `https://registry.npmjs.org/`.

## Deviations from Plan

None - plan executed exactly as written, apart from process notes under Issues Encountered.

## Issues Encountered
- The first executor run built and verified Task 1 but did not commit, because the commit guard refused the protected branch `main`. The orchestrator created `gsd/phase-01-portal-search-start-download`; this continuation re-ran the Task 1 verification and committed. The commit ledger base (`f7d891c`) was preserved, so `commits: 1` is measured, not narrated.
- The `.env.example` negative `git check-ignore` assertion in Task 1's automated verify was not run from the shell, because a local hook blocks commands naming the env file. As the plan's acceptance criteria allow, it was checked by reading `.gitignore` (lines `.env` and `!.env.example` present). The automated assertion moves to `infra/tests/test_repo_hygiene.py` in plan 01-04.
- Port 80 on Windows could not be probed from WSL. Plan 01-04 needs it free; if it is taken, set `WEB_PORT` in the env file.

## User Setup Required

Docker Desktop WSL integration was already enabled; no action needed. No USER-SETUP.md generated.

## Known Stubs

None.

## Threat Flags

None.

## Next Phase Readiness
- Lockfiles are approved, so `uv sync` and `npm ci` are cleared for 01-03 and 01-10.
- Docker and Compose work from WSL, so compose tasks can proceed.
- Open item: confirm Windows port 80 is free when 01-04 brings the stack up.

---
*Phase: 01-portal-search-start-download*
*Completed: 2026-10-22*

## Self-Check: PASSED
