---
status: complete
phase: 01-portal-search-start-download
source: [01-VERIFICATION.md]
started: 2026-10-22T15:04:27Z
updated: 2026-10-22T15:25:23.888Z
---

Re-test round after gap closure G-01-3 (plans 01-14, 01-15, 01-16). The previous round (tests 1, 2, 4 passed; 3 issue; 5 skipped) is in git history.

## Current Test

[testing complete]

## Tests

### 1. UAT 3 phone re-test, magnet-printing plugin result (limetorrents / torrentproject, e.g. Tears of Steel)
expected: Row shows Preparing, then "Started ✓". Reload during Preparing restores the results, the Movie/TV Series choice and the Preparing row, which ends on Started. The file lands in the host Film folder. Nothing technical is visible.
result: issue
reported: "tears of steel give download failed try again it's webm"
severity: major

### 2. UAT 3 phone re-test, .webm-only result (piratebay Tears of Steel 1080p webm)
expected: Row says "This video format isn’t supported. Try another result.", no Started or check mark, the button is disabled, nothing appears in qBittorrent, and a reload still shows the same message.
result: issue
reported: "tears if steek giuves diwbnkiad failed as said before"
severity: major

### 3. Real-engine guard re-run (needs docker-compose.admin.yml up; adds live open-licensed torrents)
expected: QBIT_TEST_URL=http://127.0.0.1:8088 uv run --project backend --frozen pytest backend/tests/integration -m integration -q -rs gives 4 passed, 0 skipped.
result: pass

### 4. Two-phone lockout check on the Ubuntu production server (deferred, not a Phase 1 blocker)
expected: 5 wrong logins from phone A do not lock phone B out when the server sees real client addresses.
result: skipped
reason: "Deferred follow-up: defer"

## Summary

total: 4
passed: 1
issues: 2
pending: 0
skipped: 1
blocked: 0

## Deferred Follow-Ups

- test: 4
  idea: "defer (two-phone lockout check needs the Ubuntu production server)"
  deferred_at: 2026-10-22

## Gaps

- gap_id: G-01-1
  truth: "Tapping Download on a Tears of Steel result reaches Started ✓, or for a .webm-only torrent shows 'This video format isn’t supported. Try another result.'"
  status: failed
  reason: "User reported: tears of steel give download failed try again it's webm"
  severity: major
  test: 1
  artifacts: []
  missing: []

- gap_id: G-01-2
  truth: "A .webm-only Tears of Steel result shows 'This video format isn’t supported. Try another result.' with the button disabled, not a generic failure"
  status: failed
  reason: "User reported: tears if steek giuves diwbnkiad failed as said before (i.e. Tears of Steel gives 'download failed' instead of the unsupported-format message)"
  severity: major
  test: 2
  artifacts: []
  missing: []
