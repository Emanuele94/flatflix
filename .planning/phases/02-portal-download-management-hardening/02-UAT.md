---
status: testing
phase: 02-portal-download-management-hardening
source: [02-VERIFICATION.md]
started: 2026-10-22T21:02:49Z
updated: 2026-10-22T21:02:49Z
---

## Current Test

number: 1
name: Phone check (plan 02-11 Task 2, steps 1-8)
expected: |
  On a real phone on the LAN: follow a download with progress and time left; cancel one and confirm it is gone in qBittorrent; the outage banner clears by itself; a plain reload picks up a redeploy; the rate-limit message shows; audit lines carry the phone's address and no password (on the WSL2 dev host they show the Docker gateway address instead).
awaiting: user response

## Tests

### 1. Phone check (plan 02-11 Task 2, steps 1-8)
expected: Each step behaves as plan 02-11 describes on a real phone on the LAN
result: [pending]

### 2. Visual backstops on iOS Safari and Android Chrome
expected: Layout holds at 320 px, a 200-character name does not break the row, progress bar colours and the Preparing animation render, 48 px buttons and side-by-side confirm buttons are comfortably tappable, focus ring visible
result: [pending]

### 3. Decision on code-review WR-01 / WR-02 / WR-03
expected: A recorded disposition for each (fix before shipping, or accept and defer) in 02-REVIEW-DISPOSITION.md
result: [pending]

## Summary

total: 3
passed: 0
issues: 0
pending: 3
skipped: 0
blocked: 0

## Gaps
