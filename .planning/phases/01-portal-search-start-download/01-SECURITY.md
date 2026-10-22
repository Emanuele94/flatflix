---
phase: "01"
slug: "portal-search-start-download"
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on severity (the blocking gate)
threats_open: 0
asvs_level: 1
created: "2026-10-22"
---

# Phase 01 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.
> Register built from the `<threat_model>` blocks of plans 01-01..01-16 and verified by gsd-security-auditor (ASVS L1, block_on: high).

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| Phone browser → Caddy (port 80, LAN) | Only published port; serves the SPA and proxies `/api` | Portal password, session cookie, search queries, result ids |
| Caddy → backend (Docker network) | Backend trusts forwarded client address only from the `web` peer | Proxied API requests, client IP for the login limiter |
| Backend → qBittorrent Web API v2 (private `qbit` network) | Backend owns qBittorrent credentials and session cookie | qBittorrent credentials, torrent URLs, categories, file priorities |
| qBittorrent → search plugins / indexers / swarm | Untrusted third-party result names, URLs and torrent payloads | Result metadata, torrent metadata, file payloads |
| Repository / build context → images and git history | Secrets and host data must stay out of tracked files and images | `.env`, qBittorrent config/hash, host media, LAN addresses |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-01-01 | Information disclosure | .gitignore | high | mitigate | `.gitignore:1-6`; `infra/tests/test_repo_hygiene.py:170,184` | closed |
| T-01-02 | Information disclosure | compose qbittorrent/backend ports | high | mitigate | no `ports:` on qbittorrent/backend; `test_compose_invariants.py:173,181,200` | closed |
| T-01-03 | Information disclosure | health, logs, QbitClient repr | high | mitigate | `routers/health.py:28-33`; `qbit/client.py:102`; tests in `test_health.py`, `test_qbit_client.py` | closed |
| T-01-04 | Denial of service | QbitClient login retries | medium | mitigate | backoff and single re-login under lock, `qbit/client.py:69-139` | closed |
| T-01-05 | Information disclosure | qBittorrent.conf PBKDF2 hash | high | mitigate | written only into /config by `10-credentials.sh`; ignored by git | closed |
| T-01-06 | Elevation of privilege | backend container | medium | mitigate | non-root uid 10001, `backend/Dockerfile:20-21` | closed |
| T-01-07 | Tampering | allowlist.decide | high | mitigate | final lower-cased extension, samples/no-video rejected, `download/allowlist.py` | closed |
| T-01-08 | Spoofing | filters.normalize_and_filter | medium | mitigate | `search/filters.py:240-248`; `test_filters.py` | closed |
| T-01-09 | Information disclosure | web image build context | high | mitigate | `.dockerignore` allowlist | closed |
| T-01-10 | Tampering | SPA script/style loading | medium | mitigate | CSP `default-src 'self'` in `web/Caddyfile:15`; `no-third-party.test.js` | closed |
| T-01-11 | Information disclosure | Docker port publishing | high | mitigate | only web publishes; admin override loopback-only | closed |
| T-01-12 | Information disclosure | tracked files (no LAN IPs, secrets, hashes) | high | mitigate | `test_repo_hygiene.py:201`; Docker bridge IP redacted from `.planning/debug/webm-download-failed.md` (amended before push), infra tests 61 passed | closed |
| T-01-13 | Spoofing | clickjacking | low | mitigate | `X-Frame-Options DENY`, `frame-ancestors 'none'` | closed |
| T-01-14 | Spoofing | POST /api/login | high | mitigate | constant-work argon2 verify, throttle, `auth.py`, `routers/auth.py` | closed |
| T-01-15 | Spoofing | SessionMiddleware key | high | mitigate | ≥32-char key, placeholders rejected, `config.py` | closed |
| T-01-16 | Elevation of privilege | new API routes | high | mitigate | `protected_router`; `test_routes_protected.py`; live 401s | closed |
| T-01-17 | Information disclosure | session cookie on plain HTTP | medium | accept | see AR-01 | closed |
| T-01-18 | Tampering | CSRF | medium | mitigate | SameSite=lax, JSON-only with `extra=forbid` | closed |
| T-01-19 | Spoofing | X-Forwarded-For vs limiter | low | accept | see AR-02 | closed |
| T-01-20 | Tampering | search plugin install | high | mitigate | official repo pinned by commit, `qbit/bootstrap.py`, `config.py` | closed |
| T-01-21 | Tampering | categories and save paths | medium | mitigate | validated absolute paths, no request field | closed |
| T-01-22 | Elevation of privilege | window before FILT-01 active | high | mitigate | `require_ready` 503 until bootstrap done | closed |
| T-01-23 | Information disclosure | doctor CLI output | medium | mitigate | names/paths/counts only | closed |
| T-01-24 | Denial of service | bootstrap retry vs IP ban | medium | mitigate | stop on auth/ban, capped backoff | closed |
| T-01-25 | Tampering | POST /api/search type | high | mitigate | strict Literal, fixed maps, `test_validation.py` | closed |
| T-01-26 | Tampering | query to plugins | medium | mitigate | control chars stripped, 2..100 code points | closed |
| T-01-27 | Denial of service | qBittorrent 5-search limit | medium | mitigate | `le=5`, make-room, 409 recovery, delete on done | closed |
| T-01-28 | Tampering | XSS via result names | medium | mitigate | text children only, no innerHTML, CSP | closed |
| T-01-29 | Information disclosure | search responses | high | mitigate | 7-field whitelist; `test_no_leaks.py` | closed |
| T-01-30 | Tampering / Information disclosure | URL to qBittorrent (SSRF) | high | mitigate | result_id only; server-side URL; public-URL check | closed |
| T-01-31 | Tampering | multi-line urls field | medium | mitigate | single-URL enforcement in client and pipeline | closed |
| T-01-32 | Tampering | data fetched before filtering | high | mitigate | `stopCondition=MetadataReceived`, priorities set and re-read before `start`; residual race see AR-04 | closed |
| T-01-33 | Tampering | category from request | high | mitigate | category derived server-side from type | closed |
| T-01-34 | Information disclosure | download responses | high | mitigate | body is `{status, job_id}` | closed |
| T-01-35 | Denial of service | stranded stopped torrents | medium | mitigate | startup reconcile | closed |
| T-01-36 | Information disclosure | any API response | high | mitigate | canary sweep `test_no_leaks.py` | closed |
| T-01-37 | Information disclosure | smoke output, docs | high | mitigate | secrets never printed; `<laptop-ip>` placeholders | closed |
| T-01-38 | Information disclosure | Windows firewall for port 80 | medium | mitigate | Private profile only, `docs/setup.md` | closed |
| T-01-39 | Spoofing | qBittorrent WebUI login | high | mitigate | credentials rewritten on every start; probe 204/401 | closed |
| T-01-40 | Information disclosure | init script, dev_env, probe output | high | mitigate | key names / status codes only | closed |
| T-01-41 | Denial of service | qBittorrent IP ban from probe | low | accept | see AR-03 | closed |
| T-01-42 | Information disclosure | login error rendering | low | mitigate | fixed MSG strings | closed |
| T-01-43 | Information disclosure | credentials in the browser | medium | mitigate | password cleared; storage holds only whitelisted search data | closed |
| T-01-44 | Denial of service | SPA polling loop | low | mitigate | interval, stop, unmount cleanup | closed |
| T-01-45 | Tampering | false success display | medium | mitigate | success only for `started` | closed |
| T-01-46 | Tampering | download request body | high | mitigate | `{result_id, type}`; backend 422 on extras | closed |
| T-01-47 | Denial of service | job status polling | low | mitigate | 330 s give-up, stop on final status | closed |
| T-01-48 | Information disclosure | compose qbittorrent service | high | mitigate | no ports; compose invariant test | closed |
| T-01-49 | Information disclosure | port publishing bypasses ufw | high | mitigate | admin override `127.0.0.1:8088` only, exact-match test | closed |
| T-01-50 | Elevation of privilege | add form on non-magnet routes | high | mitigate | stop condition on every add, no stopped parameter | closed |
| T-01-51 | Denial of service | downloader magnet stuck in Preparing | medium | mitigate | never a stopped add | closed |
| T-01-52 | Tampering | fake qBittorrent fidelity | medium | mitigate | metadata-complete stop pinned in fake tests | closed |
| T-01-53 | Information disclosure | real-engine guard downloads | low | mitigate | Blender-only filter, opt-in marker, deletes own torrent | closed |
| T-01-54 | Information disclosure | saved search record | low | mitigate | per-tab sessionStorage, 7-field whitelist | closed |
| T-01-55 | Tampering | ids from storage in request paths | medium | mitigate | `^[0-9a-f]{16}$` validation | closed |
| T-01-56 | Denial of service | resumed job polling | low | mitigate | saved start time keeps 330 s limit | closed |
| T-01-57 | Information disclosure | search left after logout | low | mitigate | clear first, generation counter | closed |
| T-01-58 | Elevation of privilege | allowlist widened by wording change | high | mitigate | other-video list only picks the reason; pinned tests | closed |
| T-01-59 | Spoofing | unsupported shown as success | medium | mitigate | warning message, tests | closed |
| T-01-60 | Tampering | compose from a checkout lacking private config | high | mitigate | `${QBITTORRENT_*:?}`, `create_host_path: false` | closed |
| T-01-61 | Information disclosure | WebUI left published after guard | medium | mitigate | loopback only; live 8088 closed | closed |
| T-01-SC (×16, plans 01-01..01-16) | Tampering | supply chain: uv/npm installs, base images | high | mitigate | `--frozen` / `npm ci` with ignore-scripts, registry-only lockfiles, pinned images, manifests unchanged since 01-01 | closed |

*Status: open · closed · open — below high threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above workflow.security_block_on count toward threats_open*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-01 | T-01-17 | Session cookie travels over plain HTTP on the home LAN. Cookie is HttpOnly, SameSite=Lax and signed; HTTPS deferred to EXT-01. | plan 01-03 threat model | 2026-10-22 |
| AR-02 | T-01-19 | X-Forwarded-For spoofing against the login limiter. Residual risk is lower than planned: `--no-proxy-headers`, `TrustedProxyHeaders` from `web` only, Caddy overwrites the header. | plan threat model | 2026-10-22 |
| AR-03 | T-01-41 | One wrong-password probe per run can trigger a qBittorrent IP ban; a container restart clears it. | plan 01-10 threat model | 2026-10-22 |
| AR-04 | T-01-32 (A8) | Residual race between metadata arrival and the stop taking effect. Disallowed files are set to priority 0 before start and the exclusion list is active. No runtime `downloaded` check yet (code review WR-02) — assurance follow-up, not a missing mitigation. | plan 01-08 threat model | 2026-10-22 |

*Accepted risks do not resurface in future audit runs.*

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-10-22 | 77 | 76 | 1 | gsd-security-auditor (T-01-12: Docker bridge IP in a tracked debug note) |
| 2026-10-22 | 77 | 77 | 0 | orchestrator (IP redacted, `infra/tests` 61 passed) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-10-22
