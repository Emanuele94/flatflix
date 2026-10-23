---
phase: "02"
slug: "portal-download-management-hardening"
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on severity (the blocking gate)
threats_open: 0
asvs_level: 1
created: "2026-10-23"
---

# Phase 02 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| Browser → Caddy → backend | Household phone on the LAN calls the portal API through Caddy (single origin) | Session cookie, search text, opaque download ids |
| Backend → qBittorrent Web API | Backend owns the qBittorrent credentials and session | qBittorrent credentials, info-hashes, categories, save paths (never sent to the browser) |
| Backend → stdout / Docker logs | Audit trail and app logs read by the admin via `docker compose logs` | Client address, search text, torrent names (secrets redacted) |
| Integration tests → real qBittorrent | Opt-in tests against the pinned engine | Synthetic random-hash torrents only |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-02-01 | Information disclosure | GET /api/downloads response | high | mitigate | Fixed 7-key item, HMAC id, `type` instead of category (`listing.py`); `test_downloads_api.py`, `test_no_leaks.py` | closed |
| T-02-02 | Information disclosure | Category filter | high | mitigate | Exact-match `type_for_category` (`content_type.py`) | closed |
| T-02-03 | Elevation of privilege | GET /api/downloads | high | mitigate | `protected_router()`; 401 tests | closed |
| T-02-04 | Denial of service | Session on qBittorrent failure | medium | mitigate | 502 `qbit_refused`/`qbit_unreachable`, never 401 | closed |
| T-02-05 | Information disclosure | WARNING log on qBittorrent failure | medium | mitigate | Class name and status only | closed |
| T-02-06 | Spoofing | allowlist main-video choice | high | mitigate | Size against all video formats, 10% rule (`allowlist.py`) | closed |
| T-02-07 | Tampering | Sample-named files | low | accept | See Accepted Risks AR-01 | closed |
| T-02-08 | Information disclosure | WARNING lines for 415/409 | medium | mitigate | Job id, class, status only (`pipeline.py`) | closed |
| T-02-09 | Tampering | Caddy cache rules | medium | mitigate | `immutable` only on 2xx, `no-cache` on index (`web/Caddyfile`) | closed |
| T-02-10 | Denial of service | Docker log files | medium | mitigate | json-file 10m x 5 on all services (`docker-compose.yml`) | closed |
| T-02-11 | Information disclosure | Global security headers | low | mitigate | Global header block unchanged | closed |
| T-02-12 | Information disclosure | Job rows in list | high | mitigate | Same 7 keys, job id as id (`_job_item`) | closed |
| T-02-13 | Denial of service | JobRegistry growth | low | mitigate | MAX_JOBS=500, prune finished oldest first (`jobs.py`) | closed |
| T-02-14 | Repudiation | Failed attempts lost on restart | low | accept | See Accepted Risks AR-02 | closed |
| T-02-15 | Denial of service | POST /api/search, /api/download | high | mitigate | Sliding-window 10/20 per minute, 429 + Retry-After (`throttle.py`) | closed |
| T-02-16 | Denial of service | Throttle state growth | low | mitigate | Slot taken only after auth/readiness/validation; residual IN-01 (no eviction) is info-level | closed |
| T-02-17 | Spoofing | Client address as throttle key | medium | mitigate | Caddy overwrites X-Forwarded-For; trusted-peer right-most entry (`proxy.py`) | closed |
| T-02-18 | Denial of service | Household locked out by polling | medium | mitigate | No throttle on polls, list, DELETE, session | closed |
| T-02-19 | Tampering (XSS) | DownloadRow name rendering | high | mitigate | Text child only; no innerHTML anywhere in `frontend/src` | closed |
| T-02-20 | Information disclosure | Error rendering in Downloads | medium | mitigate | Only `MSG` strings rendered | closed |
| T-02-21 | Tampering | CSP compliance | medium | mitigate | No inline `style=`; progress via class | closed |
| T-02-22 | Denial of service | Polling load | low | mitigate | 5 s after settle, paused when hidden, cleanup on unmount | closed |
| T-02-23 | Tampering (IDOR) | DELETE id resolution | high | mitigate | `^[0-9a-f]{16}$` path; HMAC match on Film/SerieTV rows only | closed |
| T-02-24 | Tampering / info loss | deleteFiles decision | high | mitigate | `cancel_deletes_files` (in-progress, progress < 1, no `completion_on`) + live re-read before delete (WR-01/WR-02 fixes 9745bc9, 76c2328) | closed |
| T-02-25 | Tampering | qBittorrent `hashes` parameter | high | mitigate | Hashes only from qBittorrent rows; "all" → 422 | closed |
| T-02-26 | Denial of service | Concurrent/repeated cancels | low | mitigate | `asyncio.Lock`; one `torrents/delete` | closed |
| T-02-27 | Repudiation | Ghost failure rows after cancel | low | mitigate | Job set CANCELLED before delete; cancelled jobs not listed | closed |
| T-02-28 | Spoofing (CSRF) | DELETE with session cookie | medium | mitigate | `same_site=lax`, no body, CSP `form-action 'self'` | closed |
| T-02-29 | Information disclosure | Search error/row rendering | medium | mitigate | 429 mapped to `MSG` | closed |
| T-02-30 | Tampering | Restored row states | low | mitigate | Allow-listed `ROW_STATES` | closed |
| T-02-31 | Information disclosure | Any log line | high | mitigate | Typed audit helpers; `RedactingFilter` on root + uvicorn (WR-04 fix 8e3a5a2) | closed |
| T-02-32 | Repudiation (log forging) | Free text in audit lines | medium | mitigate | JSON-escaped, 200-char cut | closed |
| T-02-33 | Repudiation | Missing audit events | medium | mitigate | login/logout/search/throttle/download/cancel/remove/error wired | closed |
| T-02-34 | Information disclosure | Audit log content | medium | mitigate | stdout only, rotation, admin warning in `docs/setup.md` | closed |
| T-02-35 | Denial of service | uvicorn access formatting | medium | mitigate | Redaction keeps args structure | closed |
| T-02-36 | Tampering | Audit silenced by LOG_LEVEL | low | mitigate | `app.audit` pinned to INFO | closed |
| T-02-37 | Tampering / info loss | Accidental cancel | medium | mitigate | In-row confirm, focus on "No, keep it"; server decides files | closed |
| T-02-38 | Tampering | DELETE request content | high | mitigate | Id-only DELETE, no body | closed |
| T-02-39 | Information disclosure | Action failure rendering | low | mitigate | Only `MSG.actionFailed` | closed |
| T-02-40 | Tampering | Integration tests on the real engine | high | mitigate | Own random hash only, delete in `finally`, opt-in via `QBIT_TEST_URL` | closed |
| T-02-41 | Information disclosure | docs/setup.md | medium | mitigate | Documentation-range address 203.0.113.7; repo-hygiene LAN test | closed |
| T-02-42 | Repudiation | Phase sign-off | low | mitigate | `02-UAT.md` complete, 3/3 passed | closed |
| T-02-SC (x11) | Tampering | npm/pip packages and images (one per plan) | high | mitigate | No manifest, lockfile, Dockerfile or image change in the phase | closed |

*Status: open · closed · open — below high threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above workflow.security_block_on count toward threats_open*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

Full per-threat evidence (file:line and test names) is in the 2026-10-23 gsd-security-auditor verdict.

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-01 | T-02-07 | A sample-named large file of another format is ignored when sizing the main video; at worst the allowed main video is kept as before, and nothing outside the FILT-02 allowlist is downloaded | Plan 02-02 threat model | 2026-10-23 |
| AR-02 | T-02-14 | Failed-attempt rows live in memory (D-29) and a backend restart clears them; the admin log keeps the failure | Plan 02-04 threat model | 2026-10-23 |
| AR-03 | WR-04 residual | The log filter blanks secrets of 8+ characters only; `docs/setup.md` asks for a qBittorrent password of at least 8 characters | Code review fix 8e3a5a2 | 2026-10-23 |
| AR-04 | T-02-17 residual | When the host hides client addresses (WSL2/NAT), the household shares one rate-limit budget and audit lines show the gateway address; documented in `docs/setup.md` "Rate limits" | Plan 02-05/02-11, UAT | 2026-10-23 |

*Accepted risks do not resurface in future audit runs.*

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-10-23 | 53 | 53 | 0 | gsd-security-auditor (ASVS L1, block_on high) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-10-23
