---
status: testing
phase: 01-portal-search-start-download
source: [01-VERIFICATION.md]
started: 2026-10-22T15:04:27Z
updated: 2026-10-22T15:04:27Z
---

Re-test round after gap closure G-01-3 (plans 01-14, 01-15, 01-16). The previous round (tests 1, 2, 4 passed; 3 issue; 5 skipped) is in git history.

## Current Test

number: 1
name: UAT 3 phone re-test, magnet-printing plugin result (limetorrents / torrentproject, e.g. Tears of Steel)
expected: |
  Row shows Preparing, then "Started ✓". Reload the tab during Preparing: the same results and the Movie/TV Series choice come back, the row is still Preparing and then ends on Started. After completion the file is in the host Film folder. No path, category or qBittorrent name is visible.
awaiting: user response

## Tests

### 1. UAT 3 phone re-test, magnet-printing plugin result (limetorrents / torrentproject, e.g. Tears of Steel)
expected: Row shows Preparing, then "Started ✓". Reload during Preparing restores the results, the Movie/TV Series choice and the Preparing row, which ends on Started. The file lands in the host Film folder. Nothing technical is visible.
result: [pending]

### 2. UAT 3 phone re-test, .webm-only result (piratebay Tears of Steel 1080p webm)
expected: Row says "This video format isn’t supported. Try another result.", no Started or check mark, the button is disabled, nothing appears in qBittorrent, and a reload still shows the same message.
result: [pending]

### 3. Real-engine guard re-run (needs docker-compose.admin.yml up; adds live open-licensed torrents)
expected: QBIT_TEST_URL=http://127.0.0.1:8088 uv run --project backend --frozen pytest backend/tests/integration -m integration -q -rs gives 4 passed, 0 skipped.
result: [pending]

### 4. Two-phone lockout check on the Ubuntu production server (deferred, not a Phase 1 blocker)
expected: 5 wrong logins from phone A do not lock phone B out when the server sees real client addresses.
result: [pending]

## Summary

total: 4
passed: 0
issues: 0
pending: 4
skipped: 0
blocked: 0

## Gaps
