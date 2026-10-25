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
| **Config file** | `backend/pyproject.toml` (add marker `jellyfin`) |
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
| 03-xx-xx | xx | x | JFIN-01 | T-03-xx | Jellyfin pinned, no published ports, hardened, scratch read-only, no `/data` | unit (YAML) | `uv run --project backend --frozen pytest infra/tests/test_compose_invariants.py -q` | ❌ W0 (extend) | ⬜ pending |
| 03-xx-xx | xx | x | INFRA-03 | T-03-xx | Portal CSP unchanged; Jellyfin route has own CSP incl. `'wasm-unsafe-eval'` | unit (text) | `uv run --project backend --frozen pytest infra/tests/test_caddyfile.py -q` | ❌ W0 | ⬜ pending |
| 03-xx-xx | xx | x | COMPAT-01..04, NAME-01 | T-03-xx | Docs carry no serial/ESN/MAC/IP | doc lint | `uv run --project backend --frozen pytest infra/tests/test_docs_contract.py -q` | ❌ W0 | ⬜ pending |
| 03-xx-xx | xx | x | COMPAT-01..03, NAME-01 | — | N/A | unit | `uv run --project backend --frozen pytest backend/tests/test_jellyfin_scripts_contract.py -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `infra/tests/test_caddyfile.py` — portal CSP identical, Jellyfin route contract, tolerant of `handle_errors`
- [ ] `infra/tests/test_docs_contract.py` — doc structure, forbidden content, PROJECT.md decision row
- [ ] `infra/tests/test_compose_invariants.py` (extend) — Jellyfin service, network sets (replace `web == {"edge"}`), image pin, ports doc row
- [ ] `backend/tests/test_jellyfin_scripts_contract.py` — classifier, renderer, name evaluator, clip command builder
- [ ] `.gitignore` (`jellyfin/`, real name corpus), `.env.example` (Jellyfin passwords, empty `TMDB_API_KEY`), `scripts/init-host-dirs.sh` Jellyfin dirs + seed `network.xml`

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
