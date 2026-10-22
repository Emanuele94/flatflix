---
status: testing
phase: 01-portal-search-start-download
source: [01-VERIFICATION.md]
started: 2026-10-22T12:27:12Z
updated: 2026-10-22T12:27:12Z
---

## Current Test

number: 1
name: Phone, 360 px layout (PUI-01, SC1/SC2)
expected: |
  On a real phone on the home Wi-Fi, open http://<laptop-ip>/. The English login screen appears first. After login the Movie / TV Series toggle, search box and result rows fit with no sideways scroll, and buttons are easy to tap.
awaiting: user response

## Tests

### 1. Phone, 360 px layout (PUI-01, SC1/SC2)
expected: English login first; after login toggle, search box and rows fit with no sideways scroll; buttons easy to tap.
result: [pending]

### 2. LAN reachability through the Windows firewall (SC1, SC4)
expected: From the phone, http://<laptop-ip>/ loads the portal; http://<laptop-ip>:8088/ and :8000 do NOT answer.
result: [pending]

### 3. Tap Download on the phone and watch it land (SC3, DOWN-01..03)
expected: Search an open-licensed title (e.g. Tears of Steel), tap Download; row shows Preparing then "Started ✓"; after completion the file is in the host Film folder; no path, category or qBittorrent name on screen.
result: [pending]

### 4. First results within about 2 seconds (SRCH-03)
expected: On the household network, first rows appear roughly 2 s after tapping Search.
result: [pending]

### 5. Lockout behaviour with real client addresses (WR-07)
expected: Fail 5 logins from one phone; a second phone can still log in. If both count as one address, the shared lockout is the documented Docker Desktop limitation (docs/setup.md).
result: [pending]

## Summary

total: 5
passed: 0
issues: 0
pending: 5
skipped: 0
blocked: 0

## Gaps
