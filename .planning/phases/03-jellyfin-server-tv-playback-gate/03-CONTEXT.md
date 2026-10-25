# Phase 3: Jellyfin Server & TV Playback Gate - Context

**Gathered:** 2026-10-25
**Status:** Ready for planning

<domain>
## Phase Boundary

Jellyfin runs in Docker on the dev laptop behind Caddy at one stable LAN address, with a scratch library of correctly named open content (posters, plots, seasons, episodes). The real Hisense TV (VIDAA, firmware V0003.09.60A.Q0707) is tested through Jellyfin's own web UI to produce a codec compatibility matrix and a go/no-go verdict on "no video transcoding". The naming-ownership decision (NAME-01) is made from a scan test with raw torrent-style names and recorded in PROJECT.md. Requirements: JFIN-01..03, COMPAT-01..04, INFRA-03, INFRA-04, NAME-01.

Not in this phase: the portal → Jellyfin hand-off and any rename code (Phase 4), the custom TV app and its device profile (Phase 5), the VIDAA icon (Phase 6). Jellyfin does not mount the portal's `media` folders yet (Phase 4); it scans only the scratch library.

</domain>

<decisions>
## Implementation Decisions

### Address and routing
- **D-80:** Jellyfin is served at the **`/jellyfin` subpath** of the single Caddy origin (port 80), replacing the reserved `handle /jellyfin/*` stub. Jellyfin's **BaseURL is `/jellyfin`**. The Phase 5 TV app at `/tv` will call it same-origin. — **Reversibility:** costly — the BaseURL is stored in Jellyfin config, and the TV app (Phase 5) and household bookmarks will use the path.
- **D-81:** Preferred household address is an **mDNS `.local` name** (e.g. `flatflix.local`), **if the VIDAA browser resolves it**. This must be tested on the real TV in this phase, and the result recorded. A **DHCP reservation + raw IP stays as the fallback** in every case (INFRA-04 still delivered). Research must cover how the name is advertised on both hosts: Windows host under WSL2/Docker Desktop (dev) and avahi on Ubuntu Server (prod).
- **D-82:** The Jellyfin admin dashboard is reached **through Caddy only** (`/jellyfin` with the admin account). Port 8096 stays unpublished; no admin-override entry for Jellyfin.
- **D-83:** The real-TV tests run on the **dev laptop** (WSL2 + Docker Desktop, same port forwarding as the portal). The verdict is about client decoding, so it carries to the production box.

### Compatibility test media and matrix
- **D-84:** Test files come from **both** sources: (a) a committed script that generates short clips with ffmpeg from the Blender open movies, one per codec combination (H.264, HEVC 8-bit and 10-bit; AAC, AC3, EAC3, DTS; SRT, embedded ASS, PGS; MKV and MP4 containers), and (b) a few public real-release-like sample files as a sanity check. No copyrighted content; generated and downloaded media is never committed.
- **D-85:** **1080p rows decide go/no-go.** A few **4K / HDR10 rows are recorded for information only** (many torrents are 2160p).
- **D-86:** **PGS (image) subtitles are tested but do not gate.** The verdict counts with subtitles off or text subtitles (SRT/ASS). If PGS forces burn-in, it is noted so Phase 5 can prefer text subs.
- **D-87:** The mitigation (re-encode, plan B HDMI stick, stronger hardware) is chosen **on evidence**, after the matrix exists. No pre-committed preference. Audio-only transcode already counts as acceptable (PLAY-02).
- **D-88:** The real-TV session uses a **helper script**: the user presses play on each clip from the TV's browser. The script polls Jellyfin's Sessions API and writes the play method (direct play / direct stream-remux / transcode) and the transcode reasons into the matrix. The user only confirms "picture and sound OK".
- **D-89:** The matrix and verdict go into a **committed doc, `docs/tv-compatibility.md`**, linked from PROJECT.md. It records the TV firmware version only: **never the serial number, device ID or Netflix ESN** (public repo). Phase 5 builds its device profile from this doc.

### Naming decision (NAME-01)
- **D-90:** The user's **lean is a portal rename step**: after the safety check, the backend parses the torrent name and names the media hardlink `Title (Year)/Title (Year).<ext>` or `Series/Season NN/Series SNNEMM.<ext>`, which fits D-46. The scan test still runs and can overturn the lean. The decision is recorded in PROJECT.md Key Decisions. Implementation stays in Phase 4.
- **D-91:** Scan-test corpus: **~30 real film and series names captured from real portal search results**, as tiny generated clips under those names, in the scratch folder. Names only, no copyrighted content. If the captured names are committed as a fixture, check them for anything sensitive first.
- **D-92:** Bar for adopting **relaxed naming** (Jellyfin parses raw names itself): **≥ 90 % correctly identified, the rest unidentified/flagged, and zero matches to the wrong title**. Below the bar, the rename step wins.
- **D-93:** An online **TMDB lookup by the portal backend is allowed, with an opt-in API key** in `.env` (empty = offline parsing only). It needs Internet egress from the backend; the key is never committed. Whether Phase 4 uses it depends on the scan-test result.

### Household user, language, network
- **D-94:** **One shared household Jellyfin user with a password** (from `.env`, never committed), separate from the admin account. Separate profiles stay out of scope (PROF-01). The Phase 5 app's login method (user login vs API key, TV-06) is decided there.
- **D-95:** Default **audio language English, otherwise the file's default track**. Subtitles **Smart mode, English**: English subs only when the audio isn't English; forced subs always show.
- **D-96:** The TV is on **Ethernet**. The maximum streaming bitrate (JFIN-03) is set from a measured LAN throughput with headroom for 1080p remuxes; the exact value is Claude's discretion.

### Sample library
- **D-97:** The scratch library has the **Blender open movies as films** and a **real Creative Commons series that exists on TMDB** (e.g. Pioneer One) as the series, so posters, seasons and episode plots are real. The scratch folder lives apart from `DATA_ROOT/media` and is never part of the portal's folders.

### Claude's Discretion
- **Jellyfin image**: linuxserver/jellyfin (PUID/PGID convention like qBittorrent) or official jellyfin/jellyfin. Either way pinned to an exact version, never `latest` (D-22 spirit), running as `PUID:PGID`.
- Exact mDNS name and the advertising mechanism per host.
- Bitrate cap value (D-96).
- The precise ffmpeg clip list and durations, and which public sample files are used.
- Whether Jellyfin joins the existing compose project (expected, per INFRA-03) and its network: Caddy must reach it, the backend need not.
- Exact rows of the 4K/HDR information section.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements and roadmap
- `.planning/REQUIREMENTS.md` — JFIN-01..03, COMPAT-01..04, INFRA-03, INFRA-04, NAME-01; PROF-01 (out of scope)
- `.planning/ROADMAP.md` §"Phase 3" — goal and 5 success criteria; §"Phase 4" and §"Phase 5" for what consumes this phase's outputs
- `.planning/PROJECT.md` — Key Decisions table (W1 naming row to resolve; shared user / default language rows to resolve; production box row informed by the gate)

### Home-theater design
- `home-theater.md` — architecture (Caddy single origin), Jellyfin setup, compatibility test plan, network notes, open decisions, risks

### Ports, media and infra
- `docs/ports-and-media.md` — port map (Jellyfin 8096 reserved, never published; only web on the LAN), networks, media contract (`DATA_ROOT`, `PUID:PGID`)
- `docs/setup.md` — admin guide; gets Jellyfin, DHCP reservation and mDNS steps
- `web/Caddyfile` — single origin; `/jellyfin/*` stub to replace
- `docker-compose.yml`, `docker-compose.admin.yml` — services and networks
- `infra/tests/test_compose_invariants.py` — port/network invariants (already rejects 8096 for the qBittorrent WebUI); new Jellyfin invariants go here

### Prior phase decisions
- `.planning/phases/01-portal-search-start-download/01-CONTEXT.md` — D-03..D-05 (Caddy, port 80, path split), D-22 (pinned images)
- `.planning/phases/02.1-download-quarantine-firecracker-validation/02.1-CONTEXT.md` — D-44 (DATA_ROOT, Jellyfin mounts only `media` read-only), D-46 (hardlink hand-off, Phase 4 renames the link)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `scripts/make_probe_fixtures.py`: already generates video fixtures with ffmpeg; a starting point for the D-84 clip generator.
- `scripts/smoke.py`: end-to-end probe that downloads only Blender open movies; same legal-content source for samples.
- `backend/app/tools/doctor.py`: admin health tool; can gain a Jellyfin reachability check.
- `scripts/init-host-dirs.sh`: creates host folders with `PUID:PGID`; extend for Jellyfin config/cache and the scratch library.

### Established Patterns
- `web/Caddyfile` sets a strict site-wide CSP (`default-src 'self'`, no inline styles) and `X-Frame-Options DENY`. Jellyfin's web UI likely needs a looser policy under `/jellyfin/*` (inline styles/scripts, `blob:` media, workers). Research must define a per-route header policy without weakening the portal's.
- Only `web` publishes a port; everything else is reachable on internal networks (`edge`, `qbit`, `sandbox`). Invariants in `infra/tests` enforce this.
- Images are pinned to exact versions; secrets come from `.env` generated by `scripts/dev_env.py`, with placeholders in `.env.example`.

### Integration Points
- Caddy `handle /jellyfin/*` → `reverse_proxy jellyfin:8096` (no path stripping when the BaseURL is `/jellyfin`; websockets for the web UI).
- New Jellyfin volumes: config, cache, scratch library (read-only). The `media` mount comes in Phase 4.
- `.env` / `scripts/dev_env.py`: household user password, optional `TMDB_API_KEY` (D-93, used from Phase 4).

</code_context>

<specifics>
## Specific Ideas

- TV: Hisense on VIDAA, firmware **V0003.09.60A.Q0707** (from the TV's Information screen). Connected by Ethernet.
- The user wants mDNS if the TV can resolve it; prove it on the TV before relying on it.
- The household includes an English speaker; English is the default audio/subtitle language.

</specifics>

<deferred>
## Deferred Ideas

None. The discussion stayed within phase scope.

</deferred>

---

*Phase: 03-jellyfin-server-tv-playback-gate*
*Context gathered: 2026-10-25*
