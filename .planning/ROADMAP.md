# Roadmap: flatflix

## Overview

flatflix gives a non-technical household a two-step flow on the home LAN: search and download a film or series from a phone, then find it and play it in full HD from an icon on the Hisense TV, with no video transcoding. The user chose the build order: the qBittorrent portal first (Phases 1-2), then the Jellyfin and TV groundwork (Phase 3), the hand-off between the two parts (Phase 4), the TV app (Phase 5), and finally the TV icon plus end-to-end acceptance (Phase 6). The three approved ingest warnings are scheduled as explicit work: the naming gap is decided in Phase 3 (before the parts are integrated) and implemented in Phase 4; the shared-media wiring contract starts in Phase 1 and finishes in Phase 4; the laptop port map is defined in Phase 1 and applied to Caddy and Jellyfin in Phase 3.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Portal Search & Start Download** - Log in from a phone, search films/series, start a download into the right folder; stack, port map and media contract set up (completed 2026-10-22)
- [ ] **Phase 2: Portal Download Management & Hardening** - See and cancel downloads, friendly errors, rate limiting and audit logs
- [ ] **Phase 2.1: Download Quarantine & Firecracker Validation** (INSERTED) - Completed downloads are verified with ffprobe inside a Firecracker microVM before they reach the media folders
- [ ] **Phase 3: Jellyfin Server & TV Playback Gate** - Jellyfin behind Caddy, stable LAN address, real-TV compatibility verdict, naming decision recorded
- [ ] **Phase 4: Library Hand-off** - Portal downloads appear in Jellyfin with correct names and artwork, no manual steps
- [ ] **Phase 5: TV App Browse & Play** - Remote-only TV app with Home, Library, Detail and Player at 1080p without video transcoding
- [ ] **Phase 6: TV Icon & End-to-End Acceptance** - Launch from the VIDAA home icon and prove the phone-to-TV flow for a household member

## Phase Details

### Phase 1: Portal Search & Start Download

**Goal**: A household member can log in to the portal from her phone, search for a film or series, and start a download that lands in the correct predefined folder, without ever seeing qBittorrent, save paths or credentials.
**Depends on**: Nothing (first phase)
**Requirements**: AUTH-01, SEC-01, SEC-02, SEC-03, SEC-04, SRCH-01, SRCH-02, SRCH-03, DOWN-01, DOWN-02, DOWN-03, PUI-01, PUI-02, INFRA-01, INFRA-02, MEDIA-01, FILT-01, FILT-02
**Success Criteria** (what must be TRUE):
  1. From a smartphone browser on the LAN, the user opens the portal, is asked to log in, and cannot reach search or download pages or endpoints without logging in.
  2. The user chooses Movie or TV Series, types a keyword, and sees first results in about 2 seconds with name, size, seeders, leechers and source, sorted by most seeders; a search timeout shows a plain message, not an error.
  3. Tapping Download on a result starts it in qBittorrent and, once complete, the file is in the Film or SerieTV host folder matching the chosen type, with no path or category ever shown or chosen by the user.
  4. qBittorrent is not reachable from the LAN and its credentials and paths appear in no browser response; the whole portal stack comes up with one `docker compose up` from a `.env` built from `.env.example`, and the repo holds no secrets or LAN IPs.
  5. One documented laptop port map (Caddy, portal frontend, qBittorrent WebUI if published, Jellyfin 8096) and one media-folder contract (host paths, owner IDs, separate incomplete-downloads folder) exist, and no two services collide on a port.
  6. A torrent whose file list has no allowed video file is rejected before any data is downloaded, with a plain message to the user; in an accepted torrent, executables, scripts, shortcuts, archives and every other non-video, non-subtitle file are never downloaded (qBittorrent exclusion list plus per-file priority 0).

**Plans**: 16/16 plans complete (12 waves plus 2 gap-closure waves; listed in execution order, so plan numbers are not sequential)

Plans:
**Wave 1**
- [x] 01-01-PLAN.md — Toolchain and host gate: manifests, lockfiles, package-legitimacy review, Docker Desktop WSL check (wave 1)

**Wave 2** *(blocked on Wave 1 completion)*
- [x] 01-10-PLAN.md — Tracer: pinned qBittorrent 5.2.4 in compose with env-provisioned credentials and host media folders; loopback-only admin WebUI; port map + media contract doc (wave 2)
- [x] 01-03-PLAN.md — Pure content rules, test-first: file allowlist (FILT-02) and search-result filters (SRCH-02) (wave 2)

**Wave 3** *(blocked on Wave 2 completion)*
- [x] 01-02-PLAN.md — Tracer: backend in compose logs into qBittorrent and reports /api/health; hardened client (wave 3)

**Wave 4** *(blocked on Wave 3 completion)*
- [x] 01-04-PLAN.md — Tracer: portal through Caddy on port 80; compose and repo-hygiene invariants (wave 4)

**Wave 5** *(blocked on Wave 4 completion)*
- [x] 01-05-PLAN.md — Tracer: login API with 30-day session through Caddy; deny-by-default routes; brute-force limit; hash helper (wave 5)

**Wave 6** *(blocked on Wave 5 completion)*
- [x] 01-11-PLAN.md — Tracer: English login screen and logged-in shell; expired-session handling and plain messages (wave 6)

**Wave 7** *(blocked on Wave 6 completion)*
- [x] 01-06-PLAN.md — Tracer: qBittorrent bootstrap (categories, paths, exclusions, pinned plugins, seeding limits) + doctor CLI (wave 7)

**Wave 8** *(blocked on Wave 7 completion)*
- [x] 01-07-PLAN.md — Tracer: Film/Serie search API with live filtered results; strict input, timeout, cleanup (wave 8)

**Wave 9** *(blocked on Wave 8 completion)*
- [x] 01-12-PLAN.md — Tracer: search screen with live rows; searching, empty and timeout states, row layout, badge (wave 9)

**Wave 10** *(blocked on Wave 9 completion)*
- [x] 01-08-PLAN.md — Tracer: download API with stopCondition=MetadataReceived, allowlist before start, real-engine guard (wave 10)

**Wave 11** *(blocked on Wave 10 completion)*
- [x] 01-13-PLAN.md — Tracer: Download button and row states (Started ✓, Preparing, rejection) (wave 11)

**Wave 12** *(blocked on Wave 11 completion)*
- [x] 01-09-PLAN.md — Tracer: household flow end to end with leak scan; setup guide; CLAUDE.md/REQUIREMENTS.md aligned; phone check (wave 12)

**Gap closure: UAT G-01-3, wave 1** *(after Wave 12)*
- [x] 01-14-PLAN.md — Every add carries stopCondition=MetadataReceived; plugin results that resolve to a magnet start instead of hanging in Preparing; faithful fake, four-route zero-payload tests, real-engine plugin-route test
- [x] 01-15-PLAN.md — A reload during Preparing keeps the list and the row: sessionStorage persistence in Search.jsx, cleared on new search and logout

**Gap closure: UAT G-01-3, wave 2** *(blocked on gap wave 1)*
- [x] 01-16-PLAN.md — .webm-only torrents get status unsupported and "This video format isn’t supported. Try another result."; D-13 amendment, D-23 re-affirmation and D-24 recorded; stack rebuilt and real-engine guard run

**UI hint**: yes

### Phase 2: Portal Download Management & Hardening

**Goal**: The user can follow and cancel her downloads from the phone, and the portal degrades gracefully, throttles abuse and keeps audit logs.
**Depends on**: Phase 1
**Requirements**: DOWN-04, DOWN-05, DOWN-06, SEC-05, SEC-06
**Success Criteria** (what must be TRUE):
  1. The user sees a list of her Film and SerieTV downloads, in progress and completed, with state and progress that refresh about every 5 seconds.
  2. The user can cancel a download from the list, and it also disappears from qBittorrent.
  3. When qBittorrent is down, a torrent is invalid or a category path is wrong, the user sees a plain-language message (with automatic retry when qBittorrent is unreachable), never a raw error.
  4. Rapid repeated search or download requests are throttled, and the logs record logins, searches, downloads, cancels and errors without any credentials.

**Plans**: 2/11 plans executed in 5 waves

Plans:
**Wave 1**
- [x] 02-01-PLAN.md — Tracer: GET /api/downloads lists Film/SerieTV torrents with plain state, progress, ETA, opaque ids, 7-day window, 502 codes (wave 1)
- [x] 02-02-PLAN.md — Tracer: WR-01 main-video rule (D-43) and plain outcomes for an invalid torrent (415) and a refused category path (409) (wave 1)
- [ ] 02-03-PLAN.md — Tracer: Caddy cache headers so phones pick up a redeploy (D-42); json-file log rotation on every service (D-40); smoke cache probe (wave 1)

**Wave 2** *(blocked on Wave 1 completion)*
- [ ] 02-04-PLAN.md — Tracer: failed attempts (24 h) and torrent-less Preparing jobs in the list; every download appears once (wave 2)
- [ ] 02-05-PLAN.md — Tracer: search 10/min and download 20/min per address, 429 too_many_requests; generic sliding-window limiter (wave 2)
- [ ] 02-06-PLAN.md — Tracer: Search | Downloads tabs, live list polled every 5 s while visible, outage banner, row states, ETA, styling contract (wave 2)

**Wave 3** *(blocked on Wave 2 completion)*
- [ ] 02-07-PLAN.md — Tracer: DELETE /api/downloads/{id}: cancel deletes partial files, remove keeps the film, the list's action matches what DELETE does to files, server-side checks, no ghost rows (wave 3)
- [ ] 02-08-PLAN.md — Tracer: throttled search and download taps and cancelled jobs read as plain, retryable messages on the Search screen (wave 3)

**Wave 4** *(blocked on Wave 3 completion)*
- [ ] 02-09-PLAN.md — Tracer: audit trail on stdout (logins, searches, downloads, cancels, throttles, errors) with client IP; redaction on every handler; canary test (wave 4)
- [ ] 02-10-PLAN.md — Tracer: Cancel download with one in-row confirm, Remove from list, failures and outage lock on the Downloads tab (wave 4)

**Wave 5** *(blocked on Wave 4 completion)*
- [ ] 02-11-PLAN.md — Tracer: real-engine list and cancel, live smoke downloads probe, full gate on the rebuilt stack, admin guide sections, end-of-phase phone check (wave 5)

**UI hint**: yes

### Phase 02.1: Download Quarantine & Firecracker Validation (INSERTED)

**Goal**: No downloaded file reaches the media folders (and so Jellyfin) unless a sandboxed probe proves it is a real video: completed downloads land in quarantine, ffprobe inspects each file inside a throwaway Firecracker microVM, and only passing files move on.
**Depends on**: Phase 2 (download list shows the new verifying / rejected states). Runs on the dev machine (WSL2 with `/dev/kvm`) and must run unchanged on the production Ubuntu Server box.
**Requirements**: QUAR-01, QUAR-02, QUAR-03, QUAR-04, QUAR-05
**Success Criteria** (what must be TRUE):
  1. A completed download sits in a quarantine folder that Jellyfin cannot see; nothing goes straight from qBittorrent to the Film or SerieTV media folders.
  2. Each file is probed by ffprobe inside a fresh Firecracker microVM with no network device, the file attached read-only, fixed vCPU/memory limits and a hard timeout; the VM is destroyed after every check, and a probe crash or timeout counts as a failure.
  3. A real film or episode passes (container matches extension, at least one video stream with a known codec, plausible duration and size) and moves to the media folder of its category; a renamed executable, a truncated file or a non-video file fails.
  4. A failed file never reaches the media folders (deleted, or held out of reach for the admin per the Phase 2.1 decision), its torrent is removed from qBittorrent, the user sees a plain "rejected" state in the download list, and the admin log records the reason.
  5. The microVM runner (pinned Firecracker version, guest kernel and ffprobe rootfs built by scripts in the repo, no binaries committed) is set up from documented steps on Ubuntu Server as well as on the dev machine, behind one stable interface so the sandbox can be swapped without touching the portal.

**Plans**: TBD
**UI hint**: yes

### Phase 3: Jellyfin Server & TV Playback Gate

**Goal**: Jellyfin runs on the laptop behind Caddy at a stable address, the real TV's playback behaviour is measured (go/no-go for "no video transcoding"), and the file-naming ownership decision is made on evidence, before the portal and Jellyfin are integrated.
**Depends on**: Phase 1 (port map and media contract); Phase 2 complete so the portal part is finished first
**Requirements**: JFIN-01, JFIN-02, JFIN-03, COMPAT-01, COMPAT-02, COMPAT-03, COMPAT-04, INFRA-03, INFRA-04, NAME-01
**Success Criteria** (what must be TRUE):
  1. From the TV's browser, the user opens one laptop address (Caddy) and uses the Jellyfin web UI; a library of correctly named sample films and episodes, kept in a scratch folder apart from the portal's folders, shows posters, plots, seasons and episodes.
  2. A compatibility matrix from tests on the real TV is recorded: H.264 and HEVC (including 10-bit), AAC / AC3 / EAC3 / DTS audio, SRT and embedded subtitles, each marked direct play, remux, audio-only transcode or video transcode.
  3. A go/no-go verdict is recorded from Jellyfin's admin dashboard: target 1080p content never needs video transcoding on this TV, or a mitigation (re-encode, plan B stick, stronger hardware) is chosen.
  4. After a laptop or router restart the TV still reaches the same address, and Caddy, Jellyfin and the portal run on the documented port map with no collisions.
  5. The naming decision (who puts downloads into Jellyfin's layout) is recorded in PROJECT.md Key Decisions, backed by a scan test with raw torrent-style names.

**Plans**: TBD

### Phase 4: Library Hand-off

**Goal**: A film or series episode downloaded through the portal shows up in Jellyfin with the right title and artwork, with no manual step by the household or the admin.
**Depends on**: Phase 2.1 (only validated files are handed off; renaming slots into the move step after validation), Phase 3 (naming decision recorded). Independent of Phase 5, which can run before or after it.
**Requirements**: NAME-02, NAME-03, NAME-04, MEDIA-02, MEDIA-03
**Success Criteria** (what must be TRUE):
  1. A film downloaded through the portal ends up as `Title (Year)/Title (Year).<ext>` and appears in Jellyfin's Film library with poster and plot.
  2. A series episode downloaded through the portal ends up as `Series/Season 01/Series S01E01.<ext>` and appears under the right season in Jellyfin's SerieTV library.
  3. A download still in progress does not appear in Jellyfin; once it completes, it appears within the stated refresh time with no admin action.
  4. A download that cannot be identified is not lost or mis-filed: it stays in an unsorted place and is flagged in the logs for the admin.
  5. Jellyfin reads the media folders read-only (it cannot change or delete downloads) and shows no permission errors in its logs.

**Plans**: TBD

### Phase 5: TV App Browse & Play

**Goal**: A household member can browse the library and play a film or episode on the TV using only the remote, at 1080p or better with original video quality.
**Depends on**: Phase 3 (compatibility gate passed or mitigation chosen; Caddy single origin)
**Requirements**: TV-01, TV-02, TV-03, TV-04, TV-05, TV-06, TV-07, PLAY-01, PLAY-02, PLAY-03, PLAY-04
**Success Criteria** (what must be TRUE):
  1. On the real TV, using only arrows, OK and Back, the user moves through Home (Continue watching), Library poster grids and Detail screens (plot, seasons, episodes, watched marks); Back works on every screen and focus is never trapped.
  2. The transpiled build loads on the VIDAA browser with no blank page or script errors, poster-grid scrolling stays smooth with reduced-size images, and the framework choice (Preact or SolidJS) is recorded from the TV prototype.
  3. Pressing OK on a film or episode starts full-screen playback at 1080p or better; Jellyfin's dashboard shows direct play, remux or audio-only transcode, never video transcode; Play/Pause and seeking work from the remote and subtitles can be switched on.
  4. Leaving a title mid-playback makes it appear in Continue watching at the right position, and finishing it marks it watched.
  5. With the laptop off or unreachable, the app shows a clear "server unreachable" screen instead of a blank or hung page.

**Plans**: TBD
**UI hint**: yes

### Phase 6: TV Icon & End-to-End Acceptance

**Goal**: The app launches from an icon on the VIDAA home, and a non-technical household member completes the whole phone-to-TV flow; the stack is reproducible from the repo.
**Depends on**: Phase 4, Phase 5
**Requirements**: LAUNCH-01, LAUNCH-02, ACPT-01, ACPT-02, INFRA-05
**Success Criteria** (what must be TRUE):
  1. An icon on the VIDAA home opens the app full screen with no browser UI and still works after a TV restart; if the community tool is not viable, plan B is chosen and recorded.
  2. A household member, with only a phone, logs into the portal, searches and starts a film download; later, with only the TV remote from the icon, she finds the film and plays it at 1080p or better with no video transcoding.
  3. The same flow works for a series episode, which appears under the right season.
  4. On a fresh machine, documented steps plus a `.env` built from `.env.example` bring up the whole stack, and moving machines changes only the host address; the repo contains no secrets or LAN IPs.

**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 2.1 → 3 → 4 → 5 → 6 (Phases 4 and 5 are independent and may be swapped)

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Portal Search & Start Download | 16/16 | Complete    | 2026-10-22 |
| 2. Portal Download Management & Hardening | 2/11 | In Progress | - |
| 2.1 Download Quarantine & Firecracker Validation | 0/TBD | Not started | - |
| 3. Jellyfin Server & TV Playback Gate | 0/TBD | Not started | - |
| 4. Library Hand-off | 0/TBD | Not started | - |
| 5. TV App Browse & Play | 0/TBD | Not started | - |
| 6. TV Icon & End-to-End Acceptance | 0/TBD | Not started | - |

## Ingest Conflict Resolution

The three warnings from `.planning/INGEST-CONFLICTS.md` were approved by the user and are scheduled as roadmap work, not silently resolved.

| Warning | What must be settled | Decided / defined in | Implemented / applied in |
|---------|----------------------|----------------------|--------------------------|
| W1 Naming gap (torrent names vs Jellyfin layout) | Who renames or organizes downloads: portal post-download step, external library manager, or relaxed requirement | Phase 3 (NAME-01), before the parts are integrated | Phase 4 (NAME-02, NAME-03, NAME-04) |
| W2 Shared media wiring | Host paths, owner IDs, incomplete-downloads folder, read-only Jellyfin mounts, two libraries, rescan trigger | Phase 1 (MEDIA-01) for the qBittorrent side | Phase 4 (MEDIA-02, MEDIA-03) for the Jellyfin side |
| W3 Port 8080 ambiguity, Caddy port undefined | One laptop port map; shared Docker network; whether Caddy fronts the portal | Phase 1 (INFRA-02) | Phase 3 (INFRA-03) |

## Open Decisions by Phase

| Decision | Resolved in |
|----------|-------------|
| Portal backend stack (FastAPI or Node) | Phase 1 |
| Naming ownership (W1) | Phase 3 |
| One shared Jellyfin user or separate profiles; default audio/subtitle language | Phase 3 |
| Whether Caddy also fronts the portal | Phase 3 |
| Rescan trigger mechanism (Jellyfin API call, scheduled scan, or folder watch) | Phase 4 |
| TV framework (Preact or SolidJS) and Jellyfin auth method (login or API key) | Phase 5 |
| Plan A or plan B for the TV icon | Phase 6 |
| Allowed extensions and plausibility thresholds (min duration/size per type) | Phase 1 (extensions), Phase 2.1 (thresholds) |
| Fate of rejected files: delete at once or keep briefly for the admin | Phase 2.1 |
| Exact production box model (x86_64 with VT-x and KVM, Ubuntu Server) | Before Phase 6; must run Firecracker |
| Access from outside home | After Phase 6 (v2) |
