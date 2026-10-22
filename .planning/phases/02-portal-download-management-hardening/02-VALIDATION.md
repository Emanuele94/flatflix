---
phase: "02"
slug: "portal-download-management-hardening"
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: "2026-10-22"
---

# Phase 02 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Backend: pytest 9.1.1 + pytest-asyncio + respx with `FakeQbit`; Frontend: vitest 5.0.5 + @testing-library/preact + jsdom; Infra: pytest + PyYAML |
| **Config file** | `backend/pyproject.toml`, `frontend/vite.config.js` |
| **Quick run command** | `uv run --project backend --frozen pytest backend/tests -x -q` (plus `npm --prefix frontend test` when frontend files changed) |
| **Full suite command** | `uv run --project backend --frozen pytest backend/tests -q && uv run --project backend --frozen pytest infra/tests -q && npm --prefix frontend test` |
| **Estimated runtime** | ~40 seconds |

---

## Sampling Rate

- **After every task commit:** Run the quick run command
- **After every plan wave:** Run the full suite command
- **Before `/gsd-verify-work`:** Full suite green, `docker compose up -d --build --wait`, doctor, `python3 scripts/smoke.py --base http://127.0.0.1 all` and the new `cache` probe
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD (filled by planner) | — | — | DOWN-04 | — | Only exact `Film`/`SerieTV` torrents listed; plain states only | unit + API | `uv run --project backend --frozen pytest backend/tests/test_download_listing.py backend/tests/test_downloads_api.py -q` | ❌ W0 | ⬜ pending |
| TBD | — | — | DOWN-04 | — | Polling only while tab visible; stale list greyed with banner | component | `npm --prefix frontend test -- Downloads` | ❌ W0 | ⬜ pending |
| TBD | — | — | DOWN-05 | — | Opaque id; server picks `deleteFiles` from live state; non-Film/SerieTV refused | API | `uv run --project backend --frozen pytest backend/tests/test_downloads_api.py backend/tests/test_download_cancel.py -q` | ❌ W0 | ⬜ pending |
| TBD | — | — | DOWN-06 | — | qBittorrent credential failure never surfaces as 401; no raw text in DOM | API + component | `uv run --project backend --frozen pytest backend/tests/test_downloads_api.py -q && npm --prefix frontend test` | ❌ W0 | ⬜ pending |
| TBD | — | — | SEC-05 | — | 11th search / 21st download per minute gets 429; polls never throttled | API | `uv run --project backend --frozen pytest backend/tests/test_rate_limit.py -q` | ❌ W0 | ⬜ pending |
| TBD | — | — | SEC-06 | — | Audit lines with client IP; canary secrets never logged | API + caplog | `uv run --project backend --frozen pytest backend/tests/test_audit.py -q` | ❌ W0 | ⬜ pending |
| TBD | — | — | SEC-06 / D-42 | — | json-file rotation on every service; Caddy cache headers | infra | `uv run --project backend --frozen pytest infra/tests -q` | partial | ⬜ pending |
| TBD | — | — | D-43 | — | Non-allowlisted main video rejected as unsupported | unit | `uv run --project backend --frozen pytest backend/tests/test_allowlist.py -q` | ✅ extend | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `backend/tests/fakeqbit.py` — richer `torrents/info` rows (name, progress, eta, completion_on, size, state override, arbitrary category, admin-added helper, failure injection)
- [ ] `backend/tests/test_download_listing.py`, `test_downloads_api.py`, `test_download_cancel.py`, `test_rate_limit.py`, `test_audit.py`
- [ ] `frontend/src/__tests__/Downloads.test.jsx`, `DownloadRow.test.jsx`, `eta.test.js`; extend `App.test.jsx`, `Search.test.jsx`
- [ ] `infra/tests` additions for logging rotation and Caddy headers; `scripts/smoke.py` `cache` subcommand

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Follow and cancel a download on a real phone | DOWN-04, DOWN-05 | Real device, real torrent | Start a Blender download, open Downloads, watch progress, cancel, confirm it is gone from qBittorrent |
| Outage banner and recovery | DOWN-06 | Needs container stop/start | `docker compose stop qbittorrent`, watch banner, `docker compose start qbittorrent`, banner clears |
| Phone picks up new version after redeploy | D-42 | Real phone cache | Redeploy, reload on phone, new UI appears without clearing cache |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
