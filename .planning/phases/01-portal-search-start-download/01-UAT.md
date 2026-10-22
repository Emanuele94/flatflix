---
status: diagnosed
phase: 01-portal-search-start-download
source: [01-VERIFICATION.md]
started: 2026-10-22T12:27:12Z
updated: 2026-10-22T13:50:47Z
---

## Current Test

[testing complete]

## Tests

### 1. Phone, 360 px layout (PUI-01, SC1/SC2)
expected: English login first; after login toggle, search box and rows fit with no sideways scroll; buttons easy to tap.
result: pass

### 2. LAN reachability through the Windows firewall (SC1, SC4)
expected: From the phone, http://<laptop-ip>/ loads the portal; http://<laptop-ip>:8088/ and :8000 do NOT answer.
result: pass

### 3. Tap Download on the phone and watch it land (SC3, DOWN-01..03)
expected: Search an open-licensed title (e.g. Tears of Steel), tap Download; row shows Preparing then "Started ✓"; after completion the file is in the host Film folder; no path, category or qBittorrent name on screen.
result: issue
reported: "[screenshot: piratebay Tears of Steel 1080p webm -> \"This file doesn't contain a video. Try another result.\"; limetorrents Tears of Steel 1080p webm -> Preparing] i then refreshed during preparing but i lost browser memory"
severity: major
observed: |
  (a) limetorrents result: qBittorrent shows it stoppedDL, has_metadata=false, tags fx-pending, no files.
      The plugin URL resolved to a magnet but was added stopped (WR-04: stopped=not is_magnet on the
      search URL), so it can never fetch metadata; it will end UNAVAILABLE after METADATA_TIMEOUT.
  (b) piratebay .webm: rejected because .webm is not in the FILT-02 allowlist (as specified), but the
      message says the file has no video, which is wrong for a .webm film.
  (c) a page reload during Preparing loses the row's state; the job keeps running server-side.

### 4. First results within about 2 seconds (SRCH-03)
expected: On the household network, first rows appear roughly 2 s after tapping Search.
result: pass
note: "Big Buck Bunny gave No results: correct, every raw result is under 5 seeders or 500 MB. Timed with Sintel / Tears of Steel."

### 5. Lockout behaviour with real client addresses (WR-07)
expected: Fail 5 logins from one phone; a second phone can still log in. If both count as one address, the shared lockout is the documented Docker Desktop limitation (docs/setup.md).
result: skipped
reason: "Deferred follow-up: laptop B also got 'Too many attempts. Try again in a few minutes.' on the WSL2 dev box, where Docker Desktop hides client addresses (documented in docs/setup.md, Login lockout). Re-check per-address counters on the Ubuntu production server."

## Summary

total: 5
passed: 3
issues: 1
pending: 0
skipped: 1
blocked: 0

## Deferred Follow-Ups

- test: 5
  idea: "laptop B Too many attempts. Try again in a few minutes. -> re-run the per-address lockout check on the Ubuntu production server"
  deferred_at: 2026-10-22

## Gaps

- gap_id: G-01-3
  truth: "Tapping Download on a search result shows Preparing then Started, and the file lands in the Film folder"
  status: failed
  reason: "User reported: [screenshot: piratebay webm -> 'This file doesn't contain a video'; limetorrents webm stuck in Preparing] i then refreshed during preparing but i lost browser memory"
  severity: major
  test: 3
  root_cause: "(a) pipeline.py adds page-URL results with stopped=true (WR-04); the limetorrents/torrentproject downloader resolves to a magnet that inherits addStopped and never fetches metadata, so the job ends UNAVAILABLE after 300 s. (b) .webm is outside the FILT-02 allowlist, and the single 'rejected' status shows the D-13 text 'doesn't contain a video'. (c) Search.jsx keeps rows and job ids only in component state, so a reload loses them while the server job keeps running."
  artifacts:
    - path: "backend/app/download/pipeline.py"
      issue: "stopped=not is_magnet decided from the search URL, not from what the downloader resolves (lines 178-187)"
    - path: "backend/app/qbit/client.py"
      issue: "stopped keyword and docstring encode the WR-04 assumption (lines 269-314)"
    - path: "backend/tests/fakeqbit.py"
      issue: "downloader adds always modeled as .torrent with metadata; stop condition assumed not to hold such a torrent (opposite of qBittorrent source)"
    - path: "backend/tests/test_download_pipeline.py"
      issue: "asserts stopped=true for page URLs (lines 517-576)"
    - path: "frontend/src/Search.jsx"
      issue: "rows, jobs, query, type, search id live only in useState/useRef; nothing persisted"
    - path: "frontend/src/messages.js"
      issue: "MSG.rejected (D-13) cannot distinguish 'no video' from 'video format not accepted'"
  missing:
    - "Send stopCondition=MetadataReceived on every add and never stopped=true (qBittorrent pauses a torrent that has metadata at add time under that stop condition)"
    - "Fake: model a downloader that resolves to a magnet; a stop condition on a torrent with metadata keeps it stopped; flip tests 517-576; add a downloader->magnet case that reaches STARTED with downloaded==0; real-engine test of the limetorrents route"
    - "Persist {type, q, search_id, rows, jobs} to sessionStorage in Search.jsx; on mount restore and resume pollJob for preparing jobs; clear on new search and logout"
    - "webm (user decision 2026-10-22, option B): keep the FILT-02 allowlist; give a rejected-for-format torrent a distinct status/reason and show \"This video format isn't supported. Try another result.\" (amends D-13 copy)"
  debug_session: ".planning/debug/download-preparing-gap.md
