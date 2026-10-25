---
phase: 03-jellyfin-server-tv-playback-gate
plan: 03
subsystem: infra
tags: [jellyfin, provisioning, stdlib-scripts, tmdb-metadata, bitrate, household-account]
status: complete

requires:
  - phase: 03-jellyfin-server-tv-playback-gate
    provides: "03-01: pinned Jellyfin behind Caddy at /jellyfin; 03-02: JELLYFIN_* keys in .env.example and dev_env.py"
provides:
  - "scripts/jellyfin_setup.py: setup, check, measure and cap subcommands; one idempotent command provisions Jellyfin through Caddy"
  - "scripts/make_compat_clips.py: sources and library subcommands; sha256-pinned Blender films and Pioneer One stand-in episodes"
  - "A provisioned, running Jellyfin: hidden admin, shared household account, Movies and TV Series libraries with real TheMovieDb metadata"
  - "backend/tests/test_jellyfin_setup_contract.py: 67 pure-function contract tests for both scripts"
affects: [03-04, 03-05, 03-08, phase-04-media-mount, phase-05-tv-app]

actuals:
  tokens: 15800
  tasks: 2
  commits: 3
plan_head_before: 04878c5ec75fc0ab3c0311451e13e423d0d0c927
commits: 3
plan_head_after: ba8f413662db95b4dd0bed7e9389cfd833fca3da

tech-stack:
  added: []
  patterns:
    - "Standalone stdlib scripts loaded by path in contract tests; pure functions carry the rules (bitrate_cap, household_policy, scan_settled, library_gaps)"
    - "Read-modify-write per step, post only what differs, print OK <step> (created|changed|unchanged)"
    - "check collects every failure over a fixed CHECK_STEPS order and writes nothing"
    - "Downloads and ffmpeg output go to .part files and are renamed only when complete"

key-files:
  created:
    - scripts/jellyfin_setup.py
    - scripts/make_compat_clips.py
    - backend/tests/test_jellyfin_setup_contract.py
  modified: []

key-decisions:
  - "Scan wait also treats a RefreshLibrary task whose LastExecutionResult.EndTimeUtc changed as 'seen', so an unchanged library (scan finishes between two polls) settles instead of timing out"
  - "Id and list comparison ignores dashes and order (same_value), so a policy is not rewritten on every run because Jellyfin formats ids differently"
  - "ensure_user resets a wrong household password by clearing it and then setting it, which needs no knowledge of the old one"
  - "Missing JELLYFIN_MAX_BITRATE_MBPS stops setup with FAIL config (no silent default); all config checks run before the first request"

requirements-completed: [JFIN-01, JFIN-02, JFIN-03]

coverage:
  - id: D1
    description: "One command provisions Jellyfin through Caddy (wizard, admin, household, libraries, server name, English settings, scan) and a second run changes nothing"
    requirement: "JFIN-01"
    verification:
      - kind: other
        ref: "Task 2 verify block: second `setup --no-scan` printed only unchanged lines"
        status: pass
    human_judgment: false
  - id: D2
    description: "GET /Users/Public returns exactly household; household is non-admin, cannot delete, manage collections or remote-control, sees exactly the two libraries, English audio and Smart subtitles"
    requirement: "JFIN-01"
    verification:
      - kind: unit
        ref: "backend/tests/test_jellyfin_setup_contract.py#test_household_policy_is_the_decided_permission_set"
        status: pass
      - kind: other
        ref: "scripts/jellyfin_setup.py check: public-users, admin-hidden, household-policy, household-prefs OK on the live server"
        status: pass
    human_judgment: false
  - id: D3
    description: "Big Buck Bunny, Sintel, Tears of Steel and Pioneer One S01E01-E03 carry TheMovieDb ids, plots, posters and cast, stored under jellyfin/config/metadata"
    requirement: "JFIN-02"
    verification:
      - kind: other
        ref: "scripts/jellyfin_setup.py check: movies-metadata, series-metadata, metadata-local OK, also after `docker compose up -d --force-recreate --wait jellyfin`"
        status: pass
    human_judgment: false
  - id: D4
    description: "Bitrate limit equals JELLYFIN_MAX_BITRATE_MBPS x 1,000,000 on the server and the household policy; measure and cap turn speeds into a limit"
    requirement: "JFIN-03"
    verification:
      - kind: unit
        ref: "backend/tests/test_jellyfin_setup_contract.py#test_bitrate_cap_is_seventy_percent_floored_and_clamped"
        status: pass
      - kind: other
        ref: "check bitrate OK live; `cap --mbps 100` printed `cap 70 Mbps`"
        status: pass
    human_judgment: true
    rationale: "The unit (bits per second, RESEARCH A3) and the fact that the limit does not bind a LAN client are confirmed only in the TV session (plan 03-08)"
  - id: D5
    description: "setup stops with FAIL config before any request on equal, empty or placeholder passwords or an out-of-range or non-integer bitrate, and never prints a value"
    requirement: "JFIN-01"
    verification:
      - kind: unit
        ref: "backend/tests/test_jellyfin_setup_contract.py#test_setup_fails_with_config_before_any_request"
        status: pass
    human_judgment: false
  - id: D6
    description: "Sources come only from download.blender.org over HTTPS with the sha256 pinned and checked on every run"
    requirement: "JFIN-02"
    verification:
      - kind: unit
        ref: "backend/tests/test_jellyfin_setup_contract.py#test_every_source_comes_from_the_blender_download_host"
        status: pass
    human_judgment: false
---

# Phase 3 Plan 03: Jellyfin provisioning and sample library Summary

`python3 scripts/jellyfin_setup.py setup` now takes a fresh Jellyfin to a usable server through Caddy only: wizard, hidden admin, one shared `household` account (English audio, Smart English subtitles, two libraries, no admin powers), Movies and TV Series libraries, the bitrate limit and a reliable library scan. `check` proves 11 promises in a fixed order, also after a container recreate.

**Started:** 2026-10-25T21:01:28Z | **Completed:** 2026-10-25T21:18Z | **Duration:** ~17 min (about 6 min of it was downloading and encoding) | **Tasks:** 2 | **Files:** 3 (all new)

## Accomplishments

- `scripts/jellyfin_setup.py`: `setup [--no-scan]`, `check`, `measure --base URL [--runs N] [--size-mb N]`, `cap --mbps N`. Default base `http://127.0.0.1/jellyfin`, never port 8096, only the `Authorization: MediaBrowser ... Token=` header, no password or token ever printed.
- `scripts/make_compat_clips.py`: `sources` (three Blender films, sha256 pinned) and `library` (Movies as `Title (Year)/Title (Year).ext`, Pioneer One S01E01-E03 stand-ins cut from Sintel at 120, 300 and 480 s with audio tagged `eng`).
- 67 contract tests over the pure parts (auth header, passwords, library options, scan settling, bitrate rule, household policy and prefs, check order, library gaps, episode command, config failure before any request).
- Live result: Big Buck Bunny (2008), Sintel (2010), Tears of Steel (2012) and Pioneer One with Season 1 and episodes 1-3 show TheMovieDb ids, plots, posters and cast; images live under `jellyfin/config/metadata`.
- Tracer feedback gate: the Task 1 verify chain was re-run end to end (pytest, compose up, setup, doctor, sources, library, setup, check) and passed, so expansion went ahead.

## Task Commits

1. **Task 1 (tracer): one setup command provisions Jellyfin, household sees Big Buck Bunny** - `66efd8d` (feat)
2. **Task 2 RED: failing tests** - `da46c46` (test)
3. **Task 2 GREEN: full library, permissions, bitrate** - `ba8f413` (feat)

## RED and GREEN evidence

**Task 1 RED** (run before either script existed): `32 errors in 0.47s`, every one a `FileNotFoundError` loading `scripts/jellyfin_setup.py` or `scripts/make_compat_clips.py` in the module fixtures. First GREEN attempt: `30 passed, 2 errors` (the `Source` dataclass needs its module in `sys.modules`; the test loader now registers it), then `32 passed`. Tracer RED and GREEN went into one commit, as in plan 03-02.

**Task 2 RED** (commit `da46c46`): `33 failed, 34 passed`. Failures are `AttributeError` on the planned symbols (`bitrate_cap`, `bitrate_bps`, `household_policy`, `policy_gaps`, `user_prefs`, `CHECK_STEPS`, `library_gaps`, `episode_path`, `episode_command`), a `SystemExit` for the missing `cap` subcommand, and two setup tests that reached the monkeypatched `Api` because the bitrate rule did not exist. Semantic assessment: every target test failed for the intended reason. Passing-at-RED tests (equal passwords, empty household password) pin behavior Task 1 already had. `gsd_run check tdd-red-evidence` was not run: pytest text output is not a supported report format and the plan is `type: execute`.

**Task 2 GREEN** (commit `ba8f413`): `67 passed` in the contract file; `uv run --project backend --frozen pytest backend/tests infra/tests -q` gives `1204 passed, 19 deselected`; ruff clean on `backend scripts/jellyfin_setup.py scripts/make_compat_clips.py`.

## Live output (no secret in it)

First `setup --no-scan` on a fresh Jellyfin (Jellyfin started and provisioned on one command line):

```
OK wizard (created)
OK admin-login
OK household (created)
OK household-visible (changed)
OK libraries (created)
```

First full `setup` after the TV library was added:

```
OK wizard (unchanged)
OK admin-login
OK server-config (changed)
OK household (unchanged)
OK library Movies (unchanged)
OK library TV Series (created)
OK household-policy (changed)
OK household-prefs (changed)
OK admin-hidden (unchanged)
OK scan
```

Second `setup --no-scan` (nothing created, changed or reset):

```
OK wizard (unchanged)
OK admin-login
OK server-config (unchanged)
OK household (unchanged)
OK library Movies (unchanged)
OK library TV Series (unchanged)
OK household-policy (unchanged)
OK household-prefs (unchanged)
OK admin-hidden (unchanged)
```

`check` (identical before and after `docker compose up -d --force-recreate --wait jellyfin`, 11 OK lines):

```
OK wizard-complete
OK admin-login
OK public-users
OK admin-hidden
OK household-policy
OK household-prefs
OK libraries
OK bitrate
OK movies-metadata
OK series-metadata
OK metadata-local
```

Backend doctor with the longer env file (the live check moved here from plan 03-02): exit 0, no FAIL line. `cap --mbps 100` printed `cap 70 Mbps`; `cap --mbps 28` printed `cap 20 Mbps`; `cap --mbps 0` printed `FAIL config: a measured speed must be above zero` and exited 1.

## Pinned sha256 values (of the final file; the extracted member for the zip)

| Source | sha256 |
|--------|--------|
| bbb (`bbb_sunflower_1080p_30fps_normal.mp4`, 276.1 MB) | `ae51005850b0ff757fe60c3dd7a12d754d3cd2397d87d939b55235e457f97658` |
| sintel (`Sintel.2010.1080p.mkv`, 1180.1 MB) | `97f1dbc66231df42ad49bd8c29aa174b8f48933058e47e7157d4ba63d93a8efa` |
| tos (`tears_of_steel_720p.mov`, 372.2 MB) | `efa9062d9cdb7a338e40ad530dfdf234806743f29ae6a1a136b97ece4e588e8f` |

Trust on first verified download over HTTPS from download.blender.org; every later run recomputes and compares them.

## Acceptance criteria

All PASS. Task 1: `DEFAULT_BASE` line 1, `8096` 0, `X-Emby-Token` 0, `def scan_settled` 1, `RefreshLibrary` 2, pinned `sha256="..."` lines present, `git status --porcelain -- jellyfin` empty. Task 2: `def bitrate_cap` 1, `def household_policy` 1, `"Smart"` 1, `"eng"` 2, `CHECK_STEPS` 2, `Season 01` 2, `check` prints 11 OK lines, 3 pinned hashes.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Dataclass loading in the contract-test fixture**
- **Found during:** Task 1 GREEN
- **Issue:** `make_compat_clips.py` defines a frozen dataclass under `from __future__ import annotations`; loading it by path without registering the module in `sys.modules` raised `AttributeError` inside `dataclasses`.
- **Fix:** the test loader sets `sys.modules[name]` before `exec_module`.
- **Files modified:** backend/tests/test_jellyfin_setup_contract.py
- **Commit:** 66efd8d

**2. [Rule 2 - Missing critical] Scan wait could never finish on an unchanged library**
- **Found during:** Task 1 design, before the first re-run
- **Issue:** the plan's `scan_settled` needs the scan "seen Running or items appeared". On a second `setup` nothing changes and the refresh can finish between two 5 s polls, so the wait would time out after 1800 s and break idempotency.
- **Fix:** `scan_settled(..., finished_seen=False)` takes one extra keyword; `wait_for_scan` sets it when the RefreshLibrary task's `LastExecutionResult.EndTimeUtc` differs from its value before the refresh. Covered by `test_scan_settled_accepts_a_scan_seen_to_finish_between_two_polls`. A second `setup` with scan took about 20 s.
- **Files modified:** scripts/jellyfin_setup.py, backend/tests/test_jellyfin_setup_contract.py
- **Commit:** 66efd8d

**3. [Rule 1 - Bug prevention] Policies compared without id formatting or list order**
- **Found during:** Task 2 design
- **Issue:** Jellyfin may return ids with or without dashes; a plain `==` on `EnabledFolders` would make every run report "changed".
- **Fix:** `same_value` compares lists as sorted, dash-free, lowercase ids. The live second run printed only `unchanged`.
- **Commit:** ba8f413

**4. [Rule 2 - Hardening] Output written under a `.part` name for the Tears of Steel remux and the episodes**
- **Found during:** Task 1 step 2
- **Issue:** the plan notes ffmpeg writes to the final path, so a crash leaves a short file that a scan could pick up (the unresolved JFIN-02 edge).
- **Fix:** ffmpeg writes `<name>.part` (`-f matroska`) and the file is renamed only when complete; existing finished files are kept. The edge probe's unresolved item is thereby closed rather than only reviewed.
- **Files modified:** scripts/make_compat_clips.py
- **Commit:** ba8f413

### Environment workaround (not a code deviation)

`docker compose` failed on the WSL credential helper in plan 03-01, so Docker commands here ran with `DOCKER_CONFIG` pointing at a scratch folder with an empty `config.json`; `~/.docker/config.json` was not touched.

**Total deviations:** 4 auto-fixed (1 blocking, 2 missing critical, 1 bug prevention). **Impact:** none on scope; all strengthen idempotency or safety.

## Issues Encountered

- The `ensure_user` password-reset path (a household password that no longer works) and the `admin-login` reset-hint path (wizard completed by someone else) are covered by logic and the config tests but were not exercised against the live server, because the live state never needed them. A first call with a wrong admin password would show the hint.
- `measure` was run once on the laptop itself (2 runs, 30 MB): about 1,210 Mbps, cap 80. That number is loopback speed and means nothing for JFIN-03; the real value comes from a wired LAN computer in plan 03-08.
- `backend/tests/test_config.py` still says "plan 03-03 adds the test that proves it" next to `SCRIPT_KEYS`. The proving test now exists (`test_the_script_reads_every_jellyfin_key_the_template_promises`); the comment is outside this plan's files and was left alone.

## Known Stubs

None. The Pioneer One episodes are stand-in clips on purpose (D-97): posters, seasons and episode plots come from TheMovieDb by name.

## Threat Flags

None. All new surface (script-to-Caddy API calls, Blender downloads, the household account) is in the plan's threat model. T-03-08 mitigated (Jellyfin started and `setup --no-scan` on one command line; `admin_api` raises the reset hint), T-03-09 (no password, token or token URL printed; a test asserts no secret in the config failure output), T-03-10 (HTTPS host pinned by a test, sha256 pinned), T-03-11 (`household_policy` and `check household-policy` plus unit tests), T-03-12 accepted.

## Authentication Gates

None.

## Next Phase Readiness

Jellyfin is now provisioned and running; the first-run wizard is closed. Ready for plan 03-04 (compat clips, admin-only Compat library) and the later TV session (03-08), which confirms the bitrate unit (RESEARCH A3) and sets the TV client's own limit (A4).

## Self-Check: PASSED

`scripts/jellyfin_setup.py`, `scripts/make_compat_clips.py` and `backend/tests/test_jellyfin_setup_contract.py` exist; commits `66efd8d`, `da46c46` and `ba8f413` are ancestors of HEAD; RED (`test`) and GREEN (`feat`) commits for `03-03` Task 2 are both present.
