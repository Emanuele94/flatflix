---
phase: 03-jellyfin-server-tv-playback-gate
plan: 09
subsystem: infra
tags: [naming-scan, tv-compatibility, verdict, go-no-go, jellyfin, vidaa]
status: complete
requires:
  - phase: 03-jellyfin-server-tv-playback-gate
    provides: "03-08: measured TV matrix, address check, bitrate record, labelled naming corpus"
provides:
  - "docs/naming-scan.md real-corpus counts and the NAME-01 decision (portal rename step, D-90/D-92)"
  - "docs/tv-compatibility.md verdict GO with the Phase 5 line, the transcoding line and the Jellyfin version"
  - "PROJECT.md rows decided: naming owner, TV verdict (Decided (user, D-87)), production box implication"
  - "Contract tests that fail on a Pending verdict, a pending naming row or an address line that disagrees with the Address check"
affects: [phase-04-portal-rename, phase-05-tv-app, phase-06-production-box]
actuals:
  tokens: 14000
  tasks: 3
  commits: 2
plan_head_before: 31b7d53b9fc94592bb737fbce5f332c545ed871d
commits: 2
plan_head_after: 9ddaa2eedb0af66556779ecbc87f23f2b98b8daa
key-files:
  created: []
  modified:
    - docs/naming-scan.md
    - docs/tv-compatibility.md
    - docs/setup.md
    - .planning/PROJECT.md
    - infra/tests/test_docs_contract.py
    - backend/tests/test_tv_gate_contract.py
key-decisions:
  - "NAME-01: relaxed naming does not meet the D-92 bar (RESULT 26 names: identified 20, unidentified 6, wrong title 0, 76 %); the portal rename step after the safety check wins (D-90, D-92). All failures are flat episode files. Phase 4 implements."
  - "TV verdict GO (user, D-87): tv_gate.py verdict printed CANDIDATE GO and '1080p content needed video transcoding: never'; Phase 5 builds its device profile from the Direct play and Remux rows."
  - "Household address stays the IP form: the TV did not resolve .local names on firmware V0003.09.60A.Q0707 (D-81)."
  - "No transcoding power is needed for 1080p, so the production box only has to be x86_64 with KVM for Firecracker."
requirements-completed: [NAME-01, COMPAT-04, INFRA-04, JFIN-03]
---

# Phase 3 Plan 09: Naming decision and the TV verdict Summary

Both open Phase 3 decisions are recorded on evidence: the portal rename step owns Jellyfin naming (76 % identified, bar not met), and the TV verdict is GO with no 1080p video transcoding.

## Tasks

| Task | Result | Commit |
| --- | --- | --- |
| 1 Tracer: real corpus scanned, counts and NAME-01 decision recorded, contract tests added | Done | 4fb624a |
| 2 Go/no-go verdict (checkpoint:decision) | User chose `go` on the recorded evidence | none |
| 3 Verdict, address line and contract tests written | Done | 9ddaa2e |

## Evidence recorded

- Naming scan: `RESULT 26 names: identified 20, unidentified 6, wrong title 0 (76 %)`; `VERDICT relaxed naming does not meet the bar: the rename step wins (D-90, D-92)`. Only counts are in the repo; no real name appears in any committed file (T-03-29).
- TV: `python3 scripts/tv_gate.py verdict` prints `CANDIDATE GO` and `1080p content needed video transcoding: never`; `tv_gate.py validate` prints OK with the GO headline.
- Streaming limit: `jellyfin_setup.py check` now prints 11 OK including bitrate (JELLYFIN_MAX_BITRATE_MBPS=35 applied by the user, then setup re-run). This closes the open item from plan 03-08 and completes JFIN-03.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Plan 03-08 contract tests pinned the Pending verdict**
- **Found during:** Task 3 verify (full pytest)
- **Issue:** `test_the_committed_doc_has_the_ui_spec_skeleton` asserted the `**Pending**` line, `test_a_verdict_must_open_with_a_known_headline` replaced it to build a bad doc, and `test_render_into_a_doc_puts_the_played_rows_in_the_matrix` rendered a mostly-untested matrix under the committed verdict. All three failed once the GO headline was written.
- **Fix:** Added a `pending_doc()` helper (committed doc with the verdict block reset to the Pending line) for the two builder tests; the skeleton test now asserts the first verdict line is one of the three headlines and the Pending line is gone.
- **Files modified:** backend/tests/test_tv_gate_contract.py (not in the plan's file list)
- **Commit:** 9ddaa2e

**2. [Orchestrator correction] Restart-test date**
- The restart test ran on 2026-10-27 (the laptop came back up at 00:00 that day), not 2026-10-26. The line `Same address after laptop and router restart` in docs/tv-compatibility.md now reads 2026-10-27. The session and Address check date (2026-10-26) is unchanged.

## Issues Encountered

- `backend/tests/test_download_cancel.py::test_a_failed_first_sweep_still_leaves_a_sweep_that_deletes_the_torrent` (known timing race) did not fail in the final full run: 1460 passed, 19 deselected.

## Known Stubs

None.

## Threat Flags

None. The doc, guide and PROJECT.md hold no LAN address, MAC, serial or device id; the repo hygiene tests pass.

## Self-Check: PASSED

- docs/tv-compatibility.md, docs/setup.md, .planning/PROJECT.md, infra/tests/test_docs_contract.py, backend/tests/test_tv_gate_contract.py present.
- Commits 4fb624a and 9ddaa2e are ancestors of HEAD.
- Acceptance greps: GO headline count 1, Pending count 0, `Decided (user, D-87)` count 1, `tv_gate.py validate` OK, `name_scan.py validate-report` OK.
