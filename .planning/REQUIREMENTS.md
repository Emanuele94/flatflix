# Requirements: flatflix

**Defined:** 2026-10-21
**Core Value:** A non-technical household member can get a film or series onto the TV using only a phone and the TV remote, and watch it in at least 1080p with no video transcoding.

Both source docs are SPECs, so there were no REQ-* entries to carry over. IDs below were derived by the roadmapper from the requirement-style lists in the specs.

Source tags: `qbit` = /home/emanuele/projects/flatflix/qbit-wrapper.md (F1-F8, NF1-NF6, sections 5-13); `ht` = /home/emanuele/projects/flatflix/home-theater.md; `W1`/`W2`/`W3` = ingest warnings in /home/emanuele/projects/flatflix/.planning/INGEST-CONFLICTS.md (naming gap, shared media wiring, port map); `derived` = added by the roadmapper to make a warning or the success metric testable; `user` = added by the user after roadmap creation (2026-10-21).

## v1 Requirements

Requirements for the initial release. Each maps to exactly one roadmap phase.

### Portal Access & Security

- [ ] **AUTH-01**: User must log in with the portal's own username and password (separate from qBittorrent) before any search, download or status page or API endpoint is reachable; unauthenticated visits go to the login page. (qbit F8, section 10)
- [ ] **SEC-01**: qBittorrent credentials and session cookie live only in the backend; they never appear in any page, script or response the browser receives. (qbit NF3)
- [x] **SEC-02**: qBittorrent's WebUI is reachable only from the backend over the internal container network; if published at all for admin setup it is bound to the laptop's loopback only, never to the LAN or Internet. (qbit NF4, section 10)
- [ ] **SEC-03**: The backend accepts only `type` = `film` or `serie` (strict validation) and never accepts a file path or category name from the browser. (qbit sections 6, 10)
- [x] **SEC-04**: All configuration (qBittorrent URL/user/password, categories, portal user/password, session key) comes from environment variables, with a committed `.env.example` holding placeholders only; the repo contains no secrets, LAN IPs or real credentials. (qbit NF5, section 12; user constraint)
- [ ] **SEC-05**: Search and download endpoints are rate limited, so repeated rapid requests are throttled with a clear message. (qbit section 10)
- [ ] **SEC-06**: The backend writes essential logs for debugging and audit (logins, searches, downloads, cancels, errors) and no log line contains credentials. (qbit NF6, section 10)

### Portal Search

- [ ] **SRCH-01**: User can choose Film or Serie TV and search by keyword; the backend queries the installed qBittorrent search plugins using plugin category `movies` (film) or `tv` (serie). (qbit F1, section 9)
- [ ] **SRCH-02**: Results show name, size, seeders, leechers and source, normalized and sorted by seeders descending. (qbit F2, section 9)
- [ ] **SRCH-03**: First results appear within about 2 seconds of submitting a search (results fill in while the qBittorrent search runs), and a search timeout shows a plain-language message instead of an error. (qbit NF2, section 13 code 504)

### Portal Downloads

- [ ] **DOWN-01**: User can start the download of a search result with one tap on Download. (qbit F3)
- [ ] **DOWN-02**: The download is automatically assigned to category `Film` (film) or `SerieTV` (serie) by the backend; the user never picks a category. (qbit F4)
- [ ] **DOWN-03**: Each category saves to its predefined path (`Film` -> `/media/Film`, `SerieTV` -> `/media/SerieTV`): categories are created through the API at startup if missing, "Append category name to save path" is disabled, and the browser sends no path. (qbit F5, section 6)
- [ ] **DOWN-04**: User can see downloads in progress and completed (Film and SerieTV only) with their state and progress, refreshed about every 5 seconds. (qbit F6, section 5.3)
- [ ] **DOWN-05**: User can cancel a download from the list and it is removed from qBittorrent. (qbit F7)
- [ ] **DOWN-06**: Failures show plain messages to the user: invalid torrent (415), qBittorrent unreachable (502, with automatic retry), invalid category path (409); wrong qBittorrent credentials (401) are logged and shown only as a generic message. (qbit section 13)

### Portal Interface

- [x] **PUI-01**: The portal interface is responsive and fully usable on a smartphone. (qbit NF1)
- [ ] **PUI-02**: The end user never sees qBittorrent, save paths, category names or credentials; the main flow is a search followed by a single Download button. (qbit sections 1, 2, 15 closing note)

### Download Filtering & Validation

- [ ] **FILT-01**: At startup the backend sets qBittorrent's global excluded-file-names list (executables, scripts, shortcuts, archives, disk images, e.g. `*.exe`, `*.bat`, `*.cmd`, `*.ps1`, `*.scr`, `*.lnk`, `*.msi`, `*.zip`, `*.rar`, `*.7z`, `*.iso`), so such files are never downloaded. (user)
- [ ] **FILT-02**: The backend adds every torrent stopped, waits for its metadata and reads the file list against an allowlist (video: `.mkv`, `.mp4`, `.avi`, `.m4v`; subtitles: `.srt`, `.ass`, `.ssa`, `.sub`, `.idx`). A torrent with no allowed video file is removed before any data is downloaded and the user sees a plain message; in an accepted torrent every non-allowed file gets priority 0; only then is the torrent started. (user)
- [ ] **QUAR-01**: Completed downloads are saved to a quarantine folder (per category) outside the media folders that Jellyfin reads; no file moves to a media folder without passing validation. (user)
- [ ] **QUAR-02**: Each completed video file is probed with ffprobe inside a fresh Firecracker microVM: no network device, the file attached read-only, fixed vCPU and memory limits, a hard wall-clock timeout, and the VM destroyed after the check; a crash or timeout counts as a failure. (user)
- [ ] **QUAR-03**: A file passes only if its real container (per ffprobe) matches its extension, it has at least one video stream with a known codec, and its duration and size are plausible for its type (configurable thresholds for film and episode). (user)
- [ ] **QUAR-04**: Passing files move to the media folder of their category (Phase 4 later adds renaming to this move); failing files never reach a media folder, their torrent is removed from qBittorrent, the download list shows a plain "verifying" then "ready" or "rejected" state, and the reason is logged for the admin. (user)
- [ ] **QUAR-05**: The microVM runner uses a pinned Firecracker version and a guest kernel plus ffprobe rootfs built by scripts in the repo (no binaries committed); documented steps set it up on the dev machine (WSL2 with `/dev/kvm`) and on the production Ubuntu Server box; the portal calls it through one stable interface so the sandbox can be swapped. (user)

### Shared Infrastructure

- [ ] **INFRA-01**: The portal stack (frontend, backend, qBittorrent) starts with a single `docker compose up` on the laptop and `GET /api/health` reports service status. (qbit section 7, 11)
- [x] **INFRA-02**: One laptop-wide port map, documented in one place, assigns host ports for Caddy, the portal frontend, the qBittorrent WebUI (only if published) and Jellyfin 8096 without collisions; qBittorrent's WebUI port differs from the portal frontend's and `QBITTORRENT_URL` matches. (W3)
- [ ] **INFRA-03**: Caddy and Jellyfin run according to the port map; the portal and Jellyfin/Caddy stacks share a Docker network or one compose project; whether Caddy also fronts the portal is decided and recorded; the TV reaches Jellyfin only through Caddy's single address. (W3, ht architecture)
- [ ] **INFRA-04**: A DHCP reservation keeps the laptop on the same LAN IP, so the TV address does not change after reboots. (ht setup)
- [ ] **INFRA-05**: The whole stack (portal, Firecracker validation runner, Jellyfin, Caddy) comes up on a fresh Ubuntu Server machine from the repo using documented steps and a `.env` built from `.env.example`; moving to another machine changes only the host address. (ht architecture, derived)

### Shared Media & Naming

- [x] **MEDIA-01**: Host media folders for Film and SerieTV are defined once (host paths, owner UID/GID), writable by qBittorrent, and qBittorrent keeps incomplete downloads in a separate folder so the final folders contain only completed files. (W2, qbit sections 6, 11)
- [ ] **MEDIA-02**: Jellyfin mounts both media folders read-only with matching permissions and has two libraries, Film and SerieTV, pointing at them. (W2, ht setup)
- [ ] **MEDIA-03**: When a download completes, the Jellyfin library is refreshed automatically (rescan trigger or schedule) so the item appears without admin action; partially downloaded files are never scanned. (W2)
- [ ] **NAME-01**: The owner of the Jellyfin naming layout is decided and recorded in PROJECT.md Key Decisions (portal post-download step, external library manager, or relaxed requirement), backed by a Jellyfin scan test using raw torrent-style names; this is resolved before the two parts are integrated. (W1)
- [ ] **NAME-02**: A completed film download ends up as `Title (Year)/Title (Year).<ext>` in the film media folder. (W1, ht naming)
- [ ] **NAME-03**: A completed series episode download ends up as `Series/Season 01/Series S01E01.<ext>` in the series media folder. (W1, ht naming)
- [ ] **NAME-04**: A download that cannot be identified is neither silently dropped nor mis-filed: it stays in an unsorted location and is flagged in the logs for the admin. (W1, derived)

### Jellyfin Server & TV Compatibility

- [ ] **JFIN-01**: Jellyfin runs in Docker on the laptop with persistent config, cache and media volumes and its admin UI on port 8096; a household user exists (one shared user vs separate profiles decided and recorded) with default audio and subtitle language set. (ht setup, open decisions)
- [ ] **JFIN-02**: Scanning correctly named sample content (in a scratch folder separate from the portal's folders) produces posters, plots, cast, seasons and episodes stored locally. (ht backend)
- [ ] **JFIN-03**: A maximum streaming bitrate suited to the home network is configured on Jellyfin. (ht network)
- [ ] **COMPAT-01**: Tested on the real TV through Jellyfin's web UI: H.264 and HEVC video, including 10-bit, play and the playback method (direct play / remux / transcode) is recorded. (ht compatibility test)
- [ ] **COMPAT-02**: Tested on the real TV: AAC, AC3, EAC3 and DTS audio, with the playback method recorded for each. (ht compatibility test)
- [ ] **COMPAT-03**: Tested on the real TV: SRT and embedded subtitles, with the result recorded. (ht compatibility test)
- [ ] **COMPAT-04**: Jellyfin's admin dashboard is checked to see which playbacks end in transcoding, and a go/no-go verdict on "no video transcoding" is recorded; if no-go, a mitigation is chosen (re-encode library, plan B stick, or stronger server hardware). (ht compatibility test, playback matrix)

### TV App

- [ ] **TV-01**: The Home screen shows "Continue watching" and entry points to the Films and Series libraries. (ht requirements)
- [ ] **TV-02**: The Library screen shows poster grids for films and series, using the reduced image size requested from Jellyfin. (ht requirements, API surface)
- [ ] **TV-03**: The Detail screen shows poster, plot, seasons and episodes, and a watched / unwatched marker. (ht requirements)
- [ ] **TV-04**: The whole app is usable with the remote only: arrows move focus spatially, OK selects, Back works on every screen, Play/Pause works in the player. (ht requirements)
- [ ] **TV-05**: A lightweight transpiled build loads on the VIDAA browser without a blank page or script errors, and poster-grid scrolling is smooth on the real TV; the framework choice (Preact vs SolidJS) is recorded after a grid prototype on the TV. (ht constraints, open decisions)
- [ ] **TV-06**: The frontend authenticates to Jellyfin (user login or API key, decision recorded) and talks only to the single Caddy origin; no credentials are committed. (ht API surface, user constraint)
- [ ] **TV-07**: When the laptop is off or unreachable, the app shows a clear "server unreachable" screen instead of a blank or hung page. (ht risks)
- [ ] **PLAY-01**: Selecting a film or episode starts full-screen playback at 1080p or better through `PlaybackInfo` with the TV's device profile and the returned stream URL. (ht requirements, API surface)
- [ ] **PLAY-02**: For compatible library content, video is never transcoded: Jellyfin uses direct play, remux to HLS, or audio-only transcode. (ht playback matrix)
- [ ] **PLAY-03**: Playback start, progress and stop are reported to Jellyfin, so "Continue watching" resumes at the right position and finished titles become watched. (ht API surface, requirements)
- [ ] **PLAY-04**: The player uses the native `<video>` element with HLS, or hls.js over Media Source Extensions if the TV lacks HLS; Play/Pause and seeking work from the remote and subtitles can be switched on. (ht playback)

### Launch & Acceptance

- [ ] **LAUNCH-01**: An icon on the VIDAA home opens the app full screen directly, with no browser UI, and still works after a TV restart (plan A; the community tool's source is read before use). (ht distribution)
- [ ] **LAUNCH-02**: Plan A is checked for viability on the real TV; if it is not viable, plan B (HDMI stick with WebView APK) is selected and recorded as the follow-up. (ht distribution, risks)
- [ ] **ACPT-01**: A non-technical household member, using only a phone, logs into the portal, searches and starts a film download; later, using only the TV remote from the icon, she finds that film and plays it at 1080p or better with no video transcoding. (success metric, derived)
- [ ] **ACPT-02**: The same end-to-end flow works for a TV series episode, appearing under the right season. (success metric, derived)

## v2 Requirements

Deferred to a future release. Tracked but not in the current roadmap.

### Portal Enhancements (qbit section 14)

- **TMDB-01**: Portal shows covers and normalized titles from TMDB (may be pulled into v1 if the Phase 3 naming decision relies on TMDB identification)
- **SERI-01**: Automatic season/episode search for series
- **NOTF-01**: Push notification when a download completes
- **USER-01**: Multiple portal users with separate categories
- **QUAL-01**: Quality (1080p, 4K) and language filter in search
- **SUBT-01**: Automatic subtitle download

### Home Theater Extensions (home-theater.md)

- **PROF-01**: Separate Jellyfin profiles per household member
- **EXT-01**: Access from outside the home via VPN (Tailscale or WireGuard), with HTTPS if the portal is exposed
- **PLANB-01**: Plan B packaging: same frontend in a WebView (e.g. Capacitor) as an APK for a Google TV / Fire TV stick (pulled into v1 if LAUNCH-02 finds plan A not viable)
- **HW-01**: Move the stack to a dedicated always-on server running Ubuntu Server; it must be x86_64 with VT-x/AMD-V and KVM so Firecracker runs (e.g. Intel N100/N150 mini PC). Raspberry Pi 5 is likely unsuitable: Firecracker on ARM expects a GICv3 interrupt controller (verify before buying)

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Replacing Sonarr/Radarr or other library managers | Portal non-goal; the NAME-01 decision may still evaluate one as an external tool |
| Music, books, games, software | Films and TV series only |
| Exposing the qBittorrent WebUI to the Internet | Security rule; stays on the internal network |
| End users changing categories, paths or qBittorrent settings | The user must never see them |
| Access from outside home | Out of scope for now; deferred to EXT-01 |
| Multiple users with separate profiles | Out of scope for now; deferred to PROF-01 |
| Publishing on the VIDAA store | Developer account, NDA and certification not worth it for home use |
| VIDAA-specific APIs in the frontend | Keeps plan A to plan B free of rewrites |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| AUTH-01 | Phase 1 | Pending |
| SEC-01 | Phase 1 | Pending |
| SEC-02 | Phase 1 | Complete |
| SEC-03 | Phase 1 | Pending |
| SEC-04 | Phase 1 | Complete |
| SEC-05 | Phase 2 | Pending |
| SEC-06 | Phase 2 | Pending |
| SRCH-01 | Phase 1 | Pending |
| SRCH-02 | Phase 1 | Pending |
| SRCH-03 | Phase 1 | Pending |
| DOWN-01 | Phase 1 | Pending |
| DOWN-02 | Phase 1 | Pending |
| DOWN-03 | Phase 1 | Pending |
| DOWN-04 | Phase 2 | Pending |
| DOWN-05 | Phase 2 | Pending |
| DOWN-06 | Phase 2 | Pending |
| PUI-01 | Phase 1 | Complete |
| PUI-02 | Phase 1 | Pending |
| INFRA-01 | Phase 1 | Pending |
| INFRA-02 | Phase 1 | Complete |
| INFRA-03 | Phase 3 | Pending |
| INFRA-04 | Phase 3 | Pending |
| INFRA-05 | Phase 6 | Pending |
| MEDIA-01 | Phase 1 | Complete |
| FILT-01 | Phase 1 | Pending |
| FILT-02 | Phase 1 | Pending |
| QUAR-01 | Phase 2.1 | Pending |
| QUAR-02 | Phase 2.1 | Pending |
| QUAR-03 | Phase 2.1 | Pending |
| QUAR-04 | Phase 2.1 | Pending |
| QUAR-05 | Phase 2.1 | Pending |
| MEDIA-02 | Phase 4 | Pending |
| MEDIA-03 | Phase 4 | Pending |
| NAME-01 | Phase 3 | Pending |
| NAME-02 | Phase 4 | Pending |
| NAME-03 | Phase 4 | Pending |
| NAME-04 | Phase 4 | Pending |
| JFIN-01 | Phase 3 | Pending |
| JFIN-02 | Phase 3 | Pending |
| JFIN-03 | Phase 3 | Pending |
| COMPAT-01 | Phase 3 | Pending |
| COMPAT-02 | Phase 3 | Pending |
| COMPAT-03 | Phase 3 | Pending |
| COMPAT-04 | Phase 3 | Pending |
| TV-01 | Phase 5 | Pending |
| TV-02 | Phase 5 | Pending |
| TV-03 | Phase 5 | Pending |
| TV-04 | Phase 5 | Pending |
| TV-05 | Phase 5 | Pending |
| TV-06 | Phase 5 | Pending |
| TV-07 | Phase 5 | Pending |
| PLAY-01 | Phase 5 | Pending |
| PLAY-02 | Phase 5 | Pending |
| PLAY-03 | Phase 5 | Pending |
| PLAY-04 | Phase 5 | Pending |
| LAUNCH-01 | Phase 6 | Pending |
| LAUNCH-02 | Phase 6 | Pending |
| ACPT-01 | Phase 6 | Pending |
| ACPT-02 | Phase 6 | Pending |

**Coverage:**
- v1 requirements: 59 total
- Mapped to phases: 59
- Unmapped: 0

---
*Requirements defined: 2026-10-21*
*Last updated: 2026-10-21 after adding download filtering (FILT) and Firecracker validation (QUAR, Phase 2.1)*
