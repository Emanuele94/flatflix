---
phase: 03-jellyfin-server-tv-playback-gate
fixed_at: 2026-10-27T00:00:00Z
review_path: .planning/phases/03-jellyfin-server-tv-playback-gate/03-REVIEW.md
iteration: 1
findings_in_scope: 8
fixed: 8
skipped: 0
status: all_fixed
---

# Phase 3: Code Review Fix Report

**Fixed at:** 2026-10-27
**Source review:** .planning/phases/03-jellyfin-server-tv-playback-gate/03-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 8 (0 critical, 8 warning; Info findings out of scope)
- Fixed: 8
- Skipped: 0

**Verification:** per-fix tests ran inside the isolated worktree; the full suite (`uv run --project backend --frozen pytest backend/tests infra/tests -q`) ran there once at the end: 1487 passed, 19 deselected (integration marker), no flaky failure. The worktree was fast-forwarded into the phase branch and removed, so the numbers are reproducible from the main checkout.

## Fixed Issues

### WR-03: A corrupt `results.json` is silently treated as empty and then overwritten

**Files modified:** `scripts/tv_gate.py`, `backend/tests/test_tv_gate_contract.py`
**Commit:** e1ede9c
**Applied fix:** `ResultStore` starts empty only on `FileNotFoundError`. A JSON syntax error raises `Fail("results", "<file> is not valid JSON: fix it or move it away")` and the file is left untouched (the CLI prints it as a normal FAIL line). The old test that expected an empty read for a broken file now asserts the refusal and that the file is unchanged.

### WR-01: `watch` prompt takes type-ahead as the answer; `yy` saves no answer, silently

**Files modified:** `scripts/tv_gate.py`, `backend/tests/test_tv_gate_contract.py`
**Commit:** c89c5ea
**Applied fix:** `ask_ok()` first drains stdin (`termios.tcflush`, only on a TTY, no-op where termios is missing), accepts `y/yes/n/no`, treats an empty line or EOF as skip, and asks again on anything else. `record_play` prints `recorded: yes|no|no answer`. Tests cover each answer, re-ask on `yy`/`yse`, the drain call, and the no-TTY no-op.

### WR-02: Ctrl-C at the prompt discards the play being answered

**Files modified:** `scripts/tv_gate.py`, `backend/tests/test_tv_gate_contract.py`
**Commit:** 6fb8310
**Applied fix:** `ResultStore.add` now returns the stored dict. `record_play` stores and saves before asking, then writes the answer into that stored dict and saves again, so Ctrl-C at the prompt keeps the play (with `ok: null`). `cmd_watch` keeps finished plays in a `pending` list and a `flush_unrecorded()` helper that the Ctrl-C path and the "Jellyfin does not answer" (`return 1`) path both call, so other plays finished in the same poll and plays still in progress are saved too. Four tests drive `cmd_watch` with scripted polls; three of them fail on the old code. The module docstring wording was updated.

### WR-06: A long single-file torrent name loses its extension and aborts the whole scan

**Files modified:** `scripts/name_scan.py`, `backend/tests/test_name_scan_contract.py`
**Commit:** 8725eb9
**Applied fix:** New `file_component()` splits a known video extension off before `safe_component` cuts at the byte cap, then re-appends it. Used for a single-file torrent name and for `inner`. A bare extension name such as `.mkv` still yields `unnamed.mkv`. Three tests: a 230-byte name with `.mkv` and `.MP4`, a long multibyte inner name (cut on a character boundary), and the bare-extension case.

### WR-04: `name_scan.py report` can overwrite the committed real result and decision; a sample `run` clobbers real results

**Files modified:** `scripts/name_scan.py`, `backend/tests/test_name_scan_contract.py`
**Commit:** 3f7b951
**Applied fix:** (1) `cmd_run` writes a sample run only to `sample-results.json` and a new `sample-table.md`; `results.json` and `table.md` hold real runs only. (2) `cmd_report` reads the existing report, and when `--decision` is not given it keeps the recorded Decision text (the pending line is not treated as a decision). (3) It refuses (`Fail("report", ...)`) to replace a report that already holds real counts when there are no real results to rebuild them. `cmd_report` still ignores an old results file whose source is not `real`. Five tests: a sample run after a real run leaves results and table alone, decision kept, decision replaced when given, refusal, and a fresh report still says "Not run yet" and "Pending".

Status: fixed. The report-flow rule (keep the decision, refuse to replace real counts) is a state-handling change; the committed `docs/naming-scan.md` was not regenerated.

### WR-05: Troubleshooting row tells the admin to restart a service that does not exist

**Files modified:** `docs/setup.md`, `infra/tests/test_docs_contract.py`
**Commit:** 160c9a3
**Applied fix:** The command is now `docker compose up -d --build --wait web`. A new docs contract test parses every printed `docker compose ...` command in `docs/*.md` and checks the service names against `docker-compose.yml` and `docker-compose.admin.yml`; it failed on the old text. A second test proves the parser with mutated samples.

### WR-07: `jellyfin/config` is created group-writable and world-readable

**Files modified:** `scripts/init-host-dirs.sh`, `docs/ports-and-media.md`, `infra/tests/test_init_host_dirs.py` (new)
**Commit:** 7b6cab9
**Applied fix:** `jellyfin/config`, `jellyfin/config/config` and `jellyfin/cache` are set to `0700` (the script already chmods on every run, so an existing install is tightened on its next run); the other folders stay `0775`, `rejected` stays `0700`. Jellyfin runs as `PUID:PGID`, the owner, so it is unaffected. The script was NOT run against the live data in this session and the live stack was not touched. `docs/ports-and-media.md` notes that the helper scripts reading `jellyfin/config/log` and `metadata` must run as the `PUID` user. The new test runs the script in a temporary layout with a test-written env file (the repo's own is never read) and checks the modes, including tightening an existing `0775` folder.

### WR-08: Jellyfin is served from the portal's origin with `script-src 'unsafe-inline'`

**Files modified:** `web/Caddyfile`, `docs/ports-and-media.md`, `infra/tests/test_docs_contract.py`
**Commit:** 8c7da51
**Applied fix:** Documentation only; the CSP behaviour is unchanged (accepted architecture decision D-04). A comment next to the Jellyfin policy in `web/Caddyfile` records the accepted risk, and a new section "One origin for the portal and Jellyfin" in `docs/ports-and-media.md` explains what an injected script could and could not reach (the session cookie is HttpOnly, so script cannot read it, but the browser still sends it to the same origin) and lists the mitigations to use later (scope the cookie to `Path=/api`, or a separate host or port). A docs test pins both places. The optional regression test on `Set-Cookie` scope was not added because no cookie path change was made.

## Skipped Issues

None. Info findings IN-01 to IN-07 are out of scope for `critical_warning` and were not touched.

## Notes for the orchestrator

- Eight fix commits are on `gsd/phase-03-jellyfin-server-tv-playback-gate` (first e1ede9c, last 8c7da51); the temporary review-fix branch and worktree were removed and the recovery sentinel deleted.
- Not committed (by design): this file, `.planning/state.json`, `.planning/config.json`, `.planning/research/`.
- Items for a human to confirm (logic-level changes that syntax checks cannot prove): WR-02 (interrupt-safe recording flow in `cmd_watch`) and WR-04 (report decision-preserving and refusal rules). Both are covered by new behavioural tests.

---

_Fixed: 2026-10-27_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
