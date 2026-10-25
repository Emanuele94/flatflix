---
phase: "03"
slug: "jellyfin-server-tv-playback-gate"
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: "2026-10-25"
---

# Phase 03 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 (+ pyyaml), already locked in `backend/` |
| **Config file** | `backend/pyproject.toml` (no new marker; live checks are script commands) |
| **Quick run command** | `uv run --project backend --frozen pytest infra/tests -q` |
| **Full suite command** | `uv run --project backend --frozen pytest backend/tests infra/tests -q` |
| **Estimated runtime** | ~30 seconds |

Opt-in live checks (running stack): `uv run --project backend --frozen python scripts/jellyfin_setup.py --check` and `caddy validate` in the pinned Caddy image.

---

## Sampling Rate

- **After every task commit:** Run `uv run --project backend --frozen pytest infra/tests -q`
- **After every plan wave:** Run `uv run --project backend --frozen pytest backend/tests infra/tests -q`
- **Before `/gsd-verify-work`:** Full suite green, live checks green, `docs/tv-compatibility.md` verdict written
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

Filled by the planner per task; source map is `03-RESEARCH.md` § Validation Architecture → Phase Requirements -> Test Map.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 03-01-01 | 01 | 1 | INFRA-03, JFIN-01 | T-03-01, T-03-05 | One CSP on /jellyfin, portal CSP byte-identical, 308 on the bare path, health 200 through Caddy | live (curl + smoke) | the Task 1 verify line of 03-01-PLAN.md | n/a (live) | ⬜ pending |
| 03-01-02 | 01 | 1 | INFRA-03, JFIN-01 | T-03-04, T-03-05 | Jellyfin pinned, unpublished, hardened, scratch read-only, no DATA_ROOT; Caddy route contract; 502 text | unit (YAML, text) + live | `uv run --project backend --frozen pytest infra/tests -q` | ❌ W0 (`test_caddyfile.py` new, `test_compose_invariants.py` extended) | ⬜ pending |
| 03-01-03 | 01 | 1 | JFIN-01 | T-03-06 | Env keys are placeholders or empty; household password short and readable | unit | `uv run --project backend --frozen pytest backend/tests/test_config.py infra/tests -q` | extend | ⬜ pending |
| 03-02-01 | 02 | 2 | JFIN-01, JFIN-02 | T-03-08, T-03-09 | Wizard run in the same step as the start; `/Users/Public` is exactly household | unit + live | `uv run --project backend --frozen pytest backend/tests/test_jellyfin_setup_contract.py -q && python3 scripts/jellyfin_setup.py check` | ❌ W0 (new) | ⬜ pending |
| 03-02-02 | 02 | 2 | JFIN-01, JFIN-02, JFIN-03 | T-03-11, T-03-12 | Household non-admin, two libraries only; bitrate limit; idempotent; persistent | unit + live | `python3 scripts/jellyfin_setup.py check` (also after a recreate) | ✅ after 03-02-01 | ⬜ pending |
| 03-03-01 | 03 | 3 | COMPAT-01, COMPAT-02, COMPAT-03 | T-03-13, T-03-14 | Helper keeps no device data and prints no URL | unit + live | `uv run --project backend --frozen pytest backend/tests/test_tv_gate_contract.py -q && python3 scripts/tv_gate.py selftest --row A01 --profile remux` | ❌ W0 (new) | ⬜ pending |
| 03-03-02 | 03 | 3 | COMPAT-01, COMPAT-02, COMPAT-03 | T-03-15 | Test videos checked against their published sha256 | live | `python3 scripts/make_compat_clips.py clips --verify && python3 scripts/tv_gate.py selftest --row A01 --all` | ✅ | ⬜ pending |
| 03-03-03 | 03 | 3 | COMPAT-01..04 | T-03-13 | Doc forbids IPv4, MAC and serial/ESN/device-id values | doc lint | `python3 scripts/tv_gate.py validate` | ❌ W0 (new) | ⬜ pending |
| 03-04-01 | 04 | 3 | NAME-01 | T-03-18 | Torrent names become safe path components inside scratch/Raw | unit + live | `uv run --project backend --frozen pytest backend/tests/test_name_scan_contract.py -q && python3 scripts/name_scan.py run --corpus scripts/name_scan_sample.json` | ❌ W0 (new) | ⬜ pending |
| 03-04-02 | 04 | 3 | NAME-01 | T-03-17, T-03-20 | No real name in the report; capture never downloads | unit | `python3 scripts/name_scan.py validate-report` | ✅ | ⬜ pending |
| 03-05-01 | 05 | 4 | INFRA-04, INFRA-03 | T-03-21, T-03-23 | Placeholders only; warning sentence before the reset command; documented commands exist | doc lint | `uv run --project backend --frozen pytest infra/tests -q` | ❌ W0 (`test_docs_contract.py` new) | ⬜ pending |
| 03-05-02 | 05 | 4 | JFIN-01, INFRA-03 | T-03-21 | Decisions recorded in PROJECT.md | doc lint | `uv run --project backend --frozen pytest infra/tests -q` | ✅ | ⬜ pending |
| 03-06-01 | 06 | 5 | all phase IDs | — | Preflight on the rebuilt stack; no frontend change | live | the Task 1 verify line of 03-06-PLAN.md | ✅ | ⬜ pending |
| 03-06-02 | 06 | 5 | COMPAT-01..03, INFRA-04, JFIN-02, JFIN-03, NAME-01 | T-03-25 | TV leaves the admin session at the end | manual (human-action) | `python3 scripts/tv_gate.py verdict` exits 0 afterwards | — | ⬜ pending |
| 03-06-03 | 06 | 5 | COMPAT-01..03, JFIN-03, INFRA-04 | T-03-24 | Facts written without private data | doc lint + live | `python3 scripts/tv_gate.py validate && python3 scripts/tv_gate.py verdict && python3 scripts/jellyfin_setup.py check` | ✅ | ⬜ pending |
| 03-07-01 | 07 | 6 | NAME-01 | T-03-29 | Counts and failure classes only | live + doc lint | `python3 scripts/name_scan.py run && python3 scripts/name_scan.py validate-report && uv run --project backend --frozen pytest infra/tests -q` | ✅ | ⬜ pending |
| 03-07-02 | 07 | 6 | COMPAT-04 | — | Human verdict on recorded evidence | manual (decision) | — | — | ⬜ pending |
| 03-07-03 | 07 | 6 | COMPAT-04, INFRA-04 | T-03-28 | Headline allowed by the rows; Pending refused at phase end | doc lint | `python3 scripts/tv_gate.py validate && uv run --project backend --frozen pytest backend/tests infra/tests -q` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `infra/tests/test_caddyfile.py` — portal CSP identical, Jellyfin route contract, tolerant of `handle_errors` (plan 03-01)
- [ ] `infra/tests/test_compose_invariants.py` (extend) — Jellyfin service, network sets (replace `web == {"edge"}`), image pin, ports doc row (plan 03-01)
- [ ] `backend/tests/test_jellyfin_setup_contract.py` — setup script pure functions, bitrate rule, policy builder (plan 03-02)
- [ ] `backend/tests/test_tv_gate_contract.py` — catalogue, classifier, tracker, renderer, validator, verdict, committed doc (plan 03-03)
- [ ] `backend/tests/test_name_scan_contract.py` — normaliser, layout, classifier, D-92 bar, report privacy (plan 03-04)
- [ ] `infra/tests/test_docs_contract.py` — setup.md copy and commands, PROJECT.md rows, MAC/device-id scans, phase-end verdict and naming checks (plans 03-05, 03-07)
- [ ] `.gitignore` (`/jellyfin/`, which also holds the real name corpus), `.env.example` (Jellyfin passwords, bitrate, empty `TMDB_API_KEY`), `scripts/init-host-dirs.sh` Jellyfin dirs + seed `network.xml` (plan 03-01)
- No new pytest marker: live checks run as script commands (`jellyfin_setup.py check`, `tv_gate.py selftest`, `name_scan.py run`), not as an opt-in pytest suite.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| TV browser opens the Caddy address and browses the sample library | JFIN-01, JFIN-02 | Needs the real Hisense TV | Open the documented address on the TV, log in as household, check posters/plots/seasons |
| Codec matrix play-through | COMPAT-01..03 | Needs the real TV + human "picture and sound OK" | Run the helper script, press play on each Compat clip, confirm per row |
| Go/no-go verdict | COMPAT-04 | Judgement on recorded evidence | Write verdict heading in `docs/tv-compatibility.md` |
| Same address after laptop and router restart | INFRA-04 | Physical restarts | Restart both, reopen the address on the TV, record result |
| Human labels for the 30-name scan | NAME-01 | Wrong-title judgement needs a human | `python scripts/name_scan.py run`, label results, record decision in PROJECT.md |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
