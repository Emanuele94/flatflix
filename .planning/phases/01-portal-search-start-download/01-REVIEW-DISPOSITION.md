---
phase: 01
review: 01-REVIEW.md
titles: json
findings:
  - id: CR-01
    severity: critical
    disposition: open
    title: "`reconcile()` deletes a running download and its files when the pending tag was left behind"
  - id: WR-01
    severity: warning
    disposition: open
    title: "A job that fails after the add leaves a stopped torrent, and the next tap reports \"Already added\""
  - id: WR-02
    severity: warning
    disposition: open
    title: "`--forwarded-allow-ips \"*\"` lets any container on the `qbit` network spoof the throttle key"
  - id: WR-03
    severity: warning
    disposition: open
    title: "Untrusted plugin `fileUrl` is passed to qBittorrent/plugin downloader without a scheme check"
  - id: WR-04
    severity: warning
    disposition: open
    title: "The \"stop before any payload\" guarantee for non-magnet results is unproven"
  - id: WR-05
    severity: warning
    disposition: open
    title: "Rows can stay on \"Preparing\" forever (job gone after restart, 404/401, or give-up)"
  - id: WR-06
    severity: warning
    disposition: open
    title: "Readiness is checked once; later qBittorrent config drift is not detected"
  - id: WR-07
    severity: warning
    disposition: open
    title: "Login lockout is per source address only, and the whole household can be locked out"
  - id: IN-01
    severity: info
    disposition: open
    title: "A cached result's `type` is overwritten by a later search of the other type"
  - id: IN-02
    severity: info
    disposition: open
    title: "`is_sample_name` rejects legitimate titles containing the word \"sample\"; some common video containers are not allowed"
  - id: IN-03
    severity: info
    disposition: open
    title: "Unbounded request body size before authentication"
  - id: IN-04
    severity: info
    disposition: open
    title: "Compose hardening and publishing defaults"
  - id: IN-05
    severity: info
    disposition: open
    title: "Sessions cannot be revoked server-side"
  - id: IN-06
    severity: info
    disposition: open
    title: "Health banner never refreshes"
  - id: IN-07
    severity: info
    disposition: open
    title: "Config accepts identical or nested save paths, and the credentials init script can silently do nothing"
open: 15
total: 15
recorded: 2026-10-22T11:45:53.372Z
---

# Phase 01: Code Review Disposition

| Finding | Severity | Disposition | Source |
|---------|----------|-------------|--------|
| CR-01 | critical | open | - |
| WR-01 | warning | open | - |
| WR-02 | warning | open | - |
| WR-03 | warning | open | - |
| WR-04 | warning | open | - |
| WR-05 | warning | open | - |
| WR-06 | warning | open | - |
| WR-07 | warning | open | - |
| IN-01 | info | open | - |
| IN-02 | info | open | - |
| IN-03 | info | open | - |
| IN-04 | info | open | - |
| IN-05 | info | open | - |
| IN-06 | info | open | - |
| IN-07 | info | open | - |

Dispositions: `open` (recorded, not yet triaged), `fixed`, `skipped`, `deferred`.
Set `deferred` by hand and put the reason in the Source cell; both are preserved. A `|` in the reason is kept as prose and escaped on the next run.
Re-running the gate keeps every row it can. A row the current review no longer reports is kept and its Source cell flagged, so a finding does not leave this record silently. ONE exception: when a finding id is REUSED by a different finding, the earlier decision cannot keep a row — the id is taken — and it is dropped. A RECORDED decision (anything but `open`) is named on the console when that happens; a row still at `open` is replaced silently, because `open` records no decision to lose.
