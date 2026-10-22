---
phase: 01
review: 01-REVIEW.md
titles: json
findings:
  - id: WR-01
    severity: warning
    disposition: open
    title: "A torrent whose main video is outside the allowlist is \"Started\" if it holds any small allowed video"
  - id: WR-02
    severity: warning
    disposition: open
    title: "The \"no payload before the allowlist\" guarantee is proven only by the fake and an opt-in test"
  - id: WR-03
    severity: warning
    disposition: open
    title: "A restored search that the backend no longer knows keeps a stale saved record and an error on every reload"
  - id: IN-01
    severity: info
    disposition: open
    title: "Saved `result_id` is validated by a regex that coerces non-strings"
  - id: IN-02
    severity: info
    disposition: open
    title: "`.ts` in `OTHER_VIDEO_EXTENSIONS` also matches non-video files"
  - id: IN-03
    severity: info
    disposition: open
    title: "Test name is over the 100-column limit"
  - id: CR-01
    severity: critical
    disposition: fixed
    title: "`reconcile()` deletes a running download and its files when the pending tag was left behind"
  - id: WR-04
    severity: warning
    disposition: fixed
    title: "The \"stop before any payload\" guarantee for non-magnet results is unproven"
  - id: WR-05
    severity: warning
    disposition: fixed
    title: "Rows can stay on \"Preparing\" forever (job gone after restart, 404/401, or give-up)"
  - id: WR-06
    severity: warning
    disposition: fixed
    title: "Readiness is checked once; later qBittorrent config drift is not detected"
  - id: WR-07
    severity: warning
    disposition: fixed
    title: "Login lockout is per source address only, and the whole household can be locked out"
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
open: 10
total: 15
recorded: 2026-10-22T15:01:08.389Z
---

# Phase 01: Code Review Disposition

| Finding | Severity | Disposition | Source |
|---------|----------|-------------|--------|
| WR-01 | warning | open | - |
| WR-02 | warning | open | - |
| WR-03 | warning | open | - |
| IN-01 | info | open | - |
| IN-02 | info | open | - |
| IN-03 | info | open | - |
| CR-01 | critical | fixed | 01-REVIEW-FIX.md (not in the current review) |
| WR-04 | warning | fixed | 01-REVIEW-FIX.md (not in the current review) |
| WR-05 | warning | fixed | 01-REVIEW-FIX.md (not in the current review) |
| WR-06 | warning | fixed | 01-REVIEW-FIX.md (not in the current review) |
| WR-07 | warning | fixed | 01-REVIEW-FIX.md (not in the current review) |
| IN-04 | info | open | - (not in the current review) |
| IN-05 | info | open | - (not in the current review) |
| IN-06 | info | open | - (not in the current review) |
| IN-07 | info | open | - (not in the current review) |

Dispositions: `open` (recorded, not yet triaged), `fixed`, `skipped`, `deferred`.
Set `deferred` by hand and put the reason in the Source cell; both are preserved. A `|` in the reason is kept as prose and escaped on the next run.
Re-running the gate keeps every row it can. A row the current review no longer reports is kept and its Source cell flagged, so a finding does not leave this record silently. ONE exception: when a finding id is REUSED by a different finding, the earlier decision cannot keep a row — the id is taken — and it is dropped. A RECORDED decision (anything but `open`) is named on the console when that happens; a row still at `open` is replaced silently, because `open` records no decision to lose.
