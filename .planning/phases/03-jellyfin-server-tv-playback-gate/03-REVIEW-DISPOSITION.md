---
phase: 03-jellyfin-server-tv-playback-gate
review: 03-REVIEW.md
critical: 0
warning: 8
info: 7
open: 7
fixed: 8
---

# Phase 03 code review disposition

Every finding defaults to `open` until it is fixed, deferred or rejected.

| ID | Severity | Finding | Disposition |
|----|----------|---------|-------------|
| WR-01 | warning | `watch` prompt takes type-ahead as the answer; `yy` saves no answer, silently (known issue, confirmed) | fixed |
| WR-02 | warning | Ctrl-C at the prompt discards the play being answered | fixed |
| WR-03 | warning | A corrupt `results.json` is silently treated as empty and then overwritten | fixed |
| WR-04 | warning | `name_scan.py report` can overwrite the committed real result and decision; a sample `run` clobbers real results | fixed |
| WR-05 | warning | Troubleshooting row tells the admin to restart a service that does not exist | fixed |
| WR-06 | warning | A long single-file torrent name loses its extension and aborts the whole scan | fixed |
| WR-07 | warning | `jellyfin/config` (database, password hashes, access tokens) is created group-writable and world-readable | fixed |
| WR-08 | warning | Jellyfin is served from the portal's origin with `script-src 'unsafe-inline'` | fixed |
| IN-01 | info | Dead `HEALTHCHECK_URL` environment variable | open |
| IN-02 | info | `read_env_value` and `read_env_optional` are unused in `jellyfin_setup.py` | open |
| IN-03 | info | `_load()` helper duplicated, and shared modules loaded several times | open |
| IN-04 | info | Smaller robustness gaps in `jellyfin_setup.py` | open |
| IN-05 | info | Admin tokens are created on every run and never revoked | open |
| IN-06 | info | Caddy details | open |
| IN-07 | info | Other low-risk observations | open |
