# Phase 2: Portal Download Management & Hardening - Context

**Gathered:** 2026-10-22
**Status:** Ready for planning

<domain>
## Phase Boundary

A logged-in household member opens a Downloads tab on the phone and sees the Film and SerieTV downloads with plain state and progress (refreshed about every 5 s), can cancel an in-progress download or remove a completed one from the list, and sees plain-language messages (with automatic retry) when qBittorrent is down or a request fails. Search and download requests are throttled, and the backend writes audit logs with no credentials. Two Phase 1 leftovers are folded in: phones pick up a new app version after a redeploy, and WR-01 (a non-allowlisted main video with a small allowlisted trailer).

Out of this phase: quarantine, ffprobe and the verifying / rejected-by-probe states (Phase 2.1); renaming into Jellyfin layout (Phase 4); deleting a completed film from the library; multiple accounts.

Decision IDs continue from Phase 1 (D-01..D-24) so they stay unique across the project.

</domain>

<decisions>
## Implementation Decisions

### Downloads list (DOWN-04)
- **D-25:** The list shows **every torrent in the `Film` and `SerieTV` categories**, including ones the admin added by hand in the WebUI, not only `fx`-tagged ones. Torrents in other categories never appear.
- **D-26:** Layout: **two tabs, Search | Downloads**, under the app header. Switching tabs must not lose the search (it already lives in sessionStorage, D-24).
- **D-27:** Each row: **name, Movie/TV badge, progress bar with %, plain state**, plus a rough time left while downloading (e.g. "about 20 min left"). No speed, seeders or raw qBittorrent state names. Plain states map qBittorrent states to a small set: Preparing / Downloading / Ready / Stalled / plus the failure states below. Exact mapping is Claude's discretion.
- **D-28:** A completed download stays in the list **7 days after completion**, then drops off the list (the file stays on disk, the torrent is not touched by this). Env-configurable, default 7 days.
- **D-29:** Failed attempts (rejected, unsupported, unavailable, failed, D-11..D-13) **show in the list for 24 h** with their existing plain message, so a "Preparing" row that later failed is not silently lost. Kept in the in-memory job registry; a backend restart clears them (acceptable).
- **D-30:** Order: **active first** (Preparing, Downloading, Stalled), then the rest, **newest first** within each group.
- **D-31:** Polling every ~5 s **only while the Downloads tab is visible** and the page is not hidden (Page Visibility); refresh immediately when the user comes back.

### Cancel rules (DOWN-05)
- **D-32:** Cancelling an **in-progress** download (including Preparing) deletes the torrent **and its partial files** from qBittorrent, after **one confirm tap** ("Cancel this download?"). The row then disappears.
- **D-33:** A **completed** download has **no Cancel**. It has **"Remove from list"**, which removes the torrent from qBittorrent **keeping the files** (`deleteFiles=false`; stops seeding early, overriding D-21 for that torrent). The film never gets deleted from the phone. — **Reversibility:** reversible.
- **D-34:** Admin-added Film/SerieTV torrents follow **the same rules** as portal-started ones (one shared account, one household).
- **D-35:** The browser identifies a torrent by an opaque id from the list response, never by sending a path or category; the backend re-checks that the torrent is in `Film` or `SerieTV` before acting (SEC-03 spirit).

### Errors and outage (DOWN-06)
- **D-36:** When qBittorrent is unreachable with the Downloads tab open: **keep the last known list, greyed**, show a banner "Can't reach the download service. Retrying…", keep polling, clear the banner on its own when it comes back. Cancel / Remove are disabled meanwhile.
- **D-37:** Every failure shows plain English from `messages.js`; invalid torrent (415), unreachable (502, auto-retry), invalid category path (409), wrong qBittorrent credentials (401: logged, generic message only). No status codes or qBittorrent text reach the screen (same rule as Phase 1, 01-11 / 01-12).

### Throttling (SEC-05)
- **D-38:** **Generous limits:** search **10 per minute**, download **20 per minute**, env-configurable. Only a stuck finger or a script should hit them. Reusing the `LoginThrottle` sliding-window approach is Claude's discretion (keying per address vs global as in WR-07).
- **D-39:** When throttled the user sees **"Too many requests. Wait a moment and try again."** on the search box or the row. No countdown.

### Audit logs (SEC-06)
- **D-40:** Logs go to **stdout only** (`docker compose logs backend`); compose sets Docker's json-file driver with **size rotation (e.g. 10 MB x 5)**. No log volume.
- **D-41:** Audit events: login (success / fail / throttled), search (**with the search text** and type), download (**with the torrent name** and outcome), cancel / remove (torrent name), throttled requests, errors. **Client IP included.** Never: passwords, hashes, session cookies, `SECRET_KEY`, qBittorrent credentials or its SID. Log format (plain lines vs JSON) is Claude's discretion, consistent with the existing `LOG_FORMAT`.

### Phase 1 leftovers (folded)
- **D-42:** **Stale clients:** Caddy sends `Cache-Control: no-cache` on `index.html` (and the SPA fallback) and long immutable caching on hashed `/assets/*`, so phones pick up a new version after a redeploy.
- **D-43:** **WR-01:** when choosing the main video, the allowlist counts **non-allowlisted videos too**. If the largest video in the torrent is not allowlisted (e.g. a big `.webm` film with a small `.mp4` trailer), the torrent is rejected as **`unsupported`** with the existing text "This video format isn’t supported. Try another result." (D-13 amended). The FILT-02 allowlist itself is unchanged.

### Claude's Discretion
- Mapping of qBittorrent states to plain states, and the ETA wording/rounding.
- List API shape (one endpoint merging qBittorrent torrents and in-memory failed jobs is the expected shape).
- Throttle keying and whether the login throttle class is generalized.
- Log format and event field names.
- Visual design of tabs, rows, confirm dialog; keep large tap targets and the existing CSP (no inline styles, D-03 / 01-04).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Portal spec
- `qbit-wrapper.md` §3 — F6 (downloads list), F7 (cancel), NF6 (logs)
- `qbit-wrapper.md` §5.3 — monitoring flow (downloads list)
- `qbit-wrapper.md` §7 — proposed backend API
- `qbit-wrapper.md` §8 — qBittorrent Web API v2 (torrents/info, torrents/delete)
- `qbit-wrapper.md` §10 — security (rate limiting, logs)
- `qbit-wrapper.md` §13 — error codes (415, 502, 409, 401)

### Planning
- `.planning/REQUIREMENTS.md` — DOWN-04, DOWN-05, DOWN-06, SEC-05, SEC-06
- `.planning/ROADMAP.md` — Phase 2 goal and success criteria; Phase 2.1 (depends on this list for verifying / rejected states)
- `.planning/PROJECT.md` — Key Decisions; Active items for the stale-client fix and WR-01
- `.planning/phases/01-portal-search-start-download/01-CONTEXT.md` — D-01..D-24 (job states, messages, sessionStorage, seeding D-21)
- `.planning/phases/01-portal-search-start-download/COVERAGE.md` — qBittorrent API coverage; per-torrent controls deferred to Phase 2
- `.planning/phases/01-portal-search-start-download/01-REVIEW.md` — WR-01 original finding
- `.planning/phases/01-portal-search-start-download/01-UAT.md` — stale-client report (G-01-2 / webm diagnosis)

### Ops docs
- `docs/setup.md` — admin guide to update with log viewing and new env vars
- `docs/ports-and-media.md` — port map and media contract (unchanged here)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `backend/app/download/jobs.py` `JobRegistry` / `JobState`: in-memory jobs with failure states; source for D-29 failed rows (needs a finished-at time for the 24 h window).
- `backend/app/download/pipeline.py`: `fx`, `fx-pending`, `fx-job-<id>` tags and reconcile; delete helpers and tag cleanup to reuse for cancel.
- `backend/app/download/allowlist.py`: main-video selection to change for D-43.
- `backend/app/auth.py` `LoginThrottle`: sliding-window limiter (per address + global) to generalize for D-38.
- `backend/app/qbit/client.py` `QbitClient`: hardened client with shared re-login and cool-downs; add torrents/info and delete calls here.
- `frontend/src/api.js` `ApiError` (status 0 = unreachable), `frontend/src/messages.js` `MSG`: all user text.
- `frontend/src/App.jsx`: header + single `<Search/>`; tabs go here. `Search.jsx` owns sessionStorage state (D-24).

### Established Patterns
- Every feature router uses `protected_router()`; a route-enumeration test fails otherwise (01-05).
- Downloads gated by `require_ready` (503 not_ready) until bootstrap succeeds (01-06).
- Logs record exception class and HTTP status only, never bodies (pipeline, search service).
- CSP `default-src 'self'` at Caddy: no inline style attributes (01-04).
- Repo hygiene scanner and no-third-party frontend test must keep passing.

### Integration Points
- `web/Caddyfile`: cache headers for D-42.
- `docker-compose.yml`: logging driver rotation for D-40; new env vars into `.env.example`.
- Phase 2.1 will add verifying / rejected-by-probe states to this list: keep the state mapping in one place.

</code_context>

<specifics>
## Specific Ideas

- Confirm text: "Cancel this download?"; completed rows offer "Remove from list".
- Outage banner: "Can't reach the download service. Retrying…".
- Throttle message: "Too many requests. Wait a moment and try again."
- ETA phrasing like "about 20 min left".

</specifics>

<deferred>
## Deferred Ideas

- Deleting a completed film from the library from the phone — rejected for now (D-33); revisit only with a strong confirm if the household needs to free space.
- Verifying / rejected-by-probe states in the list — Phase 2.1.

</deferred>

---

*Phase: 02-portal-download-management-hardening*
*Context gathered: 2026-10-22*
