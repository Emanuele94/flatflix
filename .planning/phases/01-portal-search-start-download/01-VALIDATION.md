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
| **Quick run command** | `cd backend && uv run pytest -x -q -m "not integration"` and `cd frontend && npx vitest run` |
| **Full suite command** | quick commands plus `uv run pytest infra/tests -q` (repo root) and `caddy validate --config web/Caddyfile --adapter caddyfile` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run the backend quick command (plus vitest if the frontend changed)
- **After every plan wave:** Run the full suite command
- **Before `/gsd-verify-work`:** Full suite must be green, then the manual `docker compose up --build` LAN check
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

Task IDs are filled in by the planner. Requirement-level map (from 01-RESEARCH.md §Validation Architecture):

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD | TBD | TBD | AUTH-01 | — | All routes except login/health 401 without session; 6th failed login → 429 | unit/API | `uv run pytest backend/tests/test_auth.py backend/tests/test_login_throttle.py -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | SEC-01 | — | No response contains qB creds, URL, paths or category names | API | `uv run pytest backend/tests/test_no_leaks.py -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | SEC-02 | — | qBittorrent publishes no non-loopback port | infra | `uv run pytest infra/tests/test_compose_invariants.py -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | SEC-03 | — | Invalid `type` → 422, zero qB calls; client category/path ignored | API | `uv run pytest backend/tests/test_validation.py -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | SEC-04 | — | Placeholder secrets rejected; no LAN IPs tracked; `.env` ignored | unit/infra | `uv run pytest backend/tests/test_config.py infra/tests/test_repo_hygiene.py -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | SRCH-01/02/03 | — | N/A | unit/API | `uv run pytest backend/tests/test_qbit_client.py backend/tests/test_filters.py backend/tests/test_search_flow.py -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | DOWN-01/02/03 | — | Category only from server-side map; result_id, never URL | API | `uv run pytest backend/tests/test_download_pipeline.py backend/tests/test_bootstrap.py -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | FILT-01/02 | — | No non-video/non-subtitle byte downloaded | unit/API | `uv run pytest backend/tests/test_allowlist.py backend/tests/test_download_pipeline.py backend/tests/test_bootstrap.py -k excluded -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | PUI-01/02 | — | UI never shows qB/category/path strings | component | `cd frontend && npx vitest run` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | INFRA-01/02, MEDIA-01 | — | Unique ports, no 8080, media mounts | infra | `uv run pytest infra/tests/test_compose_invariants.py -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `backend/pyproject.toml`, `uv.lock`, `backend/tests/conftest.py` (settings fixture, `FakeQbit`, ASGI client)
- [ ] `backend/tests/fixtures/` with verbatim qB payloads from 01-RESEARCH.md
- [ ] `frontend/vite.config.js` with vitest config + `src/__tests__/`
- [ ] `infra/tests/` (PyYAML) for compose and repo-hygiene invariants
- [ ] Installs: `uv sync`, `npm ci` (after the consolidated package checkpoint)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Whole stack starts | INFRA-01 | Docker not available in the dev WSL distro yet | Enable Docker WSL integration, `docker compose up --build`, all healthchecks healthy |
| Phone end-to-end | PUI-01, DOWN-02 | Needs a real phone on the LAN | Phone logs in, searches, taps Download; file lands in the matching host folder |
| Real qBittorrent flow | FILT-02 | Opt-in integration against pinned image | `QBIT_TEST_URL=… uv run pytest backend/tests/integration -m integration` |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
