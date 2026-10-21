# Phase 1: Portal Search & Start Download - Context

**Gathered:** 2026-10-21
**Status:** Ready for planning

<domain>
## Phase Boundary

A household member opens the portal on a phone over the LAN, logs in, picks Film or Serie TV, searches by keyword through qBittorrent's search plugins, and taps Download on a result. The backend adds the torrent stopped, filters its file list (video + subtitles only), starts it in the right category (`Film` → `/media/Film`, `SerieTV` → `/media/SerieTV`), and the user never sees qBittorrent, paths, categories or credentials. The stack (Caddy, portal backend, qBittorrent) starts with one `docker compose up`; one port map and one media-folder contract are documented.

Out of this phase: download list, cancel, audit logs and full rate limiting (Phase 2); quarantine/ffprobe (Phase 2.1); Jellyfin and the TV app (Phase 3+).

</domain>

<decisions>
## Implementation Decisions

### Stack and serving
- **D-01:** Portal backend is **FastAPI (Python)**. Resolves the "FastAPI or Node" pending decision in PROJECT.md. — **Reversibility:** costly — every backend module, the qBittorrent client and tests would be rewritten.
- **D-02:** Portal frontend is a **Preact + Vite SPA**, the same stack proposed for the TV app.
- **D-03:** **Caddy is introduced already in Phase 1** (pulled forward from Phase 3). Caddy serves the SPA's static build and reverse-proxies `/api/*` to FastAPI. FastAPI serves API only, no static files. Same origin, no CORS.
- **D-04:** Caddy listens on **host port 80**; the phone opens `http://<laptop>/`. On WSL2 this needs Windows port forwarding, which must be documented. qBittorrent WebUI is not on the LAN (SEC-02) and uses a port that differs from 80 and from the backend's internal port. — **Reversibility:** costly — port is in the documented port map and household bookmarks.
- **D-05:** **One Caddy for both portal and TV app, separated by path** on the same port (e.g. `/portale` and `/tv`, or portal at `/` and TV at `/tv`; exact paths are Claude's discretion). Phase 1 only wires the portal path but the Caddyfile and port map must leave room for the TV path and Jellyfin proxying in Phase 3. The Vite build must use a matching `base` path.

### Search and results
- **D-06:** Results **fill in live** while the qBittorrent search runs (first results in ~2 s), re-sorted by seeders descending, with a visible "searching" indicator; timeout shows a plain-language message (SRCH-03).
- **D-07:** Hide results below a **minimum seeders threshold**, env `MIN_SEEDERS`, **default 5**. The user wants a "sweet spot": hide dead torrents while keeping enough results that are safe and actually download.
- **D-08:** Anti-fake filtering, all of these:
  - Hide **films that are too small** (configurable env, default ~500 MB; applies to `film` type — Claude decides whether and how a per-episode threshold applies to `serie`).
  - **Only trusted search plugins**: the admin enables only reliable plugins in qBittorrent; the portal uses all enabled plugins. Document this in setup docs; no extra code.
  - **Hide suspicious names** (e.g. containing `.exe`, `password`, `codec`, and similar markers; list is Claude's discretion, keep it configurable or in one place).
  - **Quality badge**: parse `1080p` / `2160p`/`4K` (and similar) from the name and show a badge. Badge only, not a filter.
- **D-09:** Result row: **name (full) + size (human, e.g. "4.2 GB") + seeders prominent**; leechers and source small and grey.
- **D-10:** After tapping Download the user **stays on the results list**; the button turns into "Avviato ✓". Errors and rejections are shown on that row. The user can start more downloads from the same list.

### Torrent acceptance flow (FILT-02)
- **D-11:** After the tap, the row shows a spinner for up to **~15 s** while the backend waits for metadata. If metadata arrives: show "✓ Avviato" or the rejection. If not: show "In preparazione" and the **backend keeps processing on its own** (background task, not tied to the HTTP request). The final outcome becomes visible in the Phase 2 downloads list.
- **D-12:** Metadata timeout is env `METADATA_TIMEOUT`, **default 5 minutes**; after it the torrent is removed from qBittorrent and marked unavailable.
- **D-13:** Rejection text (no allowed video file): **"Questo file non contiene un video. Prova un altro risultato."** No technical detail.
- **D-14:** Multi-video torrents: download **all allowed video files** (full seasons are fine) but set **priority 0 on samples**: files with "sample" in the name, or tiny compared with the main video. Subtitles stay allowed.

### Login and access
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

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Portal spec
- `qbit-wrapper.md` §3 — functional and non-functional requirements F1-F8 / NF1-NF6
- `qbit-wrapper.md` §5 — main flows (search, download)
- `qbit-wrapper.md` §6 — categories and save paths
- `qbit-wrapper.md` §7 — proposed backend API
- `qbit-wrapper.md` §8, §9 — qBittorrent Web API v2 integration and search plugins
- `qbit-wrapper.md` §10 — security
- `qbit-wrapper.md` §11 — deployment (note: its 8080 port conflict is superseded by D-04)
- `qbit-wrapper.md` §12 — env configuration (amended by D-07, D-08, D-12, D-17)
- `qbit-wrapper.md` §13 — error handling codes

### Planning
- `.planning/REQUIREMENTS.md` — AUTH-01, SEC-01..04, SRCH-01..03, DOWN-01..03, PUI-01..02, INFRA-01..02, MEDIA-01, FILT-01..02
- `.planning/ROADMAP.md` — Phase 1 goal and success criteria
- `.planning/PROJECT.md` — Key Decisions table (W2, W3 pending items)

### Cross-part (for D-05 path layout)
- `home-theater.md` "Architettura generale" — Caddy single-origin design for Jellyfin + TV frontend

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- None: the repo has no code yet (planning stage).

### Established Patterns
- None in code. Project constraints: Docker on LAN, public MIT repo with no secrets or LAN IPs, planning files in English, UI text in Italian.

### Integration Points
- qBittorrent Web API v2 (search, torrents/add, files, filePrio, categories, preferences `excluded_file_names`).
- Caddy is the shared entry point that Phase 3 extends for Jellyfin and the TV app.
- Host media folders are shared with Jellyfin later (MEDIA-01 contract).

</code_context>

<specifics>
## Specific Ideas

- User explicitly wants a seeders "sweet spot": not just hiding 0-seeder results, but keeping only results that are safe and will actually download.
- Rejection message wording is fixed: "Questo file non contiene un video. Prova un altro risultato."
- Button state after tap: "Avviato ✓"; pending state: "In preparazione".

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope. (Caddy was pulled forward from Phase 3 into Phase 1 by user choice; Phase 3 still owns the Jellyfin/TV routes.)

</deferred>

---

*Phase: 01-portal-search-start-download*
*Context gathered: 2026-10-21*
