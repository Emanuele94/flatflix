---
phase: 03-jellyfin-server-tv-playback-gate
plan: 07
subsystem: infra
tags: [docs, jellyfin, dhcp-reservation, mdns, avahi, docs-contract-test, project-decisions]
status: complete
requires:
  - phase: 03-jellyfin-server-tv-playback-gate
    provides: "03-03..03-06: scripts/jellyfin_setup.py, make_compat_clips.py, name_scan.py, tv_gate.py and docs/tv-compatibility.md, whose real subcommands the guide documents"
provides:
  - "docs/setup.md `## Jellyfin and the TV`: First start, household account, bitrate limit, same address (INFRA-04), .local ladder with avahi, TV compatibility test, naming scan test, Reset Jellyfin, five Troubleshooting rows"
  - "infra/tests/test_docs_contract.py: section, documented_commands, defined_subcommands, find_macs, missing_commands, bad_addresses, key_decisions, find_device_ids and 36 tests"
  - ".planning/PROJECT.md: Phase 3 decisions D-80, D-82, D-93, D-94, D-95, D-100 recorded and docs/tv-compatibility.md linked"
affects: [03-08, 03-09, phase-04-media-mount, phase-05-tv-app, phase-06-production-box]
actuals:
  tokens: 7800
  tasks: 2
  commits: 2
plan_head_before: ef59e38e39e0432b7cb1dbe55ee56e4a602c1940
commits: 2
plan_head_after: 987e37768e0816c95c68dbff62b4699509047b71
tech-stack:
  added: []
  patterns:
    - "Docs checked as data: pure text helpers (section, documented_commands, defined_subcommands) plus mutated-text tests, so every check is proven to fail when the doc drifts"
    - "Documented subcommands are compared with the argparse definitions read as source text (add_parser literals and the loop tuple in make_compat_clips.py), with no import of the scripts"
key-files:
  created:
    - infra/tests/test_docs_contract.py
  modified:
    - docs/setup.md
    - .planning/PROJECT.md
key-decisions:
  - "The measure command is written `python3 jellyfin_setup.py measure --base http://<laptop-ip>/jellyfin` (no scripts/ prefix) because it runs on another computer that holds only a copy of the file; the contract regex accepts the optional prefix and still checks the script and subcommand exist"
  - "The household address line is the IP-only form; plan 03-09 switches it to the two-name form only if the TV resolves a .local name (D-81)"
  - "The Troubleshooting CSP row writes the pipe inside the command as `\\|`, which GitHub renders as a pipe inside a table cell"
requirements-completed: [INFRA-04, INFRA-03, JFIN-01]
coverage:
  - id: E1
    description: "An admin following First start brings Jellyfin up provisioned and checked: dev_env.py, init-host-dirs.sh, start plus setup --no-scan on one line, sources and library, setup, check (11 OK lines), then the exact admin sign-in line"
    requirement: "JFIN-01"
    verification:
      - kind: unit
        ref: "infra/tests/test_docs_contract.py#test_first_start_runs_the_provisioning_commands_in_order"
        status: pass
      - kind: other
        ref: "Task 1 verify: init-host-dirs.sh, docker compose up -d --wait, jellyfin_setup.py setup --no-scan (only unchanged lines) and check (11 OK lines) run literally on the dev stack, exit 0"
        status: pass
    human_judgment: false
  - id: E2
    description: "The guide keeps the TV's address stable (router reservation by MAC, Windows random hardware addresses and sleep, Docker Desktop sign-in start) and ends with the exact restart check sentence"
    requirement: "INFRA-04"
    verification:
      - kind: unit
        ref: "infra/tests/test_docs_contract.py#test_the_same_address_section_names_the_reservation_and_the_windows_settings"
        status: pass
      - kind: unit
        ref: "infra/tests/test_docs_contract.py#test_the_restart_check_ends_the_same_address_section"
        status: pass
    human_judgment: true
    rationale: "The settings are human steps on the router and the Windows laptop; the restart test passes only in the real-TV session (plan 03-08)"
  - id: E3
    description: "The .local ladder (phone, then TV, no extra software; avahi host-name=flatflix, allow-interfaces=<lan-nic>, 5353/udp, avahi-resolve) is documented in UI-SPEC order"
    requirement: "INFRA-04"
    verification:
      - kind: unit
        ref: "infra/tests/test_docs_contract.py#test_the_local_ladder_documents_the_phone_test_and_avahi"
        status: pass
    human_judgment: true
    rationale: "Whether Windows answers .local and whether the TV resolves it (RESEARCH A2) are unverified; the avahi steps run only on the production box (Phase 6)"
  - id: E4
    description: "Every `python3 scripts/<name>.py <subcommand>` in setup.md names an existing script and a subcommand its argparse defines, and all 17 documented subcommands of the four helpers are present"
    requirement: "JFIN-01"
    verification:
      - kind: unit
        ref: "infra/tests/test_docs_contract.py#test_every_documented_script_command_exists"
        status: pass
      - kind: unit
        ref: "infra/tests/test_docs_contract.py#test_a_made_up_subcommand_is_reported"
        status: pass
    human_judgment: false
  - id: E5
    description: "No real address, MAC address or device id reaches docs or PROJECT.md: only <laptop-ip>, <mac-address>, <laptop-name>, <lan-nic>"
    requirement: "INFRA-04"
    verification:
      - kind: unit
        ref: "infra/tests/test_docs_contract.py#test_no_file_under_docs_contains_a_mac_address"
        status: pass
      - kind: unit
        ref: "infra/tests/test_docs_contract.py#test_the_mac_scan_catches_every_common_form"
        status: pass
      - kind: unit
        ref: "infra/tests/test_docs_contract.py#test_the_compatibility_docs_hold_no_mac_address_and_no_device_id_value"
        status: pass
    human_judgment: false
  - id: E6
    description: "Reset Jellyfin carries the exact warning sentence on a line before the only removal command, with the container stopped first and only jellyfin/config and jellyfin/cache named"
    requirement: "JFIN-01"
    verification:
      - kind: unit
        ref: "infra/tests/test_docs_contract.py#test_the_reset_warning_comes_before_the_line_holding_the_removal_command"
        status: pass
    human_judgment: false
  - id: E7
    description: "PROJECT.md records the shared household account (D-94), English audio and Smart English subtitles (D-95), Jellyfin at /jellyfin with 8096 unpublished (D-80, D-82, INFRA-03), the opt-in TheMovieDb key (D-93), the accepted admin-password exposure (D-100) and the link to docs/tv-compatibility.md; the W1 naming row stays Pending for plan 03-09"
    requirement: "JFIN-01"
    verification:
      - kind: unit
        ref: "infra/tests/test_docs_contract.py#test_the_new_rows_record_tmdb_the_admin_password_and_the_compatibility_doc"
        status: pass
      - kind: unit
        ref: "infra/tests/test_docs_contract.py#test_no_decision_is_still_pending_for_phase_3_and_the_naming_row_waits_for_03_09"
        status: pass
    human_judgment: false
  - id: E8
    description: "The three UI-SPEC troubleshooting symptoms plus the CSP, unavailable-page and locked-account rows are in the existing Troubleshooting table, which keeps its older rows"
    requirement: "INFRA-03"
    verification:
      - kind: unit
        ref: "infra/tests/test_docs_contract.py#test_the_troubleshooting_table_holds_the_five_jellyfin_symptoms"
        status: pass
      - kind: other
        ref: "curl -sI http://127.0.0.1/jellyfin/web/index.html | grep -ci '^content-security-policy' printed 1 and that header holds 'wasm-unsafe-eval'"
        status: pass
    human_judgment: false

duration: 4min
completed: 2026-10-25
---

# Phase 3 Plan 07: Jellyfin and the TV admin guide Summary

`docs/setup.md` now has a `## Jellyfin and the TV` section an admin can follow from nothing to a provisioned, checked Jellyfin, a TV address that survives restarts (DHCP reservation, Windows and Docker Desktop settings), the `.local` ladder with avahi for the production box, both Phase 3 tests and a safe reset, `PROJECT.md` records the Phase 3 decisions already made, and `infra/tests/test_docs_contract.py` keeps the copy, the placeholders and every documented command true.

**Started:** 2026-10-25T22:20:43Z | **Completed:** 2026-10-25T22:25Z | **Duration:** ~4 min | **Tasks:** 2 | **Files:** 3 (1 new, 2 modified)

## Accomplishments

- Eight subsections under `## Jellyfin and the TV`, placed after `## Phone access (D-04)`, whose last bullet now points to "Keep the laptop on the same address". Steps are imperative and numbered, menu paths are bold, and the only addresses are `<laptop-ip>`, `<mac-address>`, `<laptop-name>` and `<lan-nic>`.
- The exact UI-SPEC sentences are in place once each: the admin sign-in line, the restart check (last line of its section) and the reset warning (on a line before the single `rm -rf` line).
- Five rows added to the Troubleshooting table: blank page or no styles (with the CSP grep, verified live), `.local` name, "starting", "not available right now", locked household account.
- Seventeen documented subcommands across the four helpers, each checked against the argparse source by `test_every_documented_script_command_exists`.
- PROJECT.md: the two `Pending (Phase 3)` rows are Decided (D-94, D-95), the W3 and single-origin rows record what Phase 3 built, three rows are new (D-93, D-100, the compatibility matrix link, still Pending until the TV session), the W1 naming row is untouched, the footer reads 2026-10-25 after Phase 3 planning decisions.
- Tracer feedback gate: the Task 1 verify chain (pytest, init-host-dirs.sh, `docker compose up -d --wait`, `setup --no-scan`, `check`) ran end to end and passed, so Task 2 went ahead.

## Task Commits

1. **Task 1 (tracer): Jellyfin and the TV section and the docs contract test** - `f7d4b6e` (docs; RED and GREEN share one commit, as in earlier plans of this phase)
2. **Task 2: PROJECT.md decisions and the table and device-id guards** - `987e377` (docs)

## RED and GREEN evidence

- **Task 1 RED** (test file written, `docs/setup.md` unchanged): `16 failed, 8 passed`. **GREEN:** after two small fixes (a phrase wrapped over two lines, backticks in a table cell) `24 passed`; `infra/tests` `168 passed`.
- **Task 2 RED** (tests added, PROJECT.md unchanged): `8 failed, 28 passed`. **GREEN:** `36 passed`; `infra/tests` `180 passed`.

## Live output (no secret in it)

`jellyfin_setup.py setup --no-scan` printed ten `unchanged` or `OK` lines (no change on a provisioned server); `check` printed 11 lines, all `OK`: wizard-complete, admin-login, public-users, admin-hidden, household-policy, household-prefs, libraries, bitrate, movies-metadata, series-metadata, metadata-local. Also run: `jellyfin_setup.py cap --mbps 100` printed `cap 70 Mbps`; `tv_gate.py validate` printed `OK`; `make_compat_clips.py clips --verify` ended with `OK R03`.

## Acceptance criteria

All PASS. Task 1: `^## Jellyfin and the TV$` 1, `^### Keep the laptop on the same address$` 1, sign-in line 1, restart check 1, reset warning 1, `host-name=flatflix` 1, `Start Docker Desktop when you sign in` 1, `def test_every_documented_script_command_exists` 1. Task 2: `Pending (Phase 3)` 0 (baseline 2), `Phase 3 decides, Phase 4 implements` 1, `tv-compatibility.md` 1, `D-94` 1, `D-95` 1. Plan verification: `uv run --project backend --frozen pytest backend/tests infra/tests -q` gave `1455 passed, 19 deselected`.

## Deviations from Plan

### Auto-fixed Issues

None needed beyond the two test and copy fixes during GREEN (a phrase the test requires on one line, and backticks in a table cell), which were corrections to this plan's own new files before the commit.

### Plan assumptions that resolved differently

- The plan's regex for documented commands names `python3 scripts/<name>.py`, but its own measure instruction runs `python3 jellyfin_setup.py measure` on another computer. The helper regex takes `scripts/` as optional, so both forms are checked against the scripts folder.
- The plan lists "the three UI-SPEC troubleshooting symptoms" plus two more rows; the symptom match ignores backticks so the existing table style (commands in code spans) is kept.

**Total deviations:** 0 auto-fixed, 2 plan details resolved as above. **Impact:** none on scope.

## Issues Encountered

- None. The known flaky test in `backend/tests/test_download_cancel.py` did not fail in the full run.
- Windows answering for its own `.local` name, random hardware addresses and sleep breaking reachability (RESEARCH A2 and A6) are still unverified; the guide says to test on a phone first and keeps the IP address as the household address until the TV passes. The avahi steps are written from avahi-daemon.conf(5) and can only be run on the production box (Phase 6, INFRA-05).

## Known Stubs

None. The `Pending (Phase 3 TV session)` text in the PROJECT.md matrix row is the intended state until plan 03-08 runs the TV session and plan 03-09 renders the verdict.

## Threat Flags

None. T-03-21 mitigated: placeholders only, the MAC, device-id and address scans run over docs and PROJECT.md. T-03-22 mitigated: the avahi steps set `allow-interfaces=<lan-nic>` and end with an `avahi-resolve` check from another host. T-03-23 mitigated: the exact warning sentence precedes the only `rm -rf` line (tested), the container is stopped first and only `jellyfin/config` and `jellyfin/cache` are named. T-03-SC: no package added.

## Authentication Gates

None.

## Next Phase Readiness

Plan 03-08 (the real-TV session) can follow "Keep the laptop on the same address", "A name instead of the address (.local)" and "TV compatibility test" literally and record the results in `docs/tv-compatibility.md`. Plan 03-09 flips the household address line to the two-name form only if the TV resolves a `.local` name, and decides the W1 naming row from the scan test. Ready for 03-08.

## Self-Check: PASSED

`docs/setup.md`, `infra/tests/test_docs_contract.py` and `.planning/PROJECT.md` exist; commits `f7d4b6e` and `987e377` are ancestors of HEAD; `git status` shows only the pre-existing unrelated changes.
