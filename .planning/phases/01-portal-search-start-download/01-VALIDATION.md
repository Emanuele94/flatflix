---
phase: "1"
slug: "portal-search-start-download"
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: "2026-10-21"
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Backend: pytest 9.1.1 + pytest-asyncio 1.4.0 + respx 0.23.1 (+ `FakeQbit`); Frontend: vitest 5.0.5 + @testing-library/preact 3.2.4 + jsdom; Infra: pytest + PyYAML |
| **Config file** | none — Wave 0 installs (`backend/pyproject.toml`, `frontend/vite.config.js`) |
| **Quick run command** | `uv run --project backend --frozen pytest backend/tests -x -q` and `npm --prefix frontend test` |
| **Full suite command** | quick commands plus `uv run --project backend --frozen pytest infra/tests -q`; real-stack probes `python3 scripts/smoke.py --base http://127.0.0.1 all` and the opt-in `QBIT_TEST_URL=http://127.0.0.1:8088 uv run --project backend --frozen pytest backend/tests/integration -m integration` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run the backend quick command (plus vitest if the frontend changed)
- **After every plan wave:** Run the full suite command
- **Before `/gsd-verify-work`:** Full suite must be green, then the manual `docker compose up --build` LAN check
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

Filled by the planner on 2026-10-22. Commands run from the repo root; backend commands use the lockfile approved in 01-01 (`uv run --project backend --frozen ...`). Plans that start containers (01-10, 01-02, 01-04, 01-05, 01-11, 01-06, 01-07, 01-12, 01-08, 01-13, 01-09) share one Docker daemon and compose project, so each runs in its own wave; 01-03 (no containers) is the only plan sharing a wave, with 01-10. Revised 2026-10-22 after the plan check: the five widest plans were split along the backend/frontend line (and 01-02/01-04 around the qBittorrent container) so every plan stays under 15 files; frontend halves got new numbers 01-10..01-13, so plan numbers are not in execution order: follow the Wave column.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 01-01-T1 | 01-01 | 1 | INFRA-01, SEC-04 | T-01-01, T-01-SC | Lockfiles only from pypi.org / registry.npmjs.org, nothing installed, runtime/secret paths ignored | tooling | `uv lock --project backend --check` + registry/ignore checks (see plan) | ❌ W0 | ⬜ pending |
| 01-01-T2 | 01-01 | 1 | SEC-04 | T-01-SC | Human package-legitimacy review before first install (gate blocking-human) | manual | — | n/a | ⬜ pending |
| 01-01-T3 | 01-01 | 1 | INFRA-01 | — | Docker Desktop WSL integration confirmed (D-20) | manual + CLI | `docker compose version` | n/a | ⬜ pending |
| 01-10-T1 | 01-10 | 2 | INFRA-01, SEC-02, SEC-04, MEDIA-01 | T-01-02, T-01-05, T-01-39, T-01-40, T-01-41 | qB unpublished and only on qbit; env credentials accepted and a wrong password refused from a non-loopback address; host dirs owned by PUID:PGID; nothing secret printed | e2e (tracer) | `uv run --project backend --frozen python scripts/dev_env.py --check` + `docker compose up -d --wait` then `docker compose exec -T qbittorrent python3 - < scripts/qbit_login_check.py` | ❌ W0 | ⬜ pending |
| 01-10-T2 | 01-10 | 2 | SEC-02, INFRA-02, MEDIA-01 | T-01-11 | Admin override publishes only 127.0.0.1:8088; base stack restored with nothing published; one port map doc, no 8080 | e2e + docs | admin `up --wait`, `docker compose port qbittorrent 8088` = `127.0.0.1:8088`, curl the WebUI, then base `up --wait` (see plan) | n/a | ⬜ pending |
| 01-03-T1 | 01-03 | 2 | FILT-02 | T-01-07 | Only allowed video/subtitle indexes kept | unit (tracer) | `uv run --project backend --frozen pytest backend/tests/test_allowlist.py -q` | ❌ W0 | ⬜ pending |
| 01-03-T2 | 01-03 | 2 | FILT-02, FILT-01 | T-01-07 | Double extensions, case, samples, no-video rejection; exact FILT-01 tuple | unit | `uv run --project backend --frozen pytest backend/tests/test_allowlist.py -q` | ❌ W0 | ⬜ pending |
| 01-03-T3 | 01-03 | 2 | SRCH-02 | T-01-08 | Dead/fake/suspicious results hidden; stable dedupe and order | unit | `uv run --project backend --frozen pytest backend/tests/test_filters.py backend/tests/test_allowlist.py -q` | ❌ W0 | ⬜ pending |
| 01-02-T1 | 01-02 | 3 | INFRA-01, SEC-02, SEC-04 | T-01-02, T-01-03, T-01-06 | qB and backend unpublished; health body minimal; backend runs as uid 10001 | unit + e2e | `uv run --project backend --frozen pytest backend/tests/test_health.py -q` then compose health inside backend | ❌ W0 | ⬜ pending |
| 01-02-T2 | 01-02 | 3 | SEC-01 | T-01-03, T-01-04 | No credential in logs/repr; one re-login; no self-inflicted qB ban | unit | `uv run --project backend --frozen pytest backend/tests/test_qbit_client.py backend/tests/test_health.py -q` | ❌ W0 | ⬜ pending |
| 01-04-T1 | 01-04 | 4 | INFRA-01, PUI-01 | T-01-09, T-01-10, T-01-13 | Same-origin SPA, CSP self, no third-party resource, env file outside image | component + e2e | `npm --prefix frontend test` then curl through Caddy (see plan) | ❌ W0 | ⬜ pending |
| 01-04-T2 | 01-04 | 4 | SEC-02, INFRA-02, MEDIA-01, SEC-04 | T-01-11, T-01-12 | qB publish only 127.0.0.1 in admin override; unique ports, no 8080; no LAN IPs/secrets tracked | infra | `uv run --project backend --frozen pytest infra/tests -q` | ❌ W0 | ⬜ pending |
| 01-05-T1 | 01-05 | 5 | AUTH-01 | T-01-14, T-01-17, T-01-18 | 30-day HttpOnly SameSite=Lax cookie; JSON-only login | API + e2e | `uv run --project backend --frozen pytest backend/tests/test_auth.py -q` then `python3 scripts/smoke.py --base http://127.0.0.1 login` | ❌ W0 | ⬜ pending |
| 01-05-T2 | 01-05 | 5 | AUTH-01 | T-01-14, T-01-16, T-01-19 | Deny by default (route enumeration); 6th attempt in 15 min -> 429 | unit/API | `uv run --project backend --frozen pytest backend/tests/test_login_throttle.py backend/tests/test_routes_protected.py backend/tests/test_auth.py -q` | ❌ W0 | ⬜ pending |
| 01-05-T3 | 01-05 | 5 | SEC-04 | T-01-15 | Placeholder/empty/short secrets refused; argon2id hash helper | unit | `uv run --project backend --frozen pytest backend/tests/test_config.py -q` | ❌ W0 | ⬜ pending |
| 01-11-T1 | 01-11 | 6 | AUTH-01, PUI-01 | T-01-43 | Login screen first; served bundle wired to /api/login and /api/session; no web-storage use | component + e2e | `npm --prefix frontend test` then rebuild, served-bundle check and `python3 scripts/smoke.py --base http://127.0.0.1 login` (see plan) | ❌ W0 | ⬜ pending |
| 01-11-T2 | 01-11 | 6 | PUI-02, AUTH-01 | T-01-42, T-01-43 | 401 anywhere -> login; English messages only; no credentials stored | component | `npm --prefix frontend test` | ❌ W0 | ⬜ pending |
| 01-06-T1 | 01-06 | 7 | DOWN-03, FILT-01, INFRA-01 | T-01-21, T-01-23 | Categories/paths/temp/auto TMM/exclusions set on real qB; doctor prints no secrets | unit + e2e | `uv run --project backend --frozen pytest backend/tests/test_bootstrap.py -q` then `docker compose exec -T backend python -m app.tools.doctor --wait 90` | ❌ W0 | ⬜ pending |
| 01-06-T2 | 01-06 | 7 | DOWN-03, FILT-01 | T-01-22, T-01-24 | Idempotent, ordered; 503 not_ready until bootstrapped; no retry loop on auth errors | unit | `uv run --project backend --frozen pytest backend/tests/test_bootstrap.py backend/tests/test_qbit_client.py backend/tests/test_health.py -q` | ❌ W0 | ⬜ pending |
| 01-06-T3 | 01-06 | 7 | DOWN-03 | T-01-20 | Plugins only from pinned official SHA; seeding limits read back | unit + e2e | `uv run --project backend --frozen pytest backend/tests/test_bootstrap.py -q` then doctor `--wait 120` | ❌ W0 | ⬜ pending |
| 01-07-T1 | 01-07 | 8 | SRCH-01, SRCH-02, SRCH-03, PUI-02 | T-01-29 | DTO whitelist (no URLs/categories to the browser) | API + e2e | `uv run --project backend --frozen pytest backend/tests/test_search_flow.py -q` then smoke `search` | ❌ W0 | ⬜ pending |
| 01-07-T2 | 01-07 | 8 | SEC-03, SRCH-03 | T-01-25, T-01-26, T-01-27 | Strict type/query; zero qB calls on bad input; timeout/cleanup; search never adds torrents | API | `uv run --project backend --frozen pytest backend/tests/test_search_flow.py backend/tests/test_validation.py backend/tests/test_qbit_client.py backend/tests/test_routes_protected.py -q` | ❌ W0 | ⬜ pending |
| 01-12-T1 | 01-12 | 9 | SRCH-01, SRCH-03, PUI-01 | T-01-44 | Polling stops on done/new search/unmount; served bundle wired to /api/search | component + e2e | `npm --prefix frontend test` then rebuild, served-bundle check and smoke `search` (see plan) | ❌ W0 | ⬜ pending |
| 01-12-T2 | 01-12 | 9 | PUI-01, PUI-02, SRCH-02 | T-01-28 | Names rendered as text (XSS); English states only | component | `npm --prefix frontend test` | ❌ W0 | ⬜ pending |
| 01-08-T1 | 01-08 | 10 | DOWN-01, DOWN-02, DOWN-03, FILT-02 | T-01-30, T-01-32, T-01-33 | Category only from type; stopCondition=MetadataReceived; priorities verified before start; real-engine guard | API + integration | `uv run --project backend --frozen pytest backend/tests/test_download_pipeline.py -q` then integration with `QBIT_TEST_URL=http://127.0.0.1:8088` | ❌ W0 | ⬜ pending |
| 01-08-T2 | 01-08 | 10 | FILT-02, SEC-03, DOWN-01 | T-01-31, T-01-34, T-01-35 | No-video deleted before start; reconcile; double-tap dedupe; body {status, job_id} | API | `uv run --project backend --frozen pytest backend/tests/test_download_pipeline.py backend/tests/test_validation.py backend/tests/test_routes_protected.py -q` | ❌ W0 | ⬜ pending |
| 01-13-T1 | 01-13 | 11 | DOWN-01, SEC-03 | T-01-46 | Row posts exactly {result_id, type}; served bundle wired to /api/download; 401 through Caddy without a session | component + e2e | `npm --prefix frontend test` then rebuild, served-bundle check and the 401 probe (see plan) | ❌ W0 | ⬜ pending |
| 01-13-T2 | 01-13 | 11 | PUI-02, DOWN-01 | T-01-45, T-01-47 | Success shown only for status started; job polling bounded | component | `npm --prefix frontend test` | ❌ W0 | ⬜ pending |
| 01-09-T1 | 01-09 | 12 | SEC-01, PUI-02, DOWN-03, MEDIA-01 | T-01-36, T-01-37 | Canary scan over every route; real-stack smoke leak scan | API + e2e | `uv run --project backend --frozen pytest backend/tests/test_no_leaks.py backend/tests/test_config.py -q` then `python3 scripts/smoke.py --base http://127.0.0.1 all` | ❌ W0 | ⬜ pending |
| 01-09-T2 | 01-09 | 12 | INFRA-01, SEC-04 | T-01-38 | Docs use placeholders; Private-profile firewall rule only | docs + infra | `uv run --project backend --frozen pytest infra/tests/test_repo_hygiene.py -q` | ❌ W0 | ⬜ pending |
| 01-09-T3 | 01-09 | 12 | SEC-04, PUI-01, AUTH-01 | — | Instructions match D-23; full suite green; commit staged by explicit path (exactly 3 files); phone check harvested into 01-UAT.md | docs + full suite + human-check | `uv run --project backend --frozen pytest backend/tests infra/tests -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `backend/pyproject.toml` (pytest config, markers), `uv.lock` — 01-01-T1
- [ ] `frontend/vite.config.js` with vitest jsdom config — 01-01-T1; first `src/__tests__/` files — 01-04-T1
- [ ] `backend/tests/conftest.py` (settings, `fake_qbit`, `app`, `api` fixtures) and `backend/tests/fakeqbit.py` — 01-02-T1/T2 (extended by 01-06, 01-07, 01-08)
- [ ] Verbatim qB payload fixtures (search row, file rows) — inline in test_filters.py / test_allowlist.py (01-03)
- [ ] `infra/tests/` (PyYAML) compose and repo-hygiene invariants — 01-04-T2
- [ ] Installs: first `uv sync`/`npm ci` only after the consolidated package checkpoint 01-01-T2

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Package legitimacy | SEC-04 (T-01-SC) | Human trust decision | 01-01-T2 checkpoint (blocking-human) |
| Docker Desktop WSL integration | INFRA-01 (D-20) | Windows GUI setting | 01-01-T3 checkpoint; at planning time Docker already answered from WSL |
| Phone end-to-end on the LAN | AUTH-01, PUI-01, DOWN-02, DOWN-03, MEDIA-01 (ROADMAP success criterion 1) | Real phone, Windows firewall, tap usability | 01-09-T3 human-check plus the matching backstop truth in 01-09: log in, search, tap Download, file appears in the Film host folder only after completion. Harvested at end of phase into 01-UAT.md (`workflow.human_verify_mode` end-of-phase, the default); the phase stays `human_needed` and cannot be marked passed, by execute-phase or `/gsd-autonomous`, until it is recorded |

Docker became available in the dev distro on 2026-10-22, so INFRA-01 (`docker compose up --build --wait`) is now automated inside the tracer verifies instead of manual-only.

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
