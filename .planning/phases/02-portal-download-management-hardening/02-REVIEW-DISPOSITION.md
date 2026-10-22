---
phase: 02
review: 02-REVIEW.md
titles: json
findings:
  - id: WR-01
    severity: warning
    disposition: fixed
    title: "\"Completed\" is judged by `progress` alone, so a finished film in a checking state can be offered \"Cancel\" and have its files deleted"
  - id: WR-02
    severity: warning
    disposition: fixed
    title: "Time-of-check/time-of-use gap between reading the row and `torrents/delete?deleteFiles=true`"
  - id: WR-03
    severity: warning
    disposition: fixed
    title: "A failed sweep in `_cancel_job_without_torrent` leaves a cancelled job's torrent stranded, hidden, and possibly resumed"
  - id: WR-04
    severity: warning
    disposition: fixed
    title: "`RedactingFilter` skips non-string `record.msg` and short secrets, though its docstring and docs promise \"never written\""
  - id: IN-01
    severity: info
    disposition: open
    title: "`SlidingWindowThrottle._attempts` never evicts addresses that do not come back"
  - id: IN-02
    severity: info
    disposition: open
    title: "Client-address helper duplicated in five places"
open: 2
total: 6
recorded: 2026-10-22T21:30:39.761Z
---

# Phase 02: Code Review Disposition

| Finding | Severity | Disposition | Source |
|---------|----------|-------------|--------|
| WR-01 | warning | fixed | 02-REVIEW-FIX.md (9745bc9) |
| WR-02 | warning | fixed | 02-REVIEW-FIX.md (76c2328) |
| WR-03 | warning | fixed | 02-REVIEW-FIX.md (c64fdc9) |
| WR-04 | warning | fixed | 02-REVIEW-FIX.md (8e3a5a2) |
| IN-01 | info | open | - |
| IN-02 | info | open | - |

Dispositions: `open` (recorded, not yet triaged), `fixed`, `skipped`, `deferred`.
