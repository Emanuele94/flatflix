# Phase 1: Portal Search & Start Download - Research

**Researched:** 2026-10-21
**Domain:** FastAPI portal backend over the qBittorrent Web API v2 (search plugins, torrent add/filter), Preact SPA, Caddy single-origin, Docker Compose on a LAN laptop
**Confidence:** HIGH (qBittorrent behaviour was verified by running a real `qbittorrent-nox` 5.2.4 locally; Docker was not available, so compose/image behaviour is cited or flagged)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Stack and serving**
- **D-01:** Portal backend is **FastAPI (Python)**. Resolves the "FastAPI or Node" pending decision in PROJECT.md. — **Reversibility:** costly — every backend module, the qBittorrent client and tests would be rewritten.
- **D-02:** Portal frontend is a **Preact + Vite SPA**, the same stack proposed for the TV app.
- **D-03:** **Caddy is introduced already in Phase 1** (pulled forward from Phase 3). Caddy serves the SPA's static build and reverse-proxies `/api/*` to FastAPI. FastAPI serves API only, no static files. Same origin, no CORS.
- **D-04:** Caddy listens on **host port 80**; the phone opens `http://<laptop>/`. On WSL2 this needs Windows port forwarding, which must be documented. qBittorrent WebUI is not on the LAN (SEC-02) and uses a port that differs from 80 and from the backend's internal port. — **Reversibility:** costly — port is in the documented port map and household bookmarks.
- **D-05:** **One Caddy for both portal and TV app, separated by path** on the same port (e.g. `/portale` and `/tv`, or portal at `/` and TV at `/tv`; exact paths are Claude's discretion). Phase 1 only wires the portal path but the Caddyfile and port map must leave room for the TV path and Jellyfin proxying in Phase 3. The Vite build must use a matching `base` path.

**Search and results**
- **D-06:** Results **fill in live** while the qBittorrent search runs (first results in ~2 s), re-sorted by seeders descending, with a visible "searching" indicator; timeout shows a plain-language message (SRCH-03).
- **D-07:** Hide results below a **minimum seeders threshold**, env `MIN_SEEDERS`, **default 5**. The user wants a "sweet spot": hide dead torrents while keeping enough results that are safe and actually download.
- **D-08:** Anti-fake filtering, all of these:
  - Hide **films that are too small** (configurable env, default ~500 MB; applies to `film` type — Claude decides whether and how a per-episode threshold applies to `serie`).
  - **Only trusted search plugins**: the admin enables only reliable plugins in qBittorrent; the portal uses all enabled plugins. Document this in setup docs; no extra code.
  - **Hide suspicious names** (e.g. containing `.exe`, `password`, `codec`, and similar markers; list is Claude's discretion, keep it configurable or in one place).
  - **Quality badge**: parse `1080p` / `2160p`/`4K` (and similar) from the name and show a badge. Badge only, not a filter.
- **D-09:** Result row: **name (full) + size (human, e.g. "4.2 GB") + seeders prominent**; leechers and source small and grey.
- **D-10:** After tapping Download the user **stays on the results list**; the button turns into "Avviato ✓". Errors and rejections are shown on that row. The user can start more downloads from the same list.

**Torrent acceptance flow (FILT-02)**
- **D-11:** After the tap, the row shows a spinner for up to **~15 s** while the backend waits for metadata. If metadata arrives: show "✓ Avviato" or the rejection. If not: show "In preparazione" and the **backend keeps processing on its own** (background task, not tied to the HTTP request). The final outcome becomes visible in the Phase 2 downloads list.
- **D-12:** Metadata timeout is env `METADATA_TIMEOUT`, **default 5 minutes**; after it the torrent is removed from qBittorrent and marked unavailable.
- **D-13:** Rejection text (no allowed video file): **"Questo file non contiene un video. Prova un altro risultato."** No technical detail.
- **D-14:** Multi-video torrents: download **all allowed video files** (full seasons are fine) but set **priority 0 on samples**: files with "sample" in the name, or tiny compared with the main video. Subtitles stay allowed.

**Login and access**
- **D-15:** **One shared portal account** from env. No user database.
- **D-16:** Session lasts **30 days**: persistent, HttpOnly cookie signed with `SECRET_KEY`.
- **D-17:** Portal password stored as a **hash** (bcrypt or argon2) in env `APP_PASS_HASH` instead of plaintext `APP_PASS` (deviation from qbit-wrapper.md §12). Provide a documented helper command to generate the hash. `.env.example` holds a placeholder only. — **Reversibility:** reversible.
- **D-18:** **Basic login brute-force limit already in Phase 1** (e.g. 5 failed attempts per 15 min per IP). Full rate limiting stays in Phase 2.

### Claude's Discretion
- Exact Caddy paths for portal vs TV (D-05).
- How live results reach the browser (polling vs SSE) as long as D-06 holds.
- Suspicious-name list, sample-size heuristic, per-episode size threshold for series.
- Visual design of the portal (no area discussed); keep it simple, large tap targets, Italian UI text.
- Host media paths, PUID/PGID and incomplete-downloads folder layout (MEDIA-01) — not discussed; follow requirements.

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope. (Caddy was pulled forward from Phase 3 into Phase 1 by user choice; Phase 3 still owns the Jellyfin/TV routes.)

Out of this phase (from CONTEXT.md domain): download list, cancel, audit logs and full rate limiting (Phase 2); quarantine/ffprobe (Phase 2.1); Jellyfin and the TV app (Phase 3+).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| AUTH-01 | Login with portal's own credentials before any search/download/status page or endpoint | Starlette `SessionMiddleware` + router-level auth dependency; route-enumeration test; argon2 verify (Standard Stack, Pattern 1, Validation) |
| SEC-01 | qBittorrent credentials/session cookie only in backend | Backend-only `QbitClient`; response-scan test; qB never published to LAN (Pattern 5) |
| SEC-02 | qBittorrent WebUI only on internal network or loopback | Two compose networks, no `ports:` for qB except optional `127.0.0.1:` bind; compose-invariant test (Pattern 5, Pitfall 9) |
| SEC-03 | Only `type` = `film`/`serie`; never a path or category from the browser | Pydantic `Literal`; server-side category map; verified that qB auto-creates ANY category sent (Pitfall 4) |
| SEC-04 | All config from env; `.env.example` placeholders only; no secrets/LAN IPs | pydantic-settings, placeholder rejection, hygiene test, `.gitignore` list (Pattern 6) |
| SRCH-01 | Choose Film/Serie, search via plugins with category `movies`/`tv` | Verified `search/start` params, `plugins=enabled`, `category=movies|tv` (Pattern 2) |
| SRCH-02 | Name, size, seeders, leechers, source, sorted by seeders | Verified result fields incl. `engineName`; normalization rules incl. `-1` unknowns (Pattern 2) |
| SRCH-03 | First results ~2 s, timeout = plain message | Measured first result at 2.1 s and 1.7 s; snapshot-polling design; `SEARCH_TIMEOUT` + `search/stop` (Pattern 2) |
| DOWN-01 | One tap starts download | Result-token `POST /api/download` (Pattern 3) |
| DOWN-02 | Backend assigns category automatically | Fixed server-side map `film→Film`, `serie→SerieTV` (Pattern 3) |
| DOWN-03 | Categories → `/media/Film`, `/media/SerieTV`; created at startup; no append-category-name; no path from browser | Verified: category path applies ONLY with `autoTMM=true`; duplicate create = 409; bootstrap = list, create-if-missing, edit-if-different (Pitfalls 2, 3) |
| PUI-01 | Responsive, usable on smartphone | Plain CSS mobile-first, 44 px targets, vitest + manual phone checklist (Validation) |
| PUI-02 | User never sees qB/paths/categories/credentials | Response DTOs whitelist fields; response-scan test (Pattern 3, Validation) |
| INFRA-01 | Single `docker compose up`; `GET /api/health` | Compose skeleton, healthchecks, health decision (Pattern 5, Open Question 5) |
| INFRA-02 | One documented port map, no collisions | Proposed port map table + compose invariant test (Pattern 5) |
| MEDIA-01 | Host media folders, owner UID/GID, separate incomplete folder | Verified `temp_path` behaviour (`<temp>/<Category>`), host-dir contract, pre-create script (Pattern 5, Pitfall 8) |
| FILT-01 | Startup sets excluded-file-names list | Verified `excluded_file_names` newline format, case-insensitive nested match, priority 0 (Pattern 4) |
| FILT-02 | Add, wait for metadata, check allowlist, prio 0, then start | **Verified deviation:** a *stopped* magnet never fetches metadata; use `stopCondition=MetadataReceived` (Pitfall 1, Pattern 4) |
</phase_requirements>

## Summary

The qBittorrent-facing half of this phase was verified empirically by running a real `qbittorrent-nox` 5.2.4 (WebAPI 2.15.1, the same static `userdocs/qbittorrent-nox-static` binary the linuxserver image ships) on loopback and exercising every endpoint the backend needs. This produced six findings that contradict or extend the design doc and requirement wording, and the plan must absorb all of them: (1) a magnet added `stopped=true` **never fetches metadata** (62 s, still `stoppedDL`, zero files), so FILT-02 as worded would deadlock; the working mechanism is `stopCondition=MetadataReceived` (metadata in ~2 s, `downloaded=0`); (2) category save paths are **ignored unless `autoTMM=true`** is sent; (3) qBittorrent **auto-creates any category name** it receives, so the category must never be user-influenced; (4) some plugins (limetorrents) return an HTTP page as `fileUrl`, not a magnet, which only works through `torrents/add` with `downloader=<engine>` and returns no hash; (5) a fresh linuxserver container has **zero search plugins** and **no way to set a known password** via env; (6) login returns 204/401/403 and a port-suffixed cookie `QBT_SID_<port>` with a 1 h session, and 5 failed logins ban the caller's IP for an hour.

The rest of the stack was smoke-tested on today's versions (FastAPI 0.159.1, Starlette 1.9.0, argon2-cffi 25.1.0, Preact 11.0.1, Vite 8.3.5, Vitest 5.0.5, Caddy 2.11.7): session login with a 30-day HttpOnly signed cookie, Caddy routing with SPA fallback and a reserved `/tv/*`, and a Preact build + test all work. **Docker is not installed in this WSL distro**, so INFRA-01 cannot be verified automatically here; the plan needs a human checkpoint (enable Docker Desktop WSL integration) and should cover compose/network/port rules with a Python invariant test that needs no Docker.

**Primary recommendation:** Build FastAPI with a server-side result cache (browser sends `result_id` + `type`, never a URL/magnet/category), a tag-driven download pipeline using `stopCondition=MetadataReceived` + `autoTMM=true` + fixed categories, a Caddy-fronted SPA at `/`, and pin `lscr.io/linuxserver/qbittorrent:5.2.4` (the version tested here); treat the `stopped` wording in FILT-02/CLAUDE.md as "stop-after-metadata".

## Project Constraints (from CLAUDE.md)

Source: `/home/emanuele/projects/flatflix/CLAUDE.md` (Read this session).
- Public MIT repo: **no secrets, LAN IPs or real credentials committed.**
- Both parts run in Docker on a home laptop on the LAN, used by non-technical household members.
- Backend owns the qBittorrent credentials and session cookie; the browser never sees them, nor any save path.
- The frontend sends only `type` (`film` | `serie`), which maps to category `Film` → `/media/Film` or `SerieTV` → `/media/SerieTV`. (Research refines "sends only type" to `result_id` + `type`; no path/category/URL still holds.)
- App has its own login, separate from qBittorrent; config from env vars.
- Only video and subtitle files may be downloaded (exclusion list + per-file allowlist, torrents added stopped and filtered after metadata). **See Pitfall 1: "added stopped" must be implemented as stop-after-metadata.**
- Completed downloads later go to quarantine (Phase 2.1); keep the save-path design able to change. Dev machine is WSL2; production is a KVM-capable x86_64 Ubuntu Server box: anything host-specific must work on both.
- qBittorrent writes into folders Jellyfin scans; keep completed-torrent info (hash, name, category, content path) reachable from the backend; do not freeze the download request body (STATE.md blocker).
- Port 8080 is used by both frontend and qBittorrent in the design doc: superseded by D-04, never reuse 8080 for two services.
- CLAUDE.md says "Update this file once code and commands exist": the plan should end with a task that updates its Status section with real build/test commands.
- Planning docs in English, UI text in Italian.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Login form, search form, result list, row states, sort display, quality badge | Browser / Client (Preact SPA) | — | Pure presentation; holds no secrets, no URLs, no paths |
| Static SPA delivery, `/api/*` proxy, single origin, reserved `/tv/*` | CDN / Static (Caddy) | — | D-03/D-05: one origin, no CORS; SPA fallback is a Caddy concern |
| Authentication, session cookie, brute-force limit | API / Backend (FastAPI) | — | AUTH-01, D-15..D-18; Caddy only forwards |
| Search orchestration, result normalization, filtering, dedupe, sort, result-token cache | API / Backend | qBittorrent (plugins run there) | Backend owns trust boundary; plugins only produce raw rows |
| Download pipeline (add → metadata → allowlist → prio → start), job registry, reconcile | API / Backend | qBittorrent (state in tags) | D-11/D-12 background work must outlive the HTTP request |
| qBittorrent bootstrap (prefs, categories, plugins) | API / Backend (startup) | qBittorrent config volume | FILT-01/DOWN-03 must hold on every start |
| Search plugins, torrent engine, category→path, excluded-names enforcement | qBittorrent (Database / Storage-adjacent) | — | Stock service, no server code written for it |
| Media + incomplete folders, ownership | Database / Storage (host bind mounts) | qBittorrent container user | MEDIA-01 contract |
| Network isolation of qBittorrent WebUI | Compose networks / host port publishing | — | SEC-02 is enforced by what is NOT published |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| fastapi | 0.159.1 (2026-10-21) | API framework | D-01; smoke-tested [VERIFIED: PyPI + local venv run] |
| starlette (via fastapi) | 1.9.0 | `SessionMiddleware` signed cookie | `SessionMiddleware(secret_key, session_cookie, max_age, same_site, https_only)` signature confirmed; emitted `Max-Age=2592000; httponly; samesite=lax` [VERIFIED: local run] |
| uvicorn | 0.54.0 | ASGI server | Standard FastAPI server [VERIFIED: PyPI] |
| httpx | 0.28.1 | Async qBittorrent client | Cookie jar handles the `QBT_SID_<port>` cookie; `ASGITransport` for tests [VERIFIED: local run] |
| argon2-cffi | 25.1.0 | Verify `APP_PASS_HASH` (argon2id) | `PasswordHasher().hash/verify` worked; hash prefix `$argon2id$v=19$m=65536,t=3,p=4$` [VERIFIED: local run] |
| pydantic-settings | 2.16.1 | Env config + validation | Requires Python >=3.11 (host has 3.12.3) [VERIFIED: PyPI] |
| itsdangerous | 2.2.0 | Required by `SessionMiddleware` for signing | Pulled in with the session middleware [VERIFIED: venv import] |
| caddy (image `caddy:2-alpine`) | 2.11.7 | Static SPA + reverse proxy | D-03; Caddyfile validated and exercised with the 2.11.7 binary [VERIFIED: local run] |
| lscr.io/linuxserver/qbittorrent | pin `5.2.4` | qBittorrent + python3 for search | Tag `5.2.4` exists; image bundles `python3` and the same static binary tested [VERIFIED: Docker Hub tag API, Dockerfile] |
| preact | 11.0.1 | Frontend | D-02; build+test smoke OK [VERIFIED: npm + local build] |
| vite | 8.3.5 | Build / dev server | Needs Node ^20.19 or >=22.12 (host Node v24.15.0) [VERIFIED: npm engines] |
| @preact/preset-vite | 2.10.6 | Preact plugin for Vite | Peer range includes Vite 8 [VERIFIED: npm peerDependencies] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| python-multipart | 0.0.32 | Form parsing if any form endpoint is used | Only if login uses form posts; recommended login is JSON, so optional |
| pytest | 9.1.1 | Backend tests | All backend tests |
| pytest-asyncio | 1.4.0 | Async tests | `@pytest.mark.asyncio` with `httpx.ASGITransport` (verified) |
| respx | 0.23.1 | Assert exact qBittorrent wire format | `test_qbit_client.py` only; use a stateful `FakeQbit` for pipeline tests |
| pyyaml | 6.0.3 | Parse compose in infra invariant tests | `infra/tests/` |
| ruff | 0.17.1 | Lint/format | Optional |
| vitest | 5.0.5 | Frontend tests | Peer vite `^6.4 || ^7 || ^8` OK [VERIFIED] |
| @testing-library/preact | 3.2.4 | Component tests | Peer `preact >=10` accepts 11 [VERIFIED] |
| jsdom | 30.1.3 | Vitest DOM env | Verified working with vitest 5.0.5 |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Starlette `SessionMiddleware` | Hand-signed cookie with `itsdangerous` directly | Same primitive; middleware is less code. Use middleware. |
| Polling for live results | SSE | SSE needs streaming through Caddy (works: Caddy flushes `text/event-stream`) but adds reconnect/old-browser concerns. Polling every ~700 ms meets D-06 simply. |
| `argon2-cffi` | `bcrypt` | Both satisfy D-17. argon2id chosen; both hashes contain `$` (see Pitfall 6). |
| Preact 11 | Preact 10.x | 11.0.1 passed a build+test smoke; fall back to 10.x only if a runtime issue appears on the TV (Phase 5). |
| Plain JS/JSX | TypeScript 7.0.2 | TS 7 is very new; Phase 1 UI is small. Recommend JS + JSDoc, avoid toolchain risk. |

**Installation:**
```bash
# backend (uv 0.6.14 is on the host); commit pyproject.toml + uv.lock
uv add fastapi uvicorn httpx argon2-cffi itsdangerous pydantic-settings
uv add --dev pytest pytest-asyncio respx pyyaml ruff
# frontend
npm i preact && npm i -D vite @preact/preset-vite vitest @testing-library/preact jsdom
```

**Version verification:** all versions above were read from PyPI/npm on 2026-10-21 and the whole backend and frontend sets were installed and exercised in throwaway directories (session login test passed; `vite build` + `vitest run` passed).

## Package Legitimacy Audit

Seam command: `gsd-tools query package-legitimacy check`. The seam returned **SUS for almost every package**, driven only by the heuristics `unknown-downloads` (PyPI exposes no download counts), `too-new` (a release in the last days) and `no-repository` (argon2-cffi's PyPI metadata links to a CHANGELOG URL). I cross-checked first-release date and repository for each; all are long-established projects. Protocol still requires a human gate, so **one consolidated checkpoint** is recommended (review the committed `uv.lock` / `package-lock.json` once, before first install) rather than a checkpoint per package.

| Package | Registry | Age (first release) | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|---------------------|-----------|-------------|---------|-------------|
| fastapi | PyPI | 2018-12 | n/a (seam: unknown) | github.com/fastapi/fastapi | SUS (too-new, unknown-downloads) | Flagged: consolidated checkpoint |
| uvicorn | PyPI | 2017-06 | n/a | PyPI metadata links only a GitHub sponsors page; upstream repo not confirmed this session | SUS (too-new, unknown-downloads) | Flagged: consolidated checkpoint |
| httpx | PyPI | 2019-07 | n/a | github.com/encode/httpx | SUS (unknown-downloads) | Flagged: consolidated checkpoint |
| argon2-cffi | PyPI | 2015-12 | n/a | github.com/hynek/argon2-cffi | SUS (unknown-downloads, no-repository) | Flagged: consolidated checkpoint |
| itsdangerous | PyPI | 2011-06 | n/a | github.com/pallets/itsdangerous | SUS (unknown-downloads) | Flagged: consolidated checkpoint |
| pydantic-settings | PyPI | 2019-08 | n/a | github.com/pydantic/pydantic-settings | SUS (too-new, unknown-downloads) | Flagged: consolidated checkpoint |
| pytest | PyPI | 2010-11 | n/a | github.com/pytest-dev/pytest | SUS (unknown-downloads) | Flagged: consolidated checkpoint |
| pytest-asyncio | PyPI | 2015-04 | n/a | github.com/pytest-dev/pytest-asyncio | SUS (unknown-downloads) | Flagged: consolidated checkpoint |
| respx | PyPI | 2019-11 | n/a | github.com/lundberg/respx | SUS (unknown-downloads) | Flagged: consolidated checkpoint |
| ruff | PyPI | 2022-08 | n/a | github.com/astral-sh/ruff | SUS (too-new, unknown-downloads) | Flagged: consolidated checkpoint |
| python-multipart | PyPI | 2013-03 | n/a | github.com/Kludex/python-multipart | SUS (unknown-downloads) | Flagged (optional dependency) |
| pyyaml | PyPI | 2011-07 | n/a | github.com/yaml/pyyaml | SUS (unknown-downloads) | Flagged: consolidated checkpoint |
| preact | npm | 2015-09 | n/a | github.com/preactjs/preact | SUS (too-new) | Flagged: consolidated checkpoint |
| vite | npm | 2020-04 | n/a | github.com/vitejs/vite | SUS (too-new) | Flagged: consolidated checkpoint |
| vitest | npm | 2021-12 | n/a | github.com/vitest-dev/vitest | SUS (too-new) | Flagged: consolidated checkpoint |
| jsdom | npm | 2011-11 | n/a | github.com/jsdom/jsdom | SUS (too-new) | Flagged: consolidated checkpoint |
| @preact/preset-vite | npm | 2021-03 | n/a | github.com/preactjs/preset-vite | OK | Approved |
| @testing-library/preact | npm | 2019-09 | n/a | github.com/testing-library/preact-testing-library | OK | Approved |

**Packages removed due to SLOP verdict:** none.
**Packages flagged SUS:** all rows marked SUS above. `npm view <pkg> scripts.postinstall` returned empty for every npm package (no postinstall scripts). Planner: insert **one** `checkpoint:human-verify` before the first `uv sync` / `npm ci` that reviews the lockfiles; do not add 16 separate checkpoints.

**Search plugins are also third-party code** (Python executed inside the qBittorrent container, with network). Official repo `qbittorrent/search-plugins`, engines present on 2026-10-21: `eztv, jackett, limetorrents, piratebay, solidtorrents, torlock, torrentproject, torrentscsv` [VERIFIED: GitHub contents API + `versions.txt`]. Pin installs to a commit SHA, not `master` (latest commit touching `nova3/engines` today: `2beb5c67b0edbf2387a031a02d1881fab4bec3c3`, [VERIFIED: GitHub commits API]; re-resolve when writing the plan).

## Architecture Patterns

### System Architecture Diagram

```
 Phone browser (LAN)                    Windows/WSL2 host or Ubuntu host
 ───────────────────                    ────────────────────────────────────────────────────────
                         http://<host>/ (host port 80, only published service)
 Preact SPA  ───────────────────────────────►  [web: Caddy 2]  network: edge
   │  GET /            static dist + SPA fallback (try_files {path} /index.html)
   │  POST/GET /api/*  ───────────────────────► reverse_proxy backend:8000
   │  /tv/*  (reserved, Phase 5)    /jellyfin/* (reserved, Phase 3)
   │                                                  │
   │                                      [backend: FastAPI]  networks: edge + qbit
   │                                        ├─ /api/login ── argon2 verify ─► signed session cookie (30 d)
   │                                        ├─ require_user dependency on every router (except login, health)
   │                                        ├─ SearchService ── result cache {result_id → (engine, fileUrl, meta)}
   │                                        ├─ DownloadPipeline ── JobRegistry (asyncio tasks, tag-driven)
   │                                        └─ Bootstrap at startup: prefs, categories, plugins
   │                                                  │  http://qbittorrent:8088  (QbitClient, cookie jar, relogin on 403)
   │                                                  ▼
   │                                      [qbittorrent: linuxserver 5.2.4]  network: qbit ONLY
   │                                        ├─ search plugins (python3) ─► Internet (egress via bridge NAT)
   │                                        ├─ torrents/add  stopCondition=MetadataReceived autoTMM=true category=Film|SerieTV tags=fx,fx-pending
   │                                        ├─ files / filePrio / start
   │                                        ├─ incomplete ─► /incomplete/<Category>
   │                                        └─ complete   ─► /media/Film | /media/SerieTV
   │                                                  │ bind mounts
   │                                      host: ${MEDIA_ROOT}/Film, ${MEDIA_ROOT}/SerieTV, ${INCOMPLETE_DIR}
   │                                      (owned by PUID:PGID; Jellyfin mounts MEDIA_ROOT read-only in Phase 3/4)

 Download decision flow (per tap):
   POST /api/download{result_id,type}
     → resolve URL from server cache (410 if expired) → add (tag job) → [poll files ≤15 s in request]
        ├─ files appear: allowlist check
        │     ├─ no allowed (non-sample) video → delete torrent (deleteFiles=true) → "rejected"
        │     └─ else filePrio 0 for non-allowed + samples → verify → torrents/start → "started"
        └─ no files within 15 s → respond "preparing"; task continues to METADATA_TIMEOUT (300 s)
              └─ timeout → delete torrent → "unavailable"
```

### Recommended Project Structure
```
backend/
├── app/
│   ├── main.py              # FastAPI app, lifespan (bootstrap, job registry), middleware
│   ├── config.py            # pydantic-settings Settings, placeholder rejection
│   ├── auth.py              # login route, require_user dependency, login throttle
│   ├── qbit/client.py       # QbitClient (httpx, login/relogin, typed methods)
│   ├── qbit/bootstrap.py    # prefs, categories, plugin install, version gate
│   ├── search/service.py    # start/poll/stop, result cache, snapshot
│   ├── search/filters.py    # min seeders, min size, suspicious names, quality badge, dedupe
│   ├── download/pipeline.py # add → metadata → allowlist → prio → start
│   ├── download/jobs.py     # JobRegistry, reconcile-on-startup
│   ├── download/allowlist.py# extension sets, sample heuristic (pure functions)
│   ├── routers/{auth,search,download,health}.py
│   └── tools/hash_password.py   # `python -m app.tools.hash_password`
├── tests/ (unit + FakeQbit + respx wire tests; integration/ gated)
├── pyproject.toml / uv.lock / Dockerfile
frontend/                    # Preact + Vite (JS/JSX), vitest tests next to components
web/                         # Dockerfile (node build → caddy:2-alpine), Caddyfile
qbittorrent/custom-cont-init.d/10-credentials.sh   # executable, mounted read-only
infra/tests/                 # compose + repo-hygiene invariant tests (PyYAML, no Docker needed)
docs/ports-and-media.md      # the ONE port map + media-folder contract (INFRA-02, MEDIA-01)
docs/setup.md                # first run, hash helper, WSL2 forwarding, plugin trust list
docker-compose.yml  .env.example  .gitignore
```

### Pattern 1: Session login (AUTH-01, D-15..D-18) [VERIFIED: local run]
**What:** One shared account; argon2 verify; Starlette signed session cookie; every router protected by a dependency.
**When to use:** All routes except `POST /api/login` and the minimal health route.
**Example:**
```python
# Source: verified in a local venv with fastapi 0.159.1 / starlette 1.9.0 / argon2-cffi 25.1.0
from fastapi import Depends, FastAPI, HTTPException, Request
from starlette.middleware.sessions import SessionMiddleware
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

ph = PasswordHasher()
app = FastAPI()
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key.get_secret_value(),
    session_cookie="flatflix_session",
    max_age=30 * 24 * 3600,      # D-16
    same_site="lax",
    https_only=False,            # plain-HTTP LAN; see Security Domain
)
def require_user(request: Request):
    if request.session.get("u") != "family":
        raise HTTPException(401, "not logged in")
# Emitted header (verified): flatflix_session=...; path=/; Max-Age=2592000; httponly; samesite=lax
```
Protect by default: `APIRouter(dependencies=[Depends(require_user)])` for search/download routers; login and health routers have none. Add a test that enumerates `app.routes` and fails if any route other than the allow-list lacks the dependency.

### Pattern 2: Live search with a server-side result cache (SRCH-01..03, D-06..D-09) [VERIFIED endpoints, local run]
**What:** `POST /api/search {q,type}` starts a qB search and returns `search_id`; the frontend polls `GET /api/search/{id}` (~700 ms) which returns a **full filtered, deduped, sorted snapshot** (cap ~100 rows) plus `done`/`timed_out` and a `version` counter. The browser receives `result_id` only (`sha1(engineName + fileUrl)[:16]`, stable across polls so row state survives re-sorting); the raw `fileUrl` stays in a server-side cache (TTL ~15 min).
**qBittorrent calls (all verified on 5.2.4):**
- `POST /api/v2/search/start` form `pattern`, `category` (`movies`|`tv`), `plugins=enabled` → `{"id": 1962241670}`. Required params are `pattern`, `category`, `plugins` (source: `searchcontroller.cpp:102`). `plugins` accepts `all`, `enabled`, or `a|b`.
- `GET /api/v2/search/status?id=` → `[{"id":…,"status":"Running"|"Stopped","total":N}]`.
- `GET /api/v2/search/results?id=&limit=0&offset=0` → `{results:[…],status,total}`; `404` after `search/delete`.
- `POST /api/v2/search/stop`, `POST /api/v2/search/delete` (`id`). qB allows at most 5 concurrent searches (409 beyond that): on a new search, stop+delete the previous one and any expired ones.
**Measured:** first results at **2.14 s** (movies) and **1.66 s** (tv); search finished at 2.6 s / 5.2 s; 61 and 160 results; 2 of 7 official plugins returned data in this environment (the others returned nothing).
**Real result row (verbatim, 5.2.4):**
`{"descrLink": "https://www.limetorrents.lol/Big-Buck-Bunny-trailer-torrent-157833.html", "engineName": "limetorrents", "fileName": "Big Buck Bunny trailer", "fileSize": 4362076, "fileUrl": "https://www.limetorrents.lol/Big-Buck-Bunny-trailer-torrent-157833.html", "nbLeechers": 0, "nbSeeders": 7, "pubDate": 1761083074, "siteUrl": "https://www.limetorrents.lol"}`
**Plugin list row (verbatim):** `{"enabled": true, "fullName": "The Pirate Bay", "name": "piratebay", "supportedCategories": [{"id": "all", "name": "All categories"}, {"id": "games", "name": "Games"}, {"id": "movies", "name": "Movies"}, {"id": "music", "name": "Music"}, {"id": "software", "name": "Software"}], "url": "https://thepiratebay.org", "version": "3.10"}`
**Normalization rules:** plugin spec says unknown values are `-1` (`size`, `seeds`, `leech`) [CITED: github.com/qbittorrent/search-plugins wiki "How to write a search plugin", lines 159-168]. Treat `nbSeeders < 0` as unknown (hidden by `MIN_SEEDERS`); treat `fileSize < 0` as unknown and hide it from film/serie size filters (fail-safe); dedupe by btih infohash when `fileUrl` is a magnet (`xt=urn:btih:`), otherwise by `(engineName, fileUrl)`, keeping the highest seeders.
**Timeout:** `SEARCH_TIMEOUT` (suggest 20 s): on expiry call `search/stop`; zero results → `timed_out: true` and the frontend shows a plain Italian message; some results → show them with the indicator off.
**Query hygiene:** trim, length 2..100, strip control characters.

### Pattern 3: Tag-driven download pipeline (DOWN-01..03, FILT-02, D-10..D-14) [VERIFIED sequence, local run]
**What:** `POST /api/download {result_id, type}`. The backend resolves URL + engine from its cache (410 "Ricerca scaduta, cerca di nuovo" if missing), maps `type` → category with a fixed dict, and runs a job as an `asyncio.Task` held by a registry (strong references; not `BackgroundTasks`, which dies with the request lifecycle). The endpoint awaits `asyncio.wait_for(asyncio.shield(task), 15)`; on timeout it answers `{"status":"preparing","job_id":…}` and the task continues to `METADATA_TIMEOUT`.
**Steps:**
1. If `fileUrl` is a magnet, parse btih (hex-40 or base32-32) and check `torrents/info?hashes=` → if present, answer "Già presente" (qB itself returns 409 for duplicates, verified).
2. `POST /api/v2/torrents/add` with: `urls=<single line>`, `category=<Film|SerieTV>`, `autoTMM=true`, `stopCondition=MetadataReceived`, `tags=fx,fx-pending[,fx-job-<8hex>]`, and `downloader=<engineName>` **only when `fileUrl` is not a magnet** (verified: without `downloader` an HTTP page URL silently never appears; with it the response is `202 {"added_torrent_ids": [], "failure_count": 0, "pending_count": 1, "success_count": 0}` and the torrent appears under the tag a few seconds later). For magnets the response is `200 {"added_torrent_ids": ["<hash>"], …}`.
3. Poll `GET /api/v2/torrents/files?hash=` every 1 s: **an empty array means "no metadata yet"** (not an error; source `torrentscontroller.cpp:1036-1037`). For the downloader flow find the hash through `torrents/info?tag=fx-job-…`.
4. On files: run the allowlist (Pattern 4). Reject → `torrents/delete` with `deleteFiles=true`. Accept → `torrents/filePrio` (`hash`, `id=1|2|3`, `priority=0`) for every non-allowed file and every sample, **re-read `files` and assert** all those indexes are 0, then `torrents/start`, then remove tag `fx-pending`.
5. Timeout → delete torrent (`deleteFiles=true`), job state `unavailable`.
**Reconcile at startup:** list `torrents/info?tag=fx-pending`; resume or time out each by `added_on`. Tags persist in qB, so a backend restart cannot strand stopped torrents. Delete per-job tags afterwards (`torrents/deleteTags`).
**Response DTO whitelist:** `{status, message, job_id}`; never forward qB fields (`save_path`, `content_path`, `category`, hashes of internals).

### Pattern 4: Allowlist, exclusion list, samples (FILT-01, FILT-02, D-13, D-14)
**Exclusion list (global, set at bootstrap)** — `POST /api/v2/app/setPreferences` with `json={"excluded_file_names":"*.exe\n*.bat\n…","excluded_file_names_enabled":true}`. Verified: newline-separated; stored as `Session\ExcludedFileNames=*.jpg, *.exe, *.bat`; matching is **case-insensitive and applies to nested paths** (`Movie.mkv.exe` and `SETUP.EXE` both got priority 0; non-listed `.lnk`/`.msi`/`.zip` stayed at 1); a matched file is set to priority 0 automatically at add (`poster.jpg` → 0). It only covers patterns you list and only torrents added afterwards, so it is defence in depth; **the per-file allowlist is the real control.**
Values from REQUIREMENTS.md (Read this session):
- FILT-01 (line 46): "e.g. `*.exe`, `*.bat`, `*.cmd`, `*.ps1`, `*.scr`, `*.lnk`, `*.msi`, `*.zip`, `*.rar`, `*.7z`, `*.iso`"
- FILT-02 (line 47): "(video: `.mkv`, `.mp4`, `.avi`, `.m4v`; subtitles: `.srt`, `.ass`, `.ssa`, `.sub`, `.idx`)"
**Allowlist function:** lower-case final extension in the video or subtitle set → keep; everything else (incl. `.txt`, `.nfo`, no extension) → priority 0. Compare the **last** extension only (`movie.mkv.exe` → `.exe` → blocked).
**Sample heuristic (D-14, discretion):** priority 0 if the basename or any directory matches `(^|[\W_])sample([\W_]|$)` (case-insensitive) OR size < 10 % of the largest allowed video in the torrent. If every allowed video is a sample, treat the torrent as "no video" (reject with D-13 text).
**Series size threshold (discretion):** `MIN_SERIE_SIZE_MB` default 100 (a single episode is usually larger; season packs far larger), separate from film `MIN_FILM_SIZE_MB` default 500.
**Suspicious names (discretion):** one module-level tuple, overridable by env `SUSPICIOUS_TERMS`; start with `.exe`, `.scr`, `.bat`, `.msi`, `password`, `codec`, `keygen`, `crack`, `activator`, `installer`, `setup.exe`. Quality badge regex: `2160p|4k|uhd` → "4K"; `1080p`; `720p`; `480p|576p|dvdrip` → "SD"; else none (badge only, D-08).

### Pattern 5: Compose topology, port map, media contract (SEC-02, INFRA-01/02, MEDIA-01) [structure not runnable here; invariants testable without Docker]
Two networks: `edge` (web + backend) and `qbit` (backend + qbittorrent). `qbit` must **not** be `internal: true` because the plugins and peers need Internet egress; isolation comes from membership plus not publishing ports.

Proposed port map (Claude's discretion; the one document is `docs/ports-and-media.md`):

| Service | Container port | Host publish | Note |
|---------|----------------|--------------|------|
| Caddy (`web`) | 80 | `${WEB_PORT:-80}:80` (D-04) | portal at `/`, `/api/*` → backend, `/tv/*` reserved (Phase 5), `/jellyfin/*` reserved (Phase 3) |
| Backend (FastAPI) | 8000 | none | reachable only on `edge` |
| qBittorrent WebUI | 8088 | none; optional admin `127.0.0.1:8088:8088` | differs from 80, 8000, 8080, 8096; keep container and host numbers equal (linuxserver README warns about "issues with CSRF and port mapping") |
| qBittorrent peers | 6881 tcp+udp | `6881:6881` and `6881:6881/udp`, optional | peer traffic only |
| Jellyfin | 8096 | reserved for Phase 3 | reached via Caddy |

Media contract (defaults relative, so no personal paths land in the public repo): host `${MEDIA_ROOT:-./data/media}/Film` → container `/media/Film`; `${MEDIA_ROOT}/SerieTV` → `/media/SerieTV`; `${INCOMPLETE_DIR:-./data/incomplete}` → `/incomplete`, **outside** `MEDIA_ROOT` so Jellyfin (read-only mount of `MEDIA_ROOT`) never sees partials; owner `PUID:PGID` (default 1000:1000) documented once and reused by Jellyfin later. Moving incomplete → final crosses two bind mounts, so qB copies+deletes instead of renaming; acceptable (partial files can never appear in media folders).
Required compose rules: `ports` for qbittorrent absent or loopback-only; `QBITTORRENT_URL=http://qbittorrent:8088`; `${VAR:?}` for secrets; `depends_on: condition: service_healthy`; **qB healthcheck must not use the API** (unauthenticated `app/version` answers 403): use a TCP check such as `nc -z localhost 8088` (the image's own service check uses `nc -z`).
Skeleton of the qB service (image tag, env names and mounts verified from the linuxserver README and Dockerfile; the file as a whole could not be run without Docker):
```yaml
services:
  qbittorrent:
    image: lscr.io/linuxserver/qbittorrent:5.2.4
    environment:
      PUID: ${PUID:-1000}
      PGID: ${PGID:-1000}
      TZ: ${TZ:-Etc/UTC}
      WEBUI_PORT: "8088"
      TORRENTING_PORT: "6881"
      QBITTORRENT_USER: ${QBITTORRENT_USER:?set in .env}
      QBITTORRENT_PASS: ${QBITTORRENT_PASS:?set in .env}
    volumes:
      - ./qbittorrent/config:/config
      - ./qbittorrent/custom-cont-init.d:/custom-cont-init.d:ro
      - ${MEDIA_ROOT:-./data/media}/Film:/media/Film
      - ${MEDIA_ROOT:-./data/media}/SerieTV:/media/SerieTV
      - ${INCOMPLETE_DIR:-./data/incomplete}:/incomplete
    networks: [qbit]
    healthcheck:
      test: ["CMD-SHELL", "nc -z localhost 8088"]
```

### Pattern 6: Configuration and secrets (SEC-04, D-17)
pydantic-settings `Settings` with `SecretStr` for `QBITTORRENT_PASS`, `APP_PASS_HASH`, `SECRET_KEY`. Validate: `SECRET_KEY` length ≥ 32; refuse to start on placeholder values (any value starting `change-me`); `APP_PASS_HASH` must parse as argon2 (fail fast with a clear message, see Pitfall 6). Variables (names are the design-doc ones plus the discussed additions): `QBITTORRENT_URL`, `QBITTORRENT_USER`, `QBITTORRENT_PASS`, `CATEGORY_FILM=Film`, `CATEGORY_TV=SerieTV`, `APP_USER`, `APP_PASS_HASH`, `SECRET_KEY`, `MIN_SEEDERS=5`, `MIN_FILM_SIZE_MB=500`, `MIN_SERIE_SIZE_MB=100`, `METADATA_TIMEOUT=300`, `SEARCH_TIMEOUT=20`, `DOWNLOAD_WAIT_SECONDS=15`, `LOGIN_MAX_ATTEMPTS=5`, `LOGIN_WINDOW_MINUTES=15`, plus compose-level `WEB_PORT`, `MEDIA_ROOT`, `INCOMPLETE_DIR`, `PUID`, `PGID`, `TZ`. `.gitignore` must cover `.env`, `qbittorrent/config/` (holds the PBKDF2 hash), `data/`, `node_modules/`, `dist/`, `.venv/`.

### Pattern 7: qBittorrent client and bootstrap (SEC-01, FILT-01, DOWN-03)
```python
# Source: behaviours verified against qbittorrent-nox 5.2.4 (WebAPI 2.15.1)
class QbitClient:
    async def _login(self):
        r = await self._c.post("/api/v2/auth/login",
                               data={"username": self._user, "password": self._pw})
        if r.status_code in (200, 204) and r.text.strip() != "Fails.":
            return                                   # 204 on 5.2.4; cookie lands in the httpx jar
        if r.status_code == 403:
            raise QbitBanned()                       # 5 fails -> IP banned 3600 s (prefs verified)
        raise QbitAuthError()                        # 401 on bad credentials (verified)

    async def _request(self, method, path, **kw):
        r = await self._c.request(method, path, **kw)
        if r.status_code == 403:                     # unauthenticated/expired session (verified 403)
            await self._login()                      # serialise with an asyncio.Lock; never loop
            r = await self._c.request(method, path, **kw)
        return r
```
Bootstrap order (idempotent, retry with backoff until qB answers, **no tight login retries**): login → check `app/webapiVersion` ≥ tested version → `app/setPreferences` (`excluded_file_names`, `excluded_file_names_enabled: true`, `auto_tmm_enabled: true`, `category_changed_tmm_enabled: true`, `temp_path_enabled: true`, `temp_path: "/incomplete"`) → `torrents/categories`; for each wanted category `createCategory` if absent, `editCategory` if `savePath` differs (create on an existing name returns 409 "Unable to create category", verified) → install missing search plugins (see Open Question 1).
`setPreferences` body rule [CITED: qBittorrent wiki]: the form field `json` holds a JSON object; strings quoted, ints/bools unquoted.

### Pattern 8: Caddyfile (D-03, D-05) [VERIFIED: caddy 2.11.7 `validate` + live curl]
```caddyfile
{
	admin off
	auto_https off
}
:80 {
	encode zstd gzip
	handle /api/* {
		reverse_proxy backend:8000
	}
	handle_path /tv/* {          # reserved; Phase 5 replaces respond with root + try_files + file_server
		respond "TV reserved" 200
	}
	handle {                      # portal SPA at /, history fallback
		root * /srv/portal
		try_files {path} /index.html
		file_server
	}
}
```
Verified results: `/`, `/search`, `/login` → index.html; `/app.css` → the file; `/api/*` reaches the backend; `/tv/*` hits the reserved block; a client-supplied `X-Forwarded-For: 6.6.6.6` was **ignored** and the backend saw Caddy's peer address (`127.0.0.1` in the test). Unknown static paths (e.g. `/missing.js`) return `index.html` with 200 (normal SPA behaviour). `handle` blocks are mutually exclusive and a matcher-less `handle` is the fallback [CITED: caddyserver.com/docs/caddyfile/directives/handle]. Vite `base: '/'` for the portal; the TV app later builds with `base: '/tv/'`.

### Anti-Patterns to Avoid
- **Adding magnets with `stopped=true` and waiting for files:** never completes (Pitfall 1).
- **Sending the browser-supplied URL/magnet to qB:** SSRF and category/URL injection; use the server-side `result_id` cache.
- **Passing any user-influenced string as `category`:** qB creates it (Pitfall 4).
- **Relying on the category `savePath` without `autoTMM=true`.**
- **Hard-coding the cookie name `SID`:** 5.2.4 uses `QBT_SID_<port>`; use the httpx jar.
- **`BackgroundTasks` for the metadata wait:** tied to the request lifecycle; use a registry of `asyncio.Task`s.
- **Calling `torrents/delete` without `deleteFiles`:** returns 400 (`Missing required parameters: deleteFiles`, verified).
- **Trusting the qBittorrent wiki page "WebUI-API-(qBittorrent-5.0)" for names:** it still documents `paused`/`pausedDL`; the code and 5.2.4 use `stopped`/`stoppedDL` (Pitfall 10).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Signed session cookie | Custom HMAC cookie | `starlette.middleware.sessions.SessionMiddleware` | Verified 30-day HttpOnly SameSite=Lax cookie in 6 lines |
| Password hashing | Custom KDF or sha256 | `argon2-cffi` `PasswordHasher` | Parameters, salt, constant-time verify handled |
| qBittorrent password hash for the container | Guess a format | `hashlib.pbkdf2_hmac("sha512", pw, salt16, 100000, 64)` written as `@ByteArray(b64salt:b64key)` | Format verified: qB accepted it after restart and rejected the old temp password |
| Static serving + SPA fallback + reverse proxy | Node/Python static server in the backend | Caddy (D-03) | Verified routing; FastAPI stays API-only |
| Mock HTTP for qB wire tests | Hand-built transports | `respx` | Exact request assertions (form fields) |
| Bencoding a test `.torrent` | A bencode library | ~10-line encoder in a test helper | Only needed by the optional integration test |
| Torrent metadata/file list | Parsing magnets/trackers yourself | qB `torrents/files` after `stopCondition=MetadataReceived` | qB does the DHT/tracker exchange |
| Login throttling (Phase 1) | Anything elaborate | A ~20-line in-memory sliding window keyed by client IP | Phase 2 owns SEC-05; do not pull `slowapi` in yet |

**Key insight:** every qB behaviour above was surprising relative to the design doc; the safest strategy is the thin typed client plus a `FakeQbit` that reproduces these verified behaviours, and an opt-in integration test that replays the verified calls against a real qB on every version bump.

## Runtime State Inventory

Not a rename/refactor/migration phase (greenfield; the repo contains only planning docs). Omitted per the template rule. One related note: `qbittorrent/config/` persists `qBittorrent.conf` (credentials hash, prefs) across restarts and must be gitignored.

## Common Pitfalls

### Pitfall 1: A stopped magnet never fetches metadata (FILT-02 deadlock)
**What goes wrong:** Following the requirement text ("adds every torrent stopped, waits for its metadata") hangs forever for magnets.
**Why:** On 5.2.4, `torrents/add` with `stopped=true` for a magnet left the torrent in `stoppedDL` for 62 s with `files=[]` throughout [VERIFIED: local run]. Source accepts the parameter: `const std::optional<bool> addStopped = parseBool(params()[u"stopped"_s]);` (`torrentscontroller.cpp:1148`).
**How to avoid:** Add **started** with `stopCondition=MetadataReceived` (source: `const QString stopConditionParam = params()[u"stopCondition"_s];`, line 1164). Verified: files appeared 2 s after add, state `stoppedDL`, `downloaded=0`. The torrent only exchanges metadata, so no payload is requested before filtering. Residual race (a few pieces before the stop fires) was not observed (A8).
**Warning signs:** jobs stuck in "waiting metadata" until `METADATA_TIMEOUT`; torrents sitting in `stoppedDL` with an empty file list.
**Planner action:** keep REQUIREMENTS.md FILT-02 and CLAUDE.md wording but add a note that "stopped" means "stops itself after metadata"; the intent (nothing downloaded before the file list is checked) is preserved.

### Pitfall 2: Category path ignored without Automatic Torrent Management
**What goes wrong:** Torrent with `category=Film` saved to the global default path.
**Why:** With `autoTMM` unset, `save_path` was the global default (`…/qBittorrent/downloads`) although category `Film` had its own `savePath` [VERIFIED: local run]. With `autoTMM=true`, `save_path` became the category path and `download_path` became `<temp_path>/Film`.
**How to avoid:** send `autoTMM=true` on every add and set `auto_tmm_enabled` / `category_changed_tmm_enabled` at bootstrap. Docs: qbit-wrapper.md §6 omits this.
**Warning signs:** completed files outside `/media/Film`.

### Pitfall 3: Creating a category that already exists returns 409
**What goes wrong:** Bootstrap crashes on second start.
**Why:** `createCategory` for an existing name → `409 "Unable to create category"` [VERIFIED]. Note also `Incorrect category name` 409 for invalid names (source `torrentscontroller.cpp:1948-1985`).
**How to avoid:** list (`torrents/categories`), create if absent, `editCategory` if the stored `savePath` differs (`editCategory` returned 200).

### Pitfall 4: qBittorrent auto-creates any category passed to `torrents/add`
**What goes wrong:** A tampered request would create categories (and thus paths).
**Why:** Adding with `category=NoSuch/../x` returned 200 and the categories list afterwards contained `NoSuch`, `NoSuch/..`, `NoSuch/../x` [VERIFIED].
**How to avoid:** category comes only from the fixed server map; never from request data. SEC-03 test: any `type` other than `film`/`serie` → 422 and **no** qB call is made.

### Pitfall 5: Non-magnet search results need the plugin's downloader
**What goes wrong:** Download taps on limetorrents rows "succeed" but nothing appears in qB.
**Why:** `fileUrl` for limetorrents is an HTML page URL; plain `torrents/add` returned 202 `pending_count: 1` and no torrent ever appeared (qB log: "Connection error: Forbidden"). With `downloader=limetorrents` the torrent appeared (`stoppedDL`, name "Big Buck Bunny trailer") [VERIFIED]. The response carries **no hash**.
**How to avoid:** pass `downloader=<engineName>` for any non-magnet `fileUrl`; locate the torrent by a per-job tag; apply the same metadata timeout. `search/downloadTorrent` exists in current source but adds without category/stop-condition: do not use it.

### Pitfall 6: `$` in argon2/bcrypt hashes is eaten by Compose interpolation
**What goes wrong:** `APP_PASS_HASH=$argon2id$v=19$…` in `.env` is interpolated (`$argon2id` → empty) and login always fails.
**Why:** Compose substitutes `$VAR` in unquoted and double-quoted `.env` values; "Single-quoted (`'`) values are used literally" [CITED: docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/]. Not tested here (no Docker).
**How to avoid:** the hash helper prints the full line `APP_PASS_HASH='$argon2id$…'` (single-quoted) for pasting; backend fails fast at startup with an explicit message if the value does not parse as argon2; add a `docker compose config` checkpoint to the manual list.

### Pitfall 7: qBittorrent bans the backend after 5 failed logins
**What goes wrong:** A wrong `QBITTORRENT_PASS` plus a retry loop locks the backend out for an hour (`403`).
**Why:** `web_ui_max_auth_fail_count = 5`, `web_ui_ban_duration = 3600` [VERIFIED: preferences dump]; wrong credentials → `401 Unauthorized`.
**How to avoid:** bootstrap logs one clear error and backs off exponentially on 401; on 403 at login raise `QbitBanned` and stop retrying; the provisioning script (Pitfall 11) must set the password the backend uses.

### Pitfall 8: Docker creates missing bind sources as root
**What goes wrong:** qB (user `abc`, `PUID:PGID`) cannot write to `/media/Film`; downloads error.
**Why:** The linuxserver init only `lsiown`s `/config` (and `/downloads` if mounted) [VERIFIED: init-qbittorrent-config script read this session]; our mounts are not chowned.
**How to avoid:** ship `scripts/init-host-dirs.sh` (`mkdir -p`, `chown PUID:PGID`) and make it step 1 in `docs/setup.md`; the compose file should not auto-create them silently.

### Pitfall 9: Published Docker ports can bypass the host firewall
**What goes wrong:** On the Ubuntu box, a `ports: "8088:8088"` is reachable from the LAN even with `ufw` deny rules.
**Why:** Docker inserts its own iptables rules [ASSUMED, well-known]. 
**How to avoid:** never publish the WebUI except as `127.0.0.1:8088:8088`; the compose invariant test enforces it.

### Pitfall 10: The official API wiki lags the code
**What goes wrong:** Implementing `paused`/`pausedDL`/`pause` from the wiki page "WebUI-API-(qBittorrent-5.0)".
**Why:** The page documents `paused` for add and `pausedDL`/`pausedUP` states and says nothing of `stopCondition`, while source and 5.2.4 use `stopped`/`stoppedDL`/`torrents/stop|start` ([VERIFIED: qBittorrent master `src/webui/webapplication.h:61`] `inline const Utils::Version<3, 2> API_VERSION {2, 17, 0};`; the tested 5.2.4 server reported `2.15.1`).
**How to avoid:** pin the image to the tested tag; gate on `app/webapiVersion >= 2.15.1`; keep the integration test as the upgrade guard.

### Pitfall 11: The linuxserver image has no password env var and no plugins
**What goes wrong:** Backend cannot log in on first run; search returns nothing.
**Why:** "a temporary password for the `admin` user will be printed to the container log on startup" and changes each start [CITED: linuxserver README]; a fresh profile returned `search/plugins` = `[]` [VERIFIED].
**How to avoid:** a `/custom-cont-init.d` script (runs "after built-in and any applied mod init steps but before any services start" [CITED: docs.linuxserver.io/general/container-customization]; must be executable and root-owned) that writes `WebUI\Username` and `WebUI\Password_PBKDF2` into `/config/qBittorrent/qBittorrent.conf` from env, then `chown abc:abc` the file (a root-owned conf would break qB's own saves). Format verified: after restart `portal / <pw>` logged in (204) and `admin / <old temp>` got 401.
```sh
#!/usr/bin/with-contenv bash
# 10-credentials.sh  (chmod +x; mounted read-only at /custom-cont-init.d)
set -eu
CONF=/config/qBittorrent/qBittorrent.conf
mkdir -p /config/qBittorrent
[ -f "$CONF" ] || cp /defaults/qBittorrent.conf "$CONF"
python3 - "$CONF" <<'PY'
import base64, hashlib, os, sys
conf = sys.argv[1]
user, pw = os.environ["QBITTORRENT_USER"], os.environ["QBITTORRENT_PASS"].encode()
salt = os.urandom(16)
key = hashlib.pbkdf2_hmac("sha512", pw, salt, 100000, 64)
line = "WebUI\\Password_PBKDF2=@ByteArray(%s:%s)" % (base64.b64encode(salt).decode(), base64.b64encode(key).decode())
out = []
for l in open(conf).read().splitlines():
    if l.startswith(("WebUI\\Username=", "WebUI\\Password_PBKDF2=")):
        continue
    out.append(l)
    if l.strip() == "[Preferences]":
        out += ["WebUI\\Username=" + user, line]
open(conf, "w").write("\n".join(out) + "\n")
PY
chown abc:abc /config/qBittorrent /config/qBittorrent/qBittorrent.conf
```
(The hash format and `[Preferences]` insertion were verified; the shell wrapper, `with-contenv` shebang and the `/defaults` copy path come from the read init scripts and could not be run without Docker: A2.)

### Pitfall 12: Session expiry and the `Referer` check
**What goes wrong:** Random 403s after an hour; or login 401 when a stray `Referer` is sent.
**Why:** `web_ui_session_timeout = 3600` and the cookie carries a 1 h `expires` [VERIFIED]; a login with `Referer: http://evil.example` returned 401, while no `Referer` and an in-network `Host` (`qbittorrent:18080`) returned 204 [VERIFIED].
**How to avoid:** relogin once on 403 (Pattern 7); do not set `Referer`/`Origin` from httpx; default `WebUI\ServerDomains=*` already lets `Host: qbittorrent:8088` pass (default conf read this session).

### Pitfall 13: Priority-0 files leave a hidden `.parts` file in the final folder
**What goes wrong:** After a torrent with skipped files completes, `/media/Film/.<hash>.parts` exists next to the content (observed with the subtitles-only run).
**How to avoid:** nothing to do in Phase 1; Phase 2.1 and Phase 4 must ignore dotfiles when moving or scanning (A6).

### Pitfall 14: All LAN clients may look like one IP behind WSL2 port forwarding
**What goes wrong:** The 5-per-15-minutes limiter (D-18) locks everyone out because Windows portproxy/NAT presents a single source address.
**Why:** Caddy sets `X-Forwarded-For` from its direct peer and ignores client-supplied values (verified), so the limiter sees whatever Caddy sees. With `netsh interface portproxy` that is the forwarder's address [CITED: learn.microsoft.com/windows/wsl/networking for the portproxy mechanism; the single-source consequence is an inference, A9].
**How to avoid:** key the limiter on the Caddy-provided client IP, document the effect for a one-account household, and prefer WSL mirrored mode (Windows 11 22H2+) if available.

## Code Examples

### Add + metadata + filter + start (verified call sequence, local run)
```python
# Source: verified against qbittorrent-nox 5.2.4
r = await qb.post("/api/v2/torrents/add", data={
    "urls": url,                          # single line only; reject any '\n' or '\r'
    "category": CATEGORY_BY_TYPE[type_],  # fixed dict, never request data
    "autoTMM": "true",
    "stopCondition": "MetadataReceived",
    "tags": f"fx,fx-pending,fx-job-{job_id}",
    **({"downloader": engine} if not url.lower().startswith("magnet:") else {}),
})
# 200 {"added_torrent_ids":[hash],...} for magnets, 202 {"pending_count":1,...} for downloader flow
files = await wait_for_files(hash_or_tag)           # GET /torrents/files?hash=  -> [] until metadata
decision = decide(files)                             # pure function: allowlist + sample heuristic
if decision.reject:
    await qb.post("/api/v2/torrents/delete", data={"hashes": h, "deleteFiles": "true"})
else:
    if decision.zero_ids:
        await qb.post("/api/v2/torrents/filePrio",
                      data={"hash": h, "id": "|".join(map(str, decision.zero_ids)), "priority": "0"})
    assert all(f["priority"] == 0 for f in await get_files(h) if f["index"] in decision.zero_ids)
    await qb.post("/api/v2/torrents/start", data={"hashes": h})
```
Real `torrents/files` rows (verbatim shape, 5.2.4): index, priority, size, name, e.g. `5 1 129241752 Sintel/Sintel.mp4`, `10 0 46115 Sintel/poster.jpg` (the last already 0 through the exclusion list). `filePrio` errors verified: invalid id → `409 File ID is not valid`; unknown hash → `404 Not Found`.

### Test helper for a synthetic multi-file torrent (integration test only)
Add a `.torrent` through multipart `torrents` (`stopped=true` is fine here because metadata is embedded); bencode `info` with `name`, `piece length`, random `pieces`, and `files`. Verified: 19-file torrent accepted in one call, priorities readable immediately via `torrents/files`.

### Frontend row states (D-10, D-11, D-13)
States: `idle → starting(spinner ≤15 s) → started "Avviato ✓" | preparing "In preparazione" | rejected "Questo file non contiene un video. Prova un altro risultato." | error`. Poll `GET /api/download/{job_id}` every 2 s while `preparing` so the row resolves without a downloads list. Vite config (verified): `base: '/'`, dev `server.proxy: {'/api': 'http://127.0.0.1:8000'}`.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `paused`, `pausedDL`, `torrents/pause|resume` | `stopped`, `stoppedDL`, `torrents/stop|start` | qBittorrent 5.x (tested 5.2.4, WebAPI 2.15.1) | Wiki page still shows old names (Pitfall 10); rename date is from memory (A1) |
| Add paused then wait | `stopCondition=MetadataReceived` | present in 5.2.4 | Only way to get a magnet's file list before downloading (Pitfall 1) |
| Cookie `SID` | `QBT_SID_<port>` | 5.2.4 observed | Never hard-code (Pitfall 12) |
| Login `200 "Ok."` / `"Fails."` | `204` / `401` / `403` ban | 5.2.4 observed | Accept 200 or 204; treat `"Fails."` as failure for safety |
| `lscr.io/.../qbittorrent:latest` rebuilt on dockerized binaries | static `userdocs` builds since 2026-05-04; `latest` = 5.3.0 (published 2026-10-20) | 2026 | Pin a tag; `latest` moved yesterday |
| Compose `version: "3.8"` key (design doc §11) | Compose v2 ignores it | n/a | Omit it (A4) |

**Deprecated/outdated:** design doc §11 compose example (port 8080 clash, `version`, `latest`, plaintext `APP_PASS`); wiki pages for 5.0 API names.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The pause→stop API rename landed with 5.0 / WebAPI 2.11.0 | State of the Art | Low: image is pinned and gated on `2.15.1`, which was tested |
| A2 | Custom init script needs `#!/usr/bin/with-contenv bash` to see container env, and `/defaults/qBittorrent.conf` exists at that point | Pitfall 11 | Medium: credentials not provisioned; backend login 401. Verify at first Docker run (checkpoint) |
| A3 | uvicorn flags `--proxy-headers --forwarded-allow-ips='*'` make `request.client` the Caddy-forwarded IP | Pitfall 14 / Pattern 1 | Low: only limiter accuracy; backend is unpublished so `*` is acceptable |
| A4 | Compose v2 ignores the obsolete `version:` key (warns) | State of the Art | Low |
| A5 | Docker-published ports bypass `ufw` | Pitfall 9 | Low: loopback bind is correct either way |
| A6 | Jellyfin ignores the hidden `.<hash>.parts` file | Pitfall 13 | Low-Medium: Phase 4 concern |
| A7 | Docker image build pattern `uv sync --frozen` works with the committed `uv.lock` | Structure | Low: pip fallback |
| A8 | `stopCondition=MetadataReceived` cannot download payload pieces before the stop (observed `downloaded=0` once for a magnet and once for the downloader flow) | Pitfall 1 | Medium for FILT-02 wording; mitigated because disallowed files are prio 0 before `start` and the exclusion list is already active |
| A9 | Windows portproxy/NAT shows all LAN clients as one source address | Pitfall 14 | Low: only login-limiter behaviour |
| A10 | Plugins not declaring category `tv` (piratebay 3.10 declares only `all, games, movies, music, software`) are skipped for `category=tv` searches, so TV coverage with official plugins is thin (observed: TV results came only from limetorrents) | Pattern 2 / Open Question 2 | Medium: poor series results; user may want unofficial plugins |
| A11 | qBittorrent passes `pattern` to plugin subprocesses without a shell | Pattern 2 | Low-Medium: query injection if wrong; query is length/charset limited anyway |
| A12 | Defaults `MIN_SERIE_SIZE_MB=100`, sample < 10 % of largest video, suspicious-term list, `SEARCH_TIMEOUT=20`, cap ~100 rows | Pattern 2/4 | Low: discretionary tuning knobs |
| A13 | Torrents keep seeding after completion (no share limit set) | Open Question 6 | Low-Medium: bandwidth/ISP/legal; user preference |

## Open Questions

1. **Search plugin provisioning vs D-08 "no extra code".**
   - Known: a fresh linuxserver container has `search/plugins` = `[]`, so the portal is empty until plugins are installed; the WebUI is not on the LAN, admin access needs the loopback publish.
   - Unclear: whether the user accepts ~15 lines of bootstrap that install missing official plugins from pinned URLs (`search/installPlugin`, verified working with raw GitHub URLs; plugin names appeared after ~6 s).
   - Recommendation: add a small optional bootstrap step driven by `QBITTORRENT_SEARCH_PLUGINS` (space-separated pinned URLs, default piratebay, limetorrents, eztv, torlock); document the manual WebUI route as the alternative. Needs a one-line user nod.
2. **Search coverage for series and Italian content.**
   - Known: official plugins work only partially in this environment (2 of 7 returned data; TV results came from one engine); `jackett` is official but needs a Jackett server.
   - Unclear: which unofficial plugins the user trusts; D-08 puts that on the admin.
   - Recommendation: ship with the official set, document how to add Jackett/unofficial plugins, and test TV search on the real laptop before sign-off.
3. **Docker runtime and LAN exposure on the WSL2 dev machine.**
   - Known: `docker` is not available in this WSL distro (error text recommends enabling Docker Desktop WSL integration); Microsoft documents `netsh interface portproxy` (NAT mode) and mirrored mode (Windows 11 22H2+) for LAN access.
   - Unclear: which the user uses; Docker Desktop publishes on Windows already, a native engine in WSL needs the portproxy; port 80 may also be taken on Windows.
   - Recommendation: `docs/setup.md` documents both paths for D-04; add a `checkpoint:human-verify` for the first `docker compose up` and a phone-on-LAN check.
4. **FILT-02 wording.** Keep the requirement ID; add a note in REQUIREMENTS.md/CLAUDE.md that "added stopped" is implemented as `stopCondition=MetadataReceived` (Pitfall 1). Non-blocking.
5. **`/api/health` vs AUTH-01.** The compose healthcheck and INFRA-01 need an unauthenticated probe. Recommendation: unauthenticated `GET /api/health` returns only `{"status":"ok"|"degraded","qbittorrent":"up"|"down"}` (no versions, paths, names); everything else requires login; record this as the single intentional exception.
6. **Seeding policy after completion.** qB keeps seeding by default. Decide whether to set a share limit (ratio/time) at bootstrap; not required for Phase 1 success criteria.
7. **Pin 5.2.4 or move to 5.3.0** (published 2026-10-20, one day before this research). Recommendation: pin 5.2.4 (tested here), run the integration test against 5.3.0 before bumping.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Docker Engine | INFRA-01, all compose checks | ✗ | — (WSL integration off) | Human checkpoint after enabling Docker Desktop WSL integration; Python invariant tests cover compose rules without Docker |
| Docker Compose v2 | INFRA-01 | ✗ | — | same as above |
| Python 3 | backend dev/tests | ✓ | 3.12.3 | — |
| uv | dependency mgmt | ✓ | 0.6.14 | pip |
| Node.js / npm | frontend | ✓ | v24.15.0 / 11.12.1 (Vite 8 needs ^20.19 or >=22.12) | — |
| curl | probes | ✓ | 8.5.0 | — |
| Caddy binary | local Caddyfile validation | ✗ (not installed) | 2.11.7 downloadable static binary, tested | `docker run caddy:2-alpine caddy validate` once Docker exists |
| qbittorrent-nox | optional integration test | ✗ (not installed) | 5.2.4 static binary downloadable from `userdocs/qbittorrent-nox-static` (tested) | Real container via compose |
| Internet access | plugins, magnet metadata, package installs | ✓ | — | — |
| `/dev/kvm` | Phase 2.1 only | ✓ | — | n/a this phase |
| gsd-tools | planning tooling | ✓ | 1.18.0 | — |

**Missing dependencies with no fallback:** none for coding; INFRA-01 end-to-end needs Docker and cannot be proven automatically on this machine today.
**Missing dependencies with fallback:** Docker (Python invariant tests + human checkpoint), Caddy and qbittorrent-nox binaries (download, or use containers later).

## Validation Architecture

`.planning/config.json` is absent, so `workflow.nyquist_validation` is treated as enabled.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | Backend: pytest 9.1.1 + pytest-asyncio 1.4.0 + respx 0.23.1 (+ `FakeQbit`); Frontend: vitest 5.0.5 + @testing-library/preact 3.2.4 + jsdom; Infra: pytest + PyYAML |
| Config file | none yet: Wave 0 creates `backend/pyproject.toml` (`[tool.pytest.ini_options]`, `asyncio_mode = "strict"`, marker `integration`), `frontend/vite.config.js` (`test: {environment: 'jsdom'}`) |
| Quick run command | `cd backend && uv run pytest -x -q -m "not integration"` and `cd frontend && npx vitest run` (both well under 30 s on the verified toolchain) |
| Full suite command | quick commands plus `uv run pytest infra/tests -q` (from repo root) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| AUTH-01 | Every route except login/health returns 401 without a session; login sets 30-day HttpOnly cookie; wrong password 401 | unit/API | `uv run pytest backend/tests/test_auth.py -x` | ❌ Wave 0 |
| AUTH-01 (D-18) | 6th failed login within window → 429; resets after window | unit | `uv run pytest backend/tests/test_login_throttle.py -x` | ❌ Wave 0 |
| SEC-01 | No response body or header contains qB password, qB URL, `/media`, `/incomplete`, `Film`/`SerieTV` category strings | API | `uv run pytest backend/tests/test_no_leaks.py -x` | ❌ Wave 0 |
| SEC-02 | Compose: qbittorrent has no non-loopback `ports`; only `web` publishes; qB not on `edge` | infra | `uv run pytest infra/tests/test_compose_invariants.py -x` | ❌ Wave 0 |
| SEC-03 | `type` ∉ {film, serie} → 422 and zero qB calls; download body carrying `category`/`path` fields is rejected/ignored | API | `uv run pytest backend/tests/test_validation.py -x` | ❌ Wave 0 |
| SEC-04 | Settings reject placeholders/short `SECRET_KEY`; `.env.example` has only placeholders; no tracked file contains an IPv4 literal other than `127.0.0.1`/`0.0.0.0`; `.env` is gitignored | unit/infra | `uv run pytest backend/tests/test_config.py infra/tests/test_repo_hygiene.py -x` | ❌ Wave 0 |
| SRCH-01 | `start` called with `category=movies` for film, `tv` for serie, `plugins=enabled` | respx wire | `uv run pytest backend/tests/test_qbit_client.py -k search -x` | ❌ Wave 0 |
| SRCH-02 | Normalization, `-1` handling, dedupe by btih, sort by seeders desc, min seeders/size, suspicious names, quality badge | unit | `uv run pytest backend/tests/test_filters.py -x` | ❌ Wave 0 |
| SRCH-03 | Snapshot polling returns partial results while running; timeout with zero results → `timed_out`; `search/stop` called | API + FakeQbit | `uv run pytest backend/tests/test_search_flow.py -x` | ❌ Wave 0 |
| DOWN-01/02 | `POST /api/download` resolves cached result, sends fixed category, `autoTMM=true`, `stopCondition=MetadataReceived`, tags; expired id → 410 | API + respx | `uv run pytest backend/tests/test_download_pipeline.py -k start -x` | ❌ Wave 0 |
| DOWN-03 | Bootstrap creates missing categories, edits differing `savePath`, tolerates existing (409), sets `temp_path`/auto TMM prefs | unit | `uv run pytest backend/tests/test_bootstrap.py -x` | ❌ Wave 0 |
| FILT-01 | Bootstrap sends newline-separated exclusion list with `excluded_file_names_enabled: true` including every FILT-01 pattern | unit | `uv run pytest backend/tests/test_bootstrap.py -k excluded -x` | ❌ Wave 0 |
| FILT-02 | No allowed video → delete with `deleteFiles=true`, D-13 text, never `start`; accepted → non-allowed and samples prio 0, verified, then `start`; `movie.mkv.exe` blocked; all-sample torrent rejected; timeout → delete + `unavailable`; `preparing` after 15 s while task continues | unit/API | `uv run pytest backend/tests/test_allowlist.py backend/tests/test_download_pipeline.py -x` | ❌ Wave 0 |
| PUI-01 | Layout renders in a narrow viewport; tap targets ≥ 44 px (CSS asserted); manual phone check | component + manual | `cd frontend && npx vitest run` | ❌ Wave 0 |
| PUI-02 | UI text never contains qB/category/path strings; row states and Italian copy per D-10/D-13; 401 → login | component | `cd frontend && npx vitest run src/__tests__/` | ❌ Wave 0 |
| INFRA-01 | Compose parses, healthchecks present, `GET /api/health` minimal + unauthenticated; **real `docker compose up` is manual** | infra + manual | `uv run pytest infra/tests/test_compose_invariants.py -k health -x`; manual: `docker compose up --build` | ❌ Wave 0 |
| INFRA-02 | All published host ports unique; no `8080`; qB WebUI ≠ 80/8000/8096; `QBITTORRENT_URL` port equals `WEBUI_PORT`; `docs/ports-and-media.md` lists them | infra | `uv run pytest infra/tests/test_compose_invariants.py -k ports -x` | ❌ Wave 0 |
| MEDIA-01 | Compose mounts Film/SerieTV from `MEDIA_ROOT`, incomplete outside `MEDIA_ROOT`, `PUID/PGID` set | infra | `uv run pytest infra/tests/test_compose_invariants.py -k media -x` | ❌ Wave 0 |
| (guard) | Real qB: stop-after-metadata flow, category path, exclusion, downloader flow (replays the verified sequence) | integration (opt-in) | `QBIT_TEST_URL=http://127.0.0.1:18080 QBIT_TEST_USER=… QBIT_TEST_PASS=… uv run pytest backend/tests/integration -m integration` | ❌ Wave 0 |
| (guard) | Caddyfile valid and routes `/`, `/login`, `/api/*`, `/tv/*` correctly | tooling | `caddy validate --config web/Caddyfile --adapter caddyfile` (binary or `docker run caddy:2-alpine`) | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** the backend quick command and, if the frontend changed, the vitest command.
- **Per wave merge:** full suite including `infra/tests` and `caddy validate`.
- **Phase gate:** full suite green, then a human run: `docker compose up --build`, phone on LAN logs in, searches, taps Download, file lands in the matching host folder; plus the opt-in integration test against the pinned image version.

### Wave 0 Gaps
- [ ] `backend/pyproject.toml`, `uv.lock`, `backend/tests/conftest.py` (settings fixture, `FakeQbit`, ASGI client fixture)
- [ ] `backend/tests/fixtures/` with the verbatim qB payloads quoted in this document (search result row, plugin row, files rows, add responses 200/202/409)
- [ ] `FakeQbit` reproducing the verified behaviours: empty `files` until metadata, 409 duplicate, 403 on missing session, auto-create category, `deleteFiles` required
- [ ] `frontend/vite.config.js` with vitest config + `src/__tests__/`
- [ ] `infra/tests/` (PyYAML) for compose and repo-hygiene invariants
- [ ] Installs: `uv sync`, `npm ci` (after the consolidated package checkpoint)
- [ ] Human prerequisite: enable Docker Desktop WSL integration (or install Docker Engine) before any compose task is executed

## Security Domain

`security_enforcement` is not disabled (config absent = enabled).

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | single account, argon2id (`argon2-cffi`), constant-time verify, login throttle (D-18); qB credentials are separate and backend-only |
| V3 Session Management | yes | Starlette signed cookie, HttpOnly, SameSite=Lax, 30-day `Max-Age`; `Secure` is not possible on plain-HTTP LAN (accepted, HTTPS deferred to EXT-01); rotating `SECRET_KEY` invalidates all sessions |
| V4 Access Control | yes | deny-by-default router dependency + route-enumeration test; result-token indirection instead of client-supplied URLs |
| V5 Input Validation | yes | Pydantic `Literal["film","serie"]`, query length/charset, `result_id` hex pattern, reject `\n` in URLs sent to qB |
| V6 Cryptography | yes | never hand-rolled: argon2-cffi, itsdangerous (via Starlette), PBKDF2-SHA512 from `hashlib` for the qB hash |
| V7 Logging | partial | no secrets in logs, redact qB password; full audit logging is Phase 2 (SEC-06) |
| V14 Configuration | yes | env-only config, placeholder rejection, `.gitignore` for `.env` and `qbittorrent/config/`, pinned image tag and plugin SHA |

### Known Threat Patterns for FastAPI + qBittorrent + Compose

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SSRF through a user-supplied torrent URL (qB would fetch internal addresses) | Tampering / Info disclosure | server-side `result_id` cache; never forward browser URLs; reject newlines |
| Category/path injection (qB auto-creates unknown categories, verified) | Tampering | fixed server map; 422 on unknown `type`; test asserts zero qB calls |
| Malicious payload files (exe, scripts, archives) | Tampering | exclusion list (FILT-01) + per-file allowlist with priority 0 and verify-before-start (FILT-02); quarantine/ffprobe in Phase 2.1 |
| Login brute force | Spoofing | in-memory limiter 5/15 min; argon2; Phase 2 adds full limits |
| qBittorrent WebUI exposed to LAN/Internet | Info disclosure / Elevation | no `ports:` or loopback-only; qB only on `qbit` network; invariant test; Docker bypasses ufw (Pitfall 9) |
| qB bans backend IP after bad credentials | Denial of service | single-shot login, backoff, clear log (Pitfall 7) |
| Search-plugin supply chain (Python run in container with network) | Tampering | install only official plugins from pinned commit SHAs; admin enables trusted plugins only (D-08) |
| Cleartext session cookie on LAN | Info disclosure | accepted for home LAN by project scope; document; HTTPS with VPN access deferred (EXT-01) |
| CSRF on state-changing endpoints | Tampering | SameSite=Lax cookie + JSON-only bodies; no GET side effects |
| Secrets committed to the public repo | Info disclosure | `.env.example` placeholders, hygiene test, ignore list; hash and password only via `.env` |
| Spoofed `X-Forwarded-For` defeating the limiter | Spoofing | Caddy ignores client-supplied values (verified); backend unpublished |

## Sources

### Primary (HIGH confidence)
- Local run of `qbittorrent-nox` 5.2.4 (WebAPI 2.15.1) on loopback, 2026-10-21: auth, preferences, categories, add (magnet stopped, stopCondition, autoTMM, downloader, duplicate, garbage, unknown category), files/filePrio/start/delete, search start/status/results/stop/delete, plugin install, exclusion matching with a synthetic 19-file torrent, PBKDF2 credential seeding.
- qBittorrent source (master, API 2.17.0): `src/webui/api/torrentscontroller.cpp` (addAction, filesAction, filePrioAction, deleteAction, createCategoryAction, fetchMetadataAction), `src/webui/api/searchcontroller.cpp` (startAction, resultsAction, downloadTorrentAction), `src/webui/webapplication.h`.
- linuxserver/docker-qbittorrent repo: `README.md`, `Dockerfile`, `root/defaults/qBittorrent.conf`, `init-qbittorrent-config/run`, `svc-qbittorrent/run`; Docker Hub tag API (`5.2.4`, `5.3.0`, `latest`).
- docs.linuxserver.io container-customization (`/custom-cont-init.d`).
- docs.docker.com variable-interpolation (single-quoted values literal; `${VAR:?err}`).
- caddyserver.com docs: `handle`, `try_files`, `reverse_proxy`; Caddy 2.11.7 binary validate + live routing test.
- PyPI / npm registries + local install and run of the full backend and frontend dependency sets.
- qbittorrent/search-plugins GitHub API (engines list, `versions.txt`, commits) and wiki "How to write a search plugin".
- Repo files read this session: `CLAUDE.md`, `01-CONTEXT.md`, `REQUIREMENTS.md`, `STATE.md`, `ROADMAP.md` (Phase 1 section), `qbit-wrapper.md`.

### Secondary (MEDIUM confidence)
- qBittorrent wiki "WebUI-API-(qBittorrent-5.0)": used for the preferences table, `setPreferences` JSON rule, `search/*` parameter lists; known stale on pause/stop naming.
- learn.microsoft.com/windows/wsl/networking (portproxy and mirrored mode).

### Tertiary (LOW confidence)
- Items tagged `[ASSUMED]` in the Assumptions Log (A1-A13), mainly custom-init script specifics, ufw behaviour, WSL source-address effects, discretionary thresholds.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH: every package installed and exercised on today's versions; seam flagged them SUS on heuristics only (age and repos checked).
- Architecture: HIGH for qB interaction and Caddy (executed); MEDIUM for compose/Docker pieces (not runnable here).
- Pitfalls: HIGH for 1-5, 7, 12, 13 (observed); MEDIUM for 6, 8, 11 (cited/derived, need first Docker run); LOW-MEDIUM for 9, 14.

**Research date:** 2026-10-21
**Valid until:** 2026-10-28 (qBittorrent 5.3.0, Preact 11 and Vite 8 are days old; re-run the integration test before bumping any pinned version)
