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
- **Before `/gsd-verify-work`:** Full suite green, `docker compose up -d --build --wait`, doctor, `python3 scripts/smoke.py --base http://127.0.0.1 all` and the new `cache` and `downloads` probes
- **Image rebuilds:** only on a tree no parallel plan is editing: 02-03 rebuilds the web image only (wave 1), 02-09 the backend image only (wave 4), 02-11 the whole stack (wave 5, alone); no wave-2 or wave-3 plan touches docker
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 02-01 T1-T3 | 02-01 | 1 | DOWN-04, DOWN-06 | T-02-01..05 | Only exact `Film`/`SerieTV` torrents listed; plain states only; 502 codes, never 401 | unit + API | `uv run --project backend --frozen pytest backend/tests/test_download_listing.py backend/tests/test_downloads_api.py backend/tests/test_no_leaks.py backend/tests/test_config.py -q` | ❌ created in task | ⬜ pending |
| 02-02 T1-T2 | 02-02 | 1 | DOWN-06 (D-43) | T-02-06..08 | Non-allowlisted main video rejected as unsupported; 415 unavailable; 409 drift failed | unit + pipeline | `uv run --project backend --frozen pytest backend/tests/test_allowlist.py backend/tests/test_download_pipeline.py -q` | ✅ extend | ⬜ pending |
| 02-03 T1-T2 | 02-03 | 1 | SEC-06 (D-40, D-42) | T-02-09..11 | json-file rotation on every service; Caddy cache headers | infra + smoke | `uv run --project backend --frozen pytest infra/tests -q && docker compose up -d --build --no-deps --wait web && python3 scripts/smoke.py --base http://127.0.0.1 cache` | partial | ⬜ pending |
| 02-04 T1-T2 | 02-04 | 2 | DOWN-04 | T-02-12..14 | Failed jobs 24 h; each download listed once | unit + API | `uv run --project backend --frozen pytest backend/tests/test_download_listing.py backend/tests/test_downloads_api.py -q` | ✅ from 02-01 | ⬜ pending |
| 02-05 T1-T2 | 02-05 | 2 | SEC-05 | T-02-15..18 | 11th search / 21st download per minute gets 429; polls never throttled | API | `uv run --project backend --frozen pytest backend/tests/test_rate_limit.py backend/tests/test_login_throttle.py -q` | ❌ created in task | ⬜ pending |
| 02-06 T1-T3 | 02-06 | 2 | DOWN-04, DOWN-06 | T-02-19..22 | Polling only while tab visible; stale list greyed with banner; no raw text in DOM | component + build | `npm --prefix frontend test && npm --prefix frontend run build` (no docker in wave 2; live list probe in 02-11) | ❌ created in task | ⬜ pending |
| 02-07 T1-T3 | 02-07 | 3 | DOWN-05, DOWN-06 | T-02-23..28 | Opaque id; server picks `deleteFiles` from live state; the list's `action` is `cancel` only when DELETE deletes files; non-Film/SerieTV refused; no 401 on qBittorrent refusal | unit + API | `uv run --project backend --frozen pytest backend/tests/test_downloads_api.py backend/tests/test_download_listing.py backend/tests/test_download_cancel.py -q` | ❌ created in task | ⬜ pending |
| 02-08 T1-T2 | 02-08 | 3 | SEC-05, DOWN-06 | T-02-29..30 | 429 and cancelled read as plain, retryable messages; messages.js unchanged since 02-06 (fail-closed git gate) | component | `npm --prefix frontend test` | ✅ extend | ⬜ pending |
| 02-09 T1-T3 | 02-09 | 4 | SEC-06 | T-02-31..36 | Audit lines with client IP; canary secrets never logged; backend image rebuilt alone (`--no-deps backend`) | API + log capture | `uv run --project backend --frozen pytest backend/tests/test_audit.py -q` | ❌ created in task | ⬜ pending |
| 02-10 T1-T2 | 02-10 | 4 | DOWN-05, DOWN-06 | T-02-37..39 | One confirm, one DELETE with the opaque id only; disabled during outage | component | `npm --prefix frontend test` | ✅ from 02-06 | ⬜ pending |
| 02-11 T1-T2 | 02-11 | 5 | all | T-02-40..42 | Real-engine list and cancel; live `smoke downloads` probe through Caddy; full gate; docs; end-of-phase phone check | integration + smoke + human | `QBIT_TEST_URL=http://127.0.0.1:8088 uv run --project backend --frozen pytest backend/tests/integration -m integration -q && python3 scripts/smoke.py --base http://127.0.0.1 downloads` | ❌ created in task | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `backend/tests/fakeqbit.py` — richer `torrents/info` rows (name, progress, eta, completion_on, size, state override, arbitrary category, admin-added helper, failure injection)
- [ ] `backend/tests/test_download_listing.py`, `test_downloads_api.py`, `test_download_cancel.py`, `test_rate_limit.py`, `test_audit.py`
- [ ] `frontend/src/__tests__/Downloads.test.jsx`, `DownloadRow.test.jsx`, `eta.test.js`; extend `App.test.jsx`, `Search.test.jsx`
- [ ] `infra/tests` additions for logging rotation and Caddy headers; `scripts/smoke.py` `cache` subcommand (02-03) and `downloads` subcommand (02-11)

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
