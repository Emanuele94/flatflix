# Phase 3: Jellyfin Server & TV Playback Gate - Research

**Researched:** 2026-10-25
**Domain:** Dockerized Jellyfin 12.x behind a Caddy subpath, real-TV codec gate on a Hisense VIDAA browser, Jellyfin naming/scan behaviour
**Confidence:** HIGH for the Jellyfin/Caddy/CSP mechanics (all reproduced in a local run this session); MEDIUM for TV-side behaviour (needs the real TV); LOW for `.local` name resolution on VIDAA and Windows (no source found, must be tested)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

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
- **D-92:** Bar for adopting **relaxed naming** (Jellyfin parses raw names itself): **>= 90 % correctly identified, the rest unidentified/flagged, and zero matches to the wrong title**. Below the bar, the rename step wins.
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

### Deferred Ideas (OUT OF SCOPE)
None. The discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| JFIN-01 | Jellyfin in Docker with persistent config/cache/media volumes, household user, default audio/subtitle language | Official image `jellyfin/jellyfin:12.3.20261023-013714`, hardened compose service (verified), headless wizard + user API flow (verified), `/Users/Configuration` language fields (verified) |
| JFIN-02 | Scanning correctly named sample content gives posters, plots, seasons, episodes stored locally | Library API call and scan polling (verified); TMDb works from the container; `SaveLocalMetadata=false` on a read-only mount (verified); Pioneer One and Blender titles identified |
| JFIN-03 | Maximum streaming bitrate suited to the home network | `ServerConfiguration.RemoteClientBitrateLimit` exists but binds only non-local clients (source read); TV bound by the client-side setting; measurement and verification recipe |
| COMPAT-01 | H.264 / HEVC (incl. 10-bit) tested on real TV, play method recorded | Clip generator commands (verified with host ffmpeg 6.1.1), helper design with two independent play-method signals, stock web client profile facts (`browser.vidaa` source) |
| COMPAT-02 | AAC / AC3 / EAC3 / DTS tested, method recorded | Same generator; DTS needs `-strict -2` (verified); stock web client `canPlayDts` logic |
| COMPAT-03 | SRT and embedded subtitles tested | SRT/mov_text/ASS encodable; PGS has no ffmpeg encoder (verified); CSP must allow `'wasm-unsafe-eval'` or ASS/PGS rendering breaks (verified) |
| COMPAT-04 | Dashboard check and go/no-go verdict recorded | Dashboard paths verified; ffmpeg log prefix `Remux` / `DirectStream` / `Transcode` as server-side ground truth (verified); verdict template from UI-SPEC |
| INFRA-03 | Caddy and Jellyfin on the port map, shared network/project, TV reaches Jellyfin only through Caddy | New `jellyfin` network shared by `web` and `jellyfin` only; Caddyfile route verified incl. CSP, redirect, 502 text, WebSocket 101 |
| INFRA-04 | DHCP reservation keeps the laptop on the same address | Doc-only; Windows/WSL2 pitfalls (sign-in start of Docker Desktop, MAC randomization, sleep); mDNS options per host |
| NAME-01 | Naming ownership decided from a scan test with raw torrent-style names | Scan-test harness design, poll protocol, early evidence (1 wrong title in 16 raw names, flat episode files unidentified) |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- English only: UI, code, docs, `.planning/`. [VERIFIED: /home/emanuele/projects/flatflix/CLAUDE.md "The whole project (UI, code, docs) is English only"]
- Public MIT repo: no secrets, LAN IPs or real credentials in commits; write `<laptop-ip>`; `infra/tests/test_repo_hygiene.py` scans for private addresses and argon2/qBittorrent hashes. [VERIFIED: infra/tests/test_repo_hygiene.py]
- Backend of the home theater is **stock Jellyfin: configure it, write no server code**. Caddy serves one origin and reverse-proxies Jellyfin, so no CORS. [VERIFIED: CLAUDE.md]
- Pure web app, no VIDAA-specific APIs (plan B APK must stay possible). Phase 3 writes no custom frontend code (UI-SPEC scope statement).
- Images pinned to exact versions, never `latest` (`test_images_are_pinned_and_compose_is_versionless`). Only `web` publishes a port (`test_only_web_publishes_a_port`).
- Commands from the repo root: `uv run --project backend --frozen pytest infra/tests -q`, `... pytest backend/tests -q`, `docker compose up -d --build --wait`.
- This laptop (WSL2, `/dev/kvm`) is the dev machine only; production is a KVM-capable x86_64 Ubuntu Server box. Anything host-specific must work on both.
- User global style: the plan and docs written for the user should lead with the action, number steps, one bounded action per step.

## Summary

Jellyfin 12.3.0 (released 2026-10-23) runs fine as a pinned official image under the existing compose project, with BaseURL `/jellyfin` pre-seeded in `config/config/network.xml` before first start, a non-published port, and the same hardening the sandbox uses (`read_only`, `cap_drop: [ALL]`, `no-new-privileges`, tmpfs `/tmp`). I ran this stack locally (Jellyfin + Caddy 2.11.7, a real headless Chromium, a real TMDb scan from inside the container) and reproduced every mechanic the plan depends on: the headless setup wizard, user and library creation by API, the Caddy route with a CSP carve-out, the 502 text, WebSocket upgrade, no compression of video or images, and ffmpeg remux / audio-only / video transcode paths under the hardened container.

Four findings change the UI-SPEC or CONTEXT assumptions and the planner must act on them. (1) **Caddy's site-level `header` overrides a route-level `header`** (outer wins), so a per-route CSP override silently fails; the portal CSP must be scoped with a `not path` matcher instead. (2) **Jellyfin sends no CSP of its own**, so there is no "documented default" to start from, and the UI-SPEC starting policy **blocks WebAssembly**: `libass-wasm` (ASS) and `libbitsub` (PGS) need `'wasm-unsafe-eval'` in `script-src`; without it ASS/PGS rendering breaks and the server may fall back to burn-in, which would fake a "video transcode" NO-GO. (3) **Stock Jellyfin 12 ships TMDb and OMDb only** (no TVmaze/TVDb), and **new users are hidden from login screens by default**; the household user must be explicitly un-hidden or the TV shows no tile. (4) **The stock web client profile is not the TV's capability**: for VIDAA it never direct-plays MKV (`testCanPlayMkv` returns false), so MKV rows will be "Remux" by construction; the matrix measures "what Jellyfin's web client gets", a conservative floor for Phase 5's own profile.

The naming scan test already points the same way as the user's lean: in a 16-name pilot of raw torrent-style names, 15 were identified but **`Blade.Runner.2049.2017...` matched "Blade Runner (1982)"** (a wrong title, which alone fails D-92's zero-wrong bar) and flat single-episode files (`Show.S02E03...mkv`) were never attached to a series. The formal 30-name test must still be run and recorded.

**Primary recommendation:** Use official `jellyfin/jellyfin:12.3.20261023-013714` on a new non-internal `jellyfin` network shared only with `web`; pre-seed BaseURL; provision everything with one idempotent stdlib script (`scripts/jellyfin_setup.py`) against `http://127.0.0.1/jellyfin`; scope the portal CSP with `@notjellyfin not path /jellyfin /jellyfin/*` and give `/jellyfin/*` a policy that includes `'wasm-unsafe-eval'`; classify play methods from Sessions `TranscodingInfo` plus the `FFmpeg.<Remux|DirectStream|Transcode>` log prefix, not from the client-reported `PlayMethod` alone.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Single stable address (IP + optional `.local`) | Host network (router DHCP reservation, host mDNS responder) | Caddy `:80` accepts any Host | The address is a property of the host, not of any container; Caddy needs no Host matching |
| `/jellyfin` routing, per-route CSP, 502 text | CDN / Static tier = Caddy `web` | - | Caddy is the only published service (D-04) |
| Media server, metadata scan, playback decision | API / Backend = Jellyfin | - | Stock server, no custom code |
| Codec decode, container support | Browser / Client = VIDAA browser | Jellyfin web client profile | The TV decodes; the stock web client only decides what to request |
| Transcode decision evidence | API / Backend = Jellyfin (Sessions API, ffmpeg logs) | Host helper script | Server-side signals are the ground truth, the client only reports |
| Provisioning (users, libraries, language, bitrate) | Host script calling Jellyfin API through Caddy | - | D-82: admin only through Caddy; no 8096 override |
| Naming decision evidence | Host script + Jellyfin scan | - | Scan test reads Jellyfin's Items API against a hand-labelled truth table |
| Persistence (config, cache, scratch media) | Host bind mounts | - | `./jellyfin/{config,cache,scratch}` owned by `PUID:PGID` |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `jellyfin/jellyfin` (Docker Hub) | `12.3.20261023-013714` (server 12.3.0, ffmpeg 8.1.3-Jellyfin) | Media server | [VERIFIED: Docker Hub tags API 2026-10-25; `docker run` this session printed `"Version":"12.3.0"`]. Official image, immutable dated tag exists next to the floating `12.3`. Manifest digest seen on pull: `sha256:2038fe038ab3876a80f6e7b7e0aef6607b032c7dc0c9b3ad3296d0b2eba3bbb5` |
| `caddy` | `2.11.7-alpine` (already pinned in `web/Dockerfile`) | Reverse proxy | [VERIFIED: web/Dockerfile `FROM caddy:2.11.7-alpine`]; all route tests below ran on this exact tag |
| Python 3.12 stdlib (`urllib`, `json`, `argparse`) | repo `requires-python >=3.12,<3.13` | Setup, clip, gate and scan scripts | Matches `scripts/smoke.py` and `scripts/make_probe_fixtures.py` (stdlib only, argument lists, no shell) |
| Host `ffmpeg`/`ffprobe` | 6.1.1-3ubuntu5 on the dev box | Clip generator | [VERIFIED: `ffmpeg -version`, encoders `libx264 libx265 aac ac3 eac3 dca(experimental) srt ass mov_text` present; clips encoded this session] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pytest` 9.1.1, `pyyaml` 6.0.3 | already locked in `backend/pyproject.toml` | Compose/Caddyfile/doc invariants in `infra/tests`, script contract tests in `backend/tests` | Every new test; no new dependency |
| Jellyfin test videos | `https://repo.jellyfin.org/test-videos/` (SDR AVC / HEVC 10bit / HDR10, 1080p 3-30M, 4K 40-150M, `.sha256sum` sidecars) | Public sanity-check and 4K/HDR10 information rows | D-84(b), D-85. [VERIFIED: directory listing and `HTTP 200`, 111 MB file, this session] |
| Blender open movies | Sintel 1080p MKV `https://download.blender.org/durian/movies/Sintel.2010.1080p.mkv` (1.18 GB; H.264 High, AC3 5.1, 10 embedded SRT tracks); BBB 1080p `.../demo/movies/BBB/bbb_sunflower_1080p_30fps_normal.mp4.zip` (275 MB); Tears of Steel 720p `.../demo/movies/ToS/tears_of_steel_720p.mov` (372 MB) | Clip source (cut 60-90 s) and the "real release" sample | [VERIFIED: HEAD 200 and `ffprobe` of the first 3 MB of the Sintel file] |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Official `jellyfin/jellyfin` | `lscr.io/linuxserver/jellyfin:12.3ubu2604-ls56` | LSIO matches qBittorrent's PUID/PGID convention but adds an s6 init and runs as root first; the official image takes `user:` directly, supports `read_only` (verified), and is what `home-theater.md` names. Choose official. |
| Own `jellyfin` network | Put Jellyfin on `edge` | `edge` would let the backend reach Jellyfin and Jellyfin reach the backend. New network keeps `web`+`jellyfin` only; cost is one changed assertion in `test_qbittorrent_and_web_share_no_network` (`web` becomes `{"edge","jellyfin"}`). Phase 4 adds `backend` to it if the backend must call Jellyfin. |
| `zeroconf` (Python) on the Windows host to publish `flatflix.local` | Rename the Windows PC, Apple Bonjour `dns-sd`, router DNS entry | See mDNS section; none is verified for VIDAA. Only needed if the TV resolves `.local` at all. |

**Installation:** no new packages for the core of this phase. Images only:
```bash
docker pull jellyfin/jellyfin:12.3.20261023-013714
```

**Version verification:** [VERIFIED: GitHub releases API] `v12.3` 2026-10-23, `v12.2` 2026-10-05, `v12.1` 2026-09-15, `v12.0` 2026-09-08; Docker Hub shows `12.3.20261023-013714`. 12.0 is a new major (database migrations, no rollback without restore); a fresh install is unaffected.

## Package Legitimacy Audit

Core stack installs no PyPI/npm package. Two packages are mentioned as options only.

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| zeroconf | PyPI | latest release 2026-09-28 (project old) | unknown to seam | none reported by seam | [SUS] (`too-new`, `unknown-downloads`, `no-repository`; seam heuristics, the project is the long-standing python-zeroconf) | Optional, only for the Windows `.local` publisher. Name from training memory, `[ASSUMED]`. Planner must add `checkpoint:human-verify` before installing |
| guessit | PyPI | latest release 2026-07-31 | unknown to seam | `https://guessit-io.github.io/guessit` | [SUS] (`unknown-downloads`) | Phase 4 candidate for the rename parser, not installed in Phase 3. `[ASSUMED]`; evaluate in Phase 4 research |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** zeroconf, guessit (both optional, neither required by any Phase 3 requirement)

*Evidence source: `gsd_run query package-legitimacy check --ecosystem pypi zeroconf guessit`, 2026-10-25.*

## Architecture Patterns

### System Architecture Diagram

```
 TV browser (VIDAA) / PC browser / phone
        |  http://flatflix.local/jellyfin   or   http://<laptop-ip>/jellyfin
        v
 [host network]  router DHCP reservation (by MAC)  +  mDNS responder (optional)
        |  host port 80  (Docker Desktop publishes on Windows; Ubuntu: docker-proxy)
        v
 +---------------------------- compose project "flatflix" ----------------------------+
 |  web (Caddy 2.11.7)  networks: edge, jellyfin                                       |
 |   |  header CSP (portal)  -> only when path NOT /jellyfin*                          |
 |   |  /jellyfin            -> redir 308 /jellyfin/                                   |
 |   |  /jellyfin/*          -> own CSP + reverse_proxy jellyfin:8096 (+ WebSocket)    |
 |   |  /api/*  -> backend:8000   /tv/* (reserved)   /assets/*, SPA fallback           |
 |   |  handle_errors /jellyfin* -> "Jellyfin is not available right now..." (502/503) |
 |   v                                                                                 |
 |  jellyfin (official image, user PUID:PGID, read_only, cap_drop ALL)  network: jellyfin
 |     /config  <- ./jellyfin/config   (network.xml BaseUrl=/jellyfin seeded)          |
 |     /cache   <- ./jellyfin/cache    (HLS transcodes)                                |
 |     /scratch <- ./jellyfin/scratch  (read-only: Movies, TV, Compat, Raw)            |
 |     egress to TMDb (non-internal network)                                           |
 |  backend / qbittorrent / sandbox: unchanged, NOT on `jellyfin`                      |
 +-------------------------------------------------------------------------------------+
        ^                                   ^
        | host scripts via http://127.0.0.1/jellyfin (Caddy only, D-82)
 scripts/jellyfin_setup.py   : wizard, users, libraries, language, bitrate (idempotent)
 scripts/make_compat_clips.py: ffmpeg clips from Blender sources -> jellyfin/scratch/Compat
 scripts/tv_gate.py          : poll /Sessions + read jellyfin/config/log/FFmpeg.*.log
                               -> jellyfin/tv-gate/results.json -> docs/tv-compatibility.md
 scripts/name_scan.py        : corpus -> clips in scratch/Raw -> scan -> Items API
                               -> table + D-92 verdict
```

### Recommended Project Structure
```
jellyfin/                    # gitignored entirely (config holds the DB and tokens)
├── config/config/network.xml   # seeded by init-host-dirs.sh, never overwritten
├── cache/
├── scratch/{Movies,TV,Compat,Raw}/
└── tv-gate/results.json
scripts/
├── jellyfin_setup.py   make_compat_clips.py   tv_gate.py   name_scan.py
docs/tv-compatibility.md   docs/setup.md (+ "Jellyfin and the TV")   docs/ports-and-media.md (Jellyfin row)
infra/tests/test_compose_invariants.py (extended)   infra/tests/test_caddyfile.py (new)   infra/tests/test_docs_contract.py (new)
backend/tests/test_jellyfin_scripts_contract.py (new; loads scripts by path like test_smoke_contract.py)
```

### Pattern 1: Compose service (verified flags)
**What:** official image, non-root, read-only root, no capabilities, own network, healthcheck on the BaseURL path.
**When to use:** the `jellyfin` service in `docker-compose.yml`.
```yaml
  jellyfin:
    image: jellyfin/jellyfin:12.3.20261023-013714
    user: "${PUID:-1000}:${PGID:-1000}"
    read_only: true
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
    pids_limit: 512
    tmpfs: ["/tmp:size=64m"]
    environment:
      TZ: ${TZ:-Etc/UTC}
      # The image's own healthcheck reads this; the default has no /jellyfin prefix.
      HEALTHCHECK_URL: http://localhost:8096/jellyfin/health
    volumes:
      - {type: bind, source: ./jellyfin/config,  target: /config,  bind: {create_host_path: false}}
      - {type: bind, source: ./jellyfin/cache,   target: /cache,   bind: {create_host_path: false}}
      - {type: bind, source: ./jellyfin/scratch, target: /scratch, read_only: true, bind: {create_host_path: false}}
    networks: [jellyfin]
    healthcheck:
      test: ["CMD-SHELL", "curl --noproxy localhost -fsS http://localhost:8096/jellyfin/health || exit 1"]
      interval: 15s
      timeout: 5s
      retries: 6
      start_period: 60s
    restart: unless-stopped
    logging: *default-logging
# web: networks: [edge, jellyfin]      networks: jellyfin: {}   (not internal: TMDb egress)
```
Source: container run with `--user 1000:1000 --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges:true --pids-limit 512` started healthy, served the API, and ran `FFmpeg.Remux`, `FFmpeg.DirectStream` and `FFmpeg.Transcode` jobs. [VERIFIED: local run 2026-10-25] Image `curl` exists and `HEALTHCHECK_URL` is in the image env [VERIFIED: `docker image inspect`]. Do **not** make `web` `depends_on` Jellyfin: Caddy dials `jellyfin` lazily, and the portal must not depend on Jellyfin starting.

### Pattern 2: BaseURL pre-seed (first boot already under `/jellyfin`)
`JELLYFIN_CONFIG_DIR=/config/config` in the image, so the file is `./jellyfin/config/config/network.xml`. [VERIFIED: `docker image inspect` env + run]
```xml
<?xml version="1.0" encoding="utf-8"?>
<NetworkConfiguration xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">
  <BaseUrl>/jellyfin</BaseUrl>
</NetworkConfiguration>
```
After first start Jellyfin rewrote it with all defaults and kept `BaseUrl=/jellyfin`; `GET /jellyfin/health` answered `Healthy`, `GET /` and `GET /jellyfin` answer `302 Location: jellyfin/web/` (relative, resolves correctly). [VERIFIED: local run] `scripts/init-host-dirs.sh` must create the file **only when absent**, owned `PUID:PGID`.

### Pattern 3: Caddyfile (verified end to end)
Site-level `header` keeps the shared headers; the portal CSP is scoped by matcher; the Jellyfin route carries its own CSP; errors are handled at site level.
```caddy
	@notjellyfin not path /jellyfin /jellyfin/*

	header {
		X-Content-Type-Options nosniff
		Referrer-Policy no-referrer
		X-Frame-Options DENY
		-Server
	}
	# Byte-for-byte the existing portal policy, now scoped (see Pitfall 1).
	header @notjellyfin Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"

	redir /jellyfin /jellyfin/ 308

	handle /jellyfin/* {
		header Content-Security-Policy "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self' ws: wss:; font-src 'self' data:; worker-src 'self' blob:; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
		reverse_proxy jellyfin:8096
	}

	handle_errors {
		@jellyfin_down path /jellyfin /jellyfin/*
		respond @jellyfin_down "Jellyfin is not available right now. Ask the admin to check the server." {http.error.status_code}
	}
```
Results [VERIFIED: caddy 2.11.7 + jellyfin 12.3 locally]: exactly one `Content-Security-Policy` header on `/jellyfin/web/index.html` (the Jellyfin one); `/` and `/api/*` still carry the portal policy; bare `/jellyfin` answers `308 Location: /jellyfin/`; with Jellyfin stopped, `/jellyfin/web/index.html` answers `502` with the exact UI-SPEC sentence; WebSocket `GET /jellyfin/socket?ApiKey=<token>` answers `101 Switching Protocols`; `Accept-Encoding: gzip, zstd` on `Videos/<id>/stream` (`video/x-matroska`, including a `Range` request answered `206`) and on a poster (`image/jpeg`) came back **without** `Content-Encoding`, while `application/json` was gzipped. The existing line `header_up X-Forwarded-For {remote_host}` stays on `/api/*` only; Caddy's default `reverse_proxy` replaces client-sent `X-Forwarded-*`, so nothing extra is needed for Jellyfin.

### Pattern 4: Headless provisioning against the live API (verified)
Order that worked on a fresh server, all unauthenticated until the wizard completes:
`POST /Startup/Configuration {"ServerName":"Flatflix","UICulture":"en-US","MetadataCountryCode":"US","PreferredMetadataLanguage":"en"}` -> 204; `GET /Startup/User` (must be called, it returns the placeholder name) then `POST /Startup/User {"Name","Password"}` -> 204; `POST /Startup/RemoteAccess {"EnableRemoteAccess":true}` -> 204; `POST /Startup/Complete` -> 204. Then `POST /Users/AuthenticateByName` with header `Authorization: MediaBrowser Client="...", Device="...", DeviceId="...", Version="..."` and body `{"Username","Pw"}` -> `AccessToken`. Idempotency gate: `GET /System/Info/Public` field `StartupWizardCompleted`. [VERIFIED: local run; schemas read from `/api-docs/openapi.json` of the running server]

Authentication on Jellyfin 12.3 (legacy auth is off by default): only `Authorization: MediaBrowser Token="<token>"` and the query parameter `ApiKey=<token>` returned 200; `X-Emby-Token`, `X-MediaBrowser-Token` and `api_key=` returned **401**; `/emby/*` returns 404. [VERIFIED: local run, GET /Sessions]

Then (all verified 204/200):
- Household user: `POST /Users/New {"Name":"household","Password":"<from .env>"}`; then read `GET /Users/{id}`, set `Policy.IsHidden=false` and `POST /Users/{id}/Policy` (see Pitfall 3); `POST /Users/Configuration?userId={id}` with `{"AudioLanguagePreference":"eng","PlayDefaultAudioTrack":false,"SubtitleLanguagePreference":"eng","SubtitleMode":"Smart", ...}`. `SubtitleMode` enum is `Default|Always|OnlyForced|None|Smart`.
- Admin hidden from login screens: `Policy.IsHidden=true`; `GET /Users/Public` then returned exactly `["household"]`, and the hidden admin still logs in by name. Household policy: `IsAdministrator=false`, `EnableContentDeletion=false`, `EnableRemoteControlOfOtherUsers=false`, `EnableCollectionManagement=false`; leave `EnableVideoPlaybackTranscoding=true` during the gate (UI-SPEC).
- Libraries: `POST /Library/VirtualFolders?name=Movies&collectionType=movies&paths=/scratch/Movies&refreshLibrary=false` with body `{"LibraryOptions":{"EnableRealtimeMonitor":true,"SaveLocalMetadata":false,"EnableInternetProviders":true,"PreferredMetadataLanguage":"en","MetadataCountryCode":"US","EnableTrickplayImageExtraction":false,"EnableChapterImageExtraction":false}}`. `collectionType` enum: `movies|tvshows|music|musicvideos|homevideos|boxsets|books|mixed`. Read back: `SaveLocalMetadata=false`, `EnableRealtimeMonitor=true`.
- Server name and bitrate: `GET /System/Configuration`, modify `ServerName`, `RemoteClientBitrateLimit`, `POST /System/Configuration`.
- Scan: `POST /Library/Refresh`, then poll `GET /ScheduledTasks` for the task whose **`Key == "RefreshLibrary"`** until `State == "Idle"` **and** item counts are stable (Pitfall 5).

### Pattern 5: Play-method evidence (two independent signals)
Signal A, Sessions API: `GET /Sessions?activeWithinSeconds=30` -> `PlayState.PlayMethod` (`Transcode|DirectStream|DirectPlay`, **as reported by the client**), `NowPlayingItem.Name`, and `TranscodingInfo{IsVideoDirect, IsAudioDirect, VideoCodec, AudioCodec, Container, Width, Height, Bitrate, TranscodeReasons[]}`. Observed sample while a stream was active: `{"IsVideoDirect": true, "IsAudioDirect": false, ... "TranscodeReasons": ["ContainerNotSupported", "AudioCodecNotSupported"]}`; with a width limit: `"IsVideoDirect": false, ... "VideoResolutionNotSupported"`. [VERIFIED: local run] `TranscodingInfo` is **only present while ffmpeg runs**: on a 6 s clip it was gone by the next poll, and on a 90 s clip it was `null` in 5 of 6 one-second polls. The helper must poll at <= 1 s, keep the last non-null sample per play session, and use clips of 60 s or more.
Signal B, server logs: every ffmpeg job writes `jellyfin/config/log/FFmpeg.<Type>-<timestamp>_<itemId>_<hash>.log` with `<Type>` one of `Remux` (video copy and audio copy), `DirectStream` (video copy, audio re-encoded), `Transcode` (video re-encoded, the log shows `-codec:v:0 libx264`); direct play writes no ffmpeg log. [VERIFIED: three jobs produced exactly these three prefixes] Note the naming trap: the log type `DirectStream` is **audio-only transcode**, not the Sessions `PlayMethod=DirectStream`.

Mapping to the four UI-SPEC values: no ffmpeg log and `PlayMethod=DirectPlay` -> `Direct play`; log `Remux` -> `Remux`; log `DirectStream` -> `Audio transcode`; log `Transcode` -> `Video transcode`. Cross-check against `TranscodingInfo`; if the two disagree, record both and flag the row. Take the worst method seen during one play session (a seek can start a new job).

### Pattern 6: Compat clip generator (verified encodes)
Host ffmpeg 6.1.1, argument lists, no shell. Verified command shapes:
```
# HEVC 10-bit + DTS + SRT in MKV
ffmpeg -y -ss <t> -t 60 -i <source> -i <subs.srt> -map 0:v:0 -map 0:a:0 -map 1:0 \
  -c:v libx265 -preset ultrafast -pix_fmt yuv420p10le -x265-params log-level=error -tag:v hvc1 \
  -c:a dca -strict -2 -ac 2 -c:s srt out.mkv
# H.264 + EAC3 + mov_text in MP4
ffmpeg -y ... -c:v libx264 -preset ultrafast -pix_fmt yuv420p -c:a eac3 -c:s mov_text out.mp4
```
Probe results: `hevc,Main 10,yuv420p10le,1920x1080`, `dts`, `subrip`; `h264`, `eac3`, `mov_text`. A 5 s 1080p x265 10-bit clip took ~12 s. [VERIFIED: local run] `ass` (embedded styled text) is encodable (`-c:s ass` from an `.ass` file). **ffmpeg has no PGS encoder** (`pgssub` is decode-only), so a real PGS row needs an existing `.sup` plus `mkvmerge`, which is **not installed** here.

Design the matrix one-factor-at-a-time, not as a 96-clip cross product (about 24 gating clips): H.264/HEVC8/HEVC10 x MKV/MP4 with AAC (6), AC3/EAC3/DTS/AAC on H.264 MKV plus AC3/EAC3 on MP4 (6), SRT MKV, mov_text MP4, ASS MKV on H.264+AAC (3), plus information groups (PGS, 2160p, HDR10) and the sanity group (Sintel MKV as downloaded, Jellyfin test videos). File name prefix = the stable row ID (`A01...`), so `NowPlayingItem.Name` identifies the clip.

### Anti-Patterns to Avoid
- **Trusting `PlayState.PlayMethod` alone:** it is whatever the client reported (my simulated client reported `Transcode` and the server showed `DirectPlay`; the source stores `info.PlayMethod` verbatim). Use Pattern 5.
- **Using `jellyfin-web` forks or patching the client** to force HEVC (a forum workaround): it changes what the gate measures; forbidden by "stock web UI" scope.
- **Mounting `data/media` into Jellyfin now:** Phase 4 owns that; the scratch tree is the only library root.
- **Publishing 8096 or adding an admin override** (D-82).
- **Committing anything under `jellyfin/`** (DB, tokens, downloaded media).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Metadata, posters, plots, seasons | Own scraper or NFO writer | Jellyfin's built-in TMDb provider (worked from inside the container, `SaveLocalMetadata=false`) | Verified identification of Big Buck Bunny, Sintel, Tears of Steel, Elephants Dream, Pioneer One incl. episode titles |
| Compat clips | A second encoder or sample hoster | Host `ffmpeg` argument lists + the Jellyfin test-video set | Verified encodes; the set ships `sha256sum` sidecars |
| Play-method detection | Parsing the web player's UI | Sessions API + `FFmpeg.<Type>` log prefix | Server-side evidence, no TV-side code |
| Wizard and user setup | Clicking through the UI | The documented Startup/Users/VirtualFolders API (verified) | Idempotent, repeatable on the production box (INFRA-05 later) |
| mDNS advertising on Ubuntu | A custom responder | `avahi-daemon` with `host-name=` | One config line; see mDNS section |
| Torrent-name parsing | Regexes in Phase 3 | Nothing in Phase 3. Phase 4 evaluates a maintained parser (guessit is `[SUS]`/`[ASSUMED]`) | Phase 3 only needs the verdict; Jellyfin's own parser is the thing under test |

**Key insight:** every behaviour Phase 3 needs is already a Jellyfin or ffmpeg feature; the phase is configuration, evidence collection and documentation, plus a thin set of stdlib scripts.

## Common Pitfalls

### Pitfall 1: A route-level `header` cannot override the site-level one
**What goes wrong:** putting `header Content-Security-Policy "..."` inside `handle /jellyfin/*` leaves the **portal** policy on the response (blank/broken Jellyfin).
**Why it happens:** Caddy applies header ops as the response is written, innermost wrapper first and the site-level wrapper last, so the outer `Set` wins. [VERIFIED: reproduced twice with caddy 2.11.7: response carried `default-src 'self'; script-src 'self'; style-src 'self'` although the handle set another]
**How to avoid:** scope the portal policy with `@notjellyfin not path /jellyfin /jellyfin/*` and `header @notjellyfin Content-Security-Policy ...` (Pattern 3). Then check `curl -sI .../jellyfin/web/index.html | grep -ci '^content-security-policy'` prints `1`.
**Warning signs:** login page unstyled or blank; console shows `style-src 'self'` violations.

### Pitfall 2: The UI-SPEC starting CSP blocks WebAssembly, and Jellyfin sends no CSP of its own
**What goes wrong:** `WebAssembly.compile` is blocked under the UI-SPEC policy [VERIFIED: headless Chromium 1217, result `wasm-blocked: ... violates the following Content Security policy directive`]. jellyfin-web 12.3 ships `libbitsub_bg.wasm` (PGS/VobSub) and `libass-wasm` (ASS). With wasm blocked the client cannot render ASS/PGS, so the server may burn subtitles in (a video transcode) and produce a **false NO-GO** on the subtitle group.
**Why it happens:** `script-src` without `'wasm-unsafe-eval'` forbids wasm. And Jellyfin 12.3 returns no `Content-Security-Policy` header at all [VERIFIED: `curl -si .../jellyfin/web/index.html`], so "Jellyfin's documented default" does not exist; upstream `index.html` also has an inline `<style>`, hence `style-src 'unsafe-inline'`.
**How to avoid:** use the policy in Pattern 3 (UI-SPEC line plus `'wasm-unsafe-eval'`). With it, the login page, home, a detail page, the TV-shows view, and the dashboard pages General, Streaming, Libraries, Networking, Activity, Logs and Devices all rendered with no other violation. [VERIFIED: headless Chromium, logged in as household and as admin]. Keep `header_down -Content-Security-Policy` out unless a future Jellyfin starts sending one.
**Accepted residual violation:** the web client tries to load `https://www.gstatic.com/cv/js/sender/v1/cast_sender.js` (Chromecast) and the policy blocks it. This is expected and harmless; **amend UI-SPEC acceptance check 3** ("no CSP violation") to "no violation except `cast_sender.js`". An initial `/socket` 403 on the login page (before authentication) is also normal.
**Warning signs:** subtitles of type ASS/PGS missing or burned in.

### Pitfall 3: New Jellyfin users are hidden from login screens
**What goes wrong:** after `POST /Users/New`, `Policy.IsHidden` is `true`; with the admin also hidden, `GET /Users/Public` returns `[]` and the TV shows no tile. [VERIFIED: printed policy of a freshly created user, then `/Users/Public` = `[]`]
**How to avoid:** set `IsHidden=false` on `household` explicitly and assert `GET /Users/Public` equals exactly `["household"]` in the setup script's `--check`.

### Pitfall 4: Stock Jellyfin 12 has no TVmaze or TVDb provider
**What goes wrong:** UI-SPEC says "Fetch online from TheMovieDb and TVmaze/TVDb (as shipped)". Installed plugins are `AudioDB, ListenBrainz, MusicBrainz, OMDb, Studio Images, TMDb`; the TV library's series fetchers are `TheMovieDb` and `The Open Movie Database`. [VERIFIED: `GET /Plugins` and `/Libraries/AvailableOptions`]
**How to avoid:** change the UI-SPEC copy to "TheMovieDb (OMDb optional, needs its own key)". Pioneer One still got a TMDb id (33050), a TVDb id (170551 via external ids) and episode titles ("Earthfall", "The Man From Mars").

### Pitfall 5: Scan "finished" signals that are not
**What goes wrong:** polling "any scan task Idle" matched `Media Segment Scan` and ended the wait while `Scan Media Library` was `Running`; metadata (e.g. Tears of Steel) appeared only later. Right after `refreshLibrary=true` the task can also be `Idle` for a moment before it starts. [VERIFIED: both happened]
**How to avoid:** wait for the task with `Key == "RefreshLibrary"`: first until it is seen `Running` (or items appear), then until `Idle`; then require the item count and the count of items lacking provider ids to be unchanged for two polls (10 s). Same protocol for NAME-01.

### Pitfall 6: `RemoteClientBitrateLimit` does not cap the TV
**What goes wrong:** `GetMaxBitrate` applies the server (and per-user) limit **only if the client is not in the local network**; local clients are bounded only by the client-supplied `MaxStreamingBitrate`. [VERIFIED: source `Jellyfin.Api/Helpers/MediaInfoHelper.cs` v12.3 lines 518-540, `if (!isInLocalNetwork) { maxBitrate = Math.Min(...) }`] The TV through Caddy is a LAN client, so the Dashboard "Internet streaming bitrate limit (Mbps)" (Dashboard > Playback > Streaming) will not bind it.
**How to avoid:** satisfy JFIN-03 in three recorded parts: (1) set the server value (`RemoteClientBitrateLimit`, bits per second in the API `[ASSUMED]`, Mbps in the UI) and the per-user value; (2) set the **web client's own "Maximum streaming bitrate"** on the TV browser to the same value during the gate; (3) Phase 5's device profile `MaxStreamingBitrate` carries it forward. Verify with the server log line `RemoteClientBitrateLimit: <n>, RemoteIP: <ip>, IsInLocalNetwork: <bool>`. If the plan needs the limit to bind LAN clients, that is a design change (not available as a setting); record it instead.
**Choosing the value (D-96):** measure from a LAN device other than the server using the authenticated `GET /Playback/BitrateTest?Size=<n>` (answered 200, uncompressed, capped near 64 MiB, `Size=500000000` returned 400) or the web client's "Auto" detection, then cap = floor(0.7 x measured), clamped to 20-80 Mbps. Default if the TV link measures >= 86 Mbps: **60 Mbps** `[ASSUMED]`. Many TV Ethernet ports are 100 Mbps `[ASSUMED]`.

### Pitfall 7: Stock web profile makes MKV rows "Remux" by construction, and may misreport HEVC
**What goes wrong:** jellyfin-web 12.3 `testCanPlayMkv` returns `false` when `browser.vidaa`; `browser.vidaa = normalizedUA.includes('vidaa')`; HEVC support comes from `canPlayType('video/mp4; codecs="hvc1.1.L120"')` and VIDAA gets HEVC in HLS-TS only; DTS only if `canPlayType('video/mp4; codecs="dts-"')` says yes; the profile never claims HEVC in fMP4-HLS for VIDAA. [VERIFIED: source `src/scripts/browser.js`, `browserDeviceProfile.js` at v12.3] A forum report on a Hisense 55U7QF says the browser claims HEVC but plays it glitchily and x264 is fine `[CITED: forum.jellyfin.org/t-setting-up-jellyfin-on-a-hisense-vidaa-os-tv]` (a different model/firmware; treat as a hint, not evidence).
**How to avoid:** record the matrix as "stock Jellyfin web client on this browser", say so in `docs/tv-compatibility.md`, and add a "picture and sound OK" check per row (a row can be Direct play and still look wrong). The TV-side `canPlayType` truth is a Phase 5 prototype task (TV-05); do not build a probe page in Phase 3.

### Pitfall 8: Smart subtitles and untagged audio
**What goes wrong:** Smart mode loads preferred-language subtitles whenever the audio track language is **not** in the preferred list; files with an untagged audio language therefore get English subs. When the audio language is English it behaves like OnlyForced (forced always shown). [VERIFIED: source `Emby.Server.Implementations/Library/MediaStreamSelector.cs` v12.3: "If the audio language is one of the user's preferred subtitle languages behave like OnlyForced"] Language values are ISO 639-2 (`eng`), not `en`.
**How to avoid:** set `SubtitleLanguagePreference="eng"`; tag the generated clips' audio `language=eng`; expect Blender downloads with no tag to show subs.

### Pitfall 9: Wizard race and shared secrets
**What goes wrong:** between the first container start and the end of `jellyfin_setup.py` anyone on the LAN who opens `/jellyfin` can run the unauthenticated wizard and become admin. Also `backend` uses `env_file: .env`, so a Jellyfin admin password placed in `.env` is visible in the backend container's environment.
**How to avoid:** run the setup script immediately after `docker compose up -d --wait`, in the same documented step; keep the household password separate from the admin password; flag the `.env` exposure for the planner (see Open Question 3).

### Pitfall 10: Household password typed with a TV remote
`dev_env.py` gives every `change-me*` key `secrets.token_urlsafe(32)` (43 characters). Typing that on a TV is not workable. Either generate a short readable household password for this key (new rule in `dev_env.py`, still random) or use **Quick Connect** (enabled by default, `QuickConnectAvailable: true`; the login page shows "Use Quick Connect"). [VERIFIED: server config and login page text]

### Pitfall 11: Docker Desktop does not start at boot
Success criterion 4 ("after a laptop restart the TV still reaches the address") needs the stack running. Docker Desktop's "Start Docker Desktop when you sign in to your computer" is **off by default** and triggers on sign-in, not boot. [CITED: docs.docker.com/desktop/settings-and-maintenance/settings] Containers have `restart: unless-stopped`, so they come back once the engine is up. Other host pitfalls (`[ASSUMED]`, verify in the test): Windows "random hardware addresses" on Wi-Fi breaks a MAC-based DHCP reservation; sleep on lid close makes the laptop unreachable; the production Ubuntu box has none of these (Docker as a systemd service).

### Pitfall 12: Existing Caddyfile test helper mis-reads `handle_errors`
`infra/tests/test_compose_invariants.py::_caddy_handle_blocks` treats any depth-1 line starting with `handle` as a handle block, and `test_index_and_spa_fallback_are_revalidated` requires the **last** block to start with `handle {`. A `handle_errors` block placed after the catch-all would break that test. Place `handle_errors` before the final `handle {`, or tighten the helper to `re.match(r"handle(\s|\{)", stripped)`. [VERIFIED: read in infra/tests/test_compose_invariants.py, `stripped.startswith("handle")` and `catch_all.lstrip().startswith("handle {")`]

## mDNS and the stable address (D-81, INFRA-04)

**What is known:** the VIDAA browser's `.local` behaviour is **not documented anywhere I could find**; two searches returned nothing for VIDAA. `[ASSUMED]` that it may not resolve. **Windows** answering mDNS for its own host name is also unconfirmed (an article says only that Windows uses mDNS for lookups and a "mDNS (UDP-In)" firewall rule exists `[CITED: ctrl.blog/entry/windows-mdns-dnssd]`). So the plan is a ladder with a recorded result at each rung, and **the IP address stays the documented default until a rung passes on the real TV**.

1. **Rung 0, no software (dev laptop):** from the TV browser open `http://<windows-computer-name>.local/` (the portal answers on `/`). Pass means the TV resolves mDNS and Windows publishes its name; fail means nothing else will help on the TV and `.local` is dropped.
2. **Rung 1, only if rung 0 passes:** decide how to publish the household name `flatflix.local`.
   - **Production (Ubuntu Server):** `sudo apt install avahi-daemon`; in `/etc/avahi/avahi-daemon.conf` set `host-name=flatflix` (avahi registers this name instead of the system host name) and `allow-interfaces=<lan-nic>`, because Docker bridges (`docker0`, `br-*`) otherwise get advertised too; `deny-interfaces` takes precedence over `allow-interfaces`; the man page does not document wildcards, so list names or use `allow-interfaces`. `sudo ufw allow 5353/udp` if ufw is on. [CITED: man.archlinux.org/man/avahi-daemon.conf.5, quotes: "host-name= ... Set the host name avahi-daemon tries to register on the LAN", "deny-interfaces= ... takes precedence over allow-interfaces="]. A user report shows Docker-range addresses still leaking in some setups `[CITED: forums.docker.com/t/docker-network-interface-interferes-with-mdns-address/43337]`; verify with `avahi-resolve -n flatflix.local` from another LAN host.
   - **Dev (Windows host, Docker Desktop):** containers cannot publish on the Windows LAN, and WSL2's NAT does not forward multicast, so the publisher must run on Windows. Options, none verified for VIDAA: rename the PC (invasive), Apple Bonjour `dns-sd -P`, or a Python `zeroconf` ServiceInfo with `server="flatflix.local."` (package is `[SUS]`/`[ASSUMED]`). Choose the least invasive that rung 0 justifies; record it in `docs/setup.md` only if it works on the TV.
3. **Fallback, always:** router DHCP reservation by MAC and `http://<laptop-ip>/jellyfin`. The address check is recorded in the `## Address check` section of `docs/tv-compatibility.md` exactly as UI-SPEC defines.

Caddy `:80` matches any `Host`, and Jellyfin accepted requests addressed to `127.0.0.1` with BaseURL set; no Host configuration is needed for a `.local` name. [VERIFIED: local run via two different host:port origins]

## Naming scan test (NAME-01) design and early evidence

**Harness:** (1) capture ~30 names with the portal API the way `scripts/smoke.py` does (`POST /api/search {q,type}`, poll `GET /api/search/{id}`, rows have `name`); (2) hand-label each with truth `{kind, title, year}` or `{kind, series, season, episode}` in `jellyfin/scratch/corpus.json`; (3) create 1-second clips (`color` lavfi, 160x90, x264) at the **hardlink-shaped path**: for a torrent folder `Name.2019.1080p...-GRP/` keep that folder with the file inside, for a single-file torrent put the file in the library root, and for season packs keep `Show.S01.1080p...-GRP/Show.S01E01...mkv`; (4) one `movies` and one `tvshows` library over `scratch/Raw*`; (5) scan with the Pitfall 5 protocol; (6) read `GET /Items?Recursive=true&IncludeItemTypes=Movie,Series,Episode&Fields=ProviderIds,Path` and classify each name `identified` (title and year equal the truth), `unidentified` (no provider id, or no series link), or `wrong title`; (7) compute the D-92 bar and print the table the UI-SPEC wants (one row per name).

**Early evidence from a 16-name pilot** (generated names, real TMDb, Jellyfin 12.3.0) [VERIFIED: local run]:
- Movies: 10 of 10 got a TMDb id, but **`Blade.Runner.2049.2017.IMAX.1080p.WEB-DL.DD5.1.H264-CMRG.mkv` was matched to "Blade Runner" (1982)**. One wrong title already fails D-92's "zero wrong".
- Series: folder-per-season-pack layouts (`Pioneer.One.S01.1080p.WEB-DL.x264-GRP/...S01E01...`, `The Expanse.S03.COMPLETE...`) were identified with correct episode titles; **flat single-episode files** (`Breaking.Bad.S02E03.720p...mkv`, `Severance.2022.S01E01...mkv`, `[SubsPlease] Frieren - 05 (1080p) [ABCD1234].mkv`) became episodes with no series (`SeriesName=None`) or no season.
- Consequence for the plan: expect the formal test to confirm the user's lean (portal rename step). The rename step must handle year-in-title ("2049"), anime absolute numbering and bracket groups; a lookup (TMDB, D-93) would cover the "wrong title" case. These are Phase 4 inputs, recorded in the PROJECT.md decision row.
- Do not commit the real captured names by default (they carry scene-group and site tags such as `[YTS.MX]`); keep `corpus.json` gitignored and commit only the evaluation script, a tiny synthetic sample, and the result table with sanitised names. Flag to the user (Open Question 4).

## Code Examples

### Idempotency and scan wait (Pattern 4/Pitfall 5)
```python
# Source: reproduced against jellyfin/jellyfin:12.3.20261023-013714, 2026-10-25
def refresh_library_idle(api) -> bool:
    tasks = api.get("/ScheduledTasks")
    return next(t for t in tasks if t["Key"] == "RefreshLibrary")["State"] == "Idle"
# Wait: seen Running (or item count > 0) first; then Idle and stable counts for 2 polls.
```

### Classifier (pure function, unit-testable with synthetic JSON)
```python
# Source: field names from /api-docs/openapi.json (TranscodingInfo, PlayerStateInfo, PlayMethod)
def method(play_method, transcoding_info, ffmpeg_log_type):
    if ffmpeg_log_type == "Transcode":     return "Video transcode"
    if ffmpeg_log_type == "DirectStream":  return "Audio transcode"
    if ffmpeg_log_type == "Remux":         return "Remux"
    if transcoding_info:                   # fall back to the session sample
        if not transcoding_info["IsVideoDirect"]: return "Video transcode"
        return "Remux" if transcoding_info["IsAudioDirect"] else "Audio transcode"
    return "Direct play" if play_method == "DirectPlay" else "not tested"
```

### Avahi (production), Source: avahi-daemon.conf(5)
```ini
[server]
host-name=flatflix
allow-interfaces=<lan-nic>
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `X-Emby-Token` header, `api_key=` query, `/emby/*` routes | `Authorization: MediaBrowser Token="..."` or `ApiKey=` query | Jellyfin 12.0 (2026-09-08), legacy auth off by default | Phase 3 scripts and the Phase 5 app must use the new header; `ApiKey=` is the option for `<img src>` |
| Global subtitle configuration | Per-library subtitle settings | 12.0 | Only affects subtitle *download* settings; user subtitle mode is unchanged (verified) |
| Legacy web layout | "Modern" layout default (React, MUI, TanStack) | 12.0 | A new UI to test on the VIDAA browser; a `Legacy` layout exists |
| Jellyfin 10.x docs for BaseURL / CSP | 12.x ships no CSP; wasm renderers for ASS/PGS | 12.x | Requires `'wasm-unsafe-eval'` |

**Deprecated/outdated:** `/emby` and `/mediabrowser` route prefixes removed; `GET /QuickConnect/Initiate` removed; 10.x-era guides that set `X-Emby-Token` will 401.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The VIDAA browser may not resolve `.local` names | mDNS | If it does, the household gets a nicer name; plan already tests rung 0 |
| A2 | Windows publishes its own host name over mDNS to the TV | mDNS | Rung 0 fails for a Windows reason, wrongly dropping `.local`; mitigate by also testing from a phone first |
| A3 | `RemoteClientBitrateLimit` API unit is bits per second (UI shows Mbps) | Pitfall 6 | Cap set 1,000,000x wrong; verify by setting in the UI and reading `/System/Configuration` |
| A4 | 60 Mbps default cap, TV Ethernet port often 100 Mbps | Pitfall 6 | Cap too high or too low; plan derives it from the measured throughput |
| A5 | VIDAA user agent contains `tv` (HbbTV) so jellyfin-web sets `browser.tv` and TV layout | Pitfall 7 | TV layout not auto-selected; set Display mode "TV" manually in the TV session |
| A6 | Windows "random hardware addresses" and sleep can break the reservation / reachability | Pitfall 11 | Extra restart test failures; docs wording only |
| A7 | `zeroconf` and `guessit` are the right packages for their roles and legitimate | Package audit | Both `[SUS]`; neither is required in Phase 3 |
| A8 | The real-TV `canPlayType` truth differs from the stock profile's choices for DTS/HEVC | Pitfall 7 | If equal, Phase 5 can reuse the matrix directly |
| A9 | A PGS row can be built from a hand-made `.sup` (SubtitleEdit on the Windows admin PC) plus a muxer | Pattern 6 | If not obtainable, the PGS row stays `not tested` with a reason (UI-SPEC allows it; non-gating) |

## Open Questions

1. **Compat library vs the two-library UI-SPEC.**
   - Known: the household sees every library it may access; compat clips named `A01...` would pollute Movies, and TMDb would try to match them.
   - Unclear: UI-SPEC lists only `Movies` and `TV Series`.
   - Recommendation: a third admin-created library `Compat` (type `homevideos`, internet providers off), household access during the gate only, removed or hidden after the verdict; add a one-line UI-SPEC amendment.
2. **PGS source.** No PGS encoder exists and no hosted PGS sample was found. Recommendation: one `checkpoint:human-action` to export a `.sup` (SubtitleEdit) and mux it; otherwise record `not tested`. Needs `mkvtoolnix` on the host (not installed).
3. **Jellyfin admin password in the backend's environment.** `env_file: .env` exposes every key to the backend. Recommendation: accept for the dev laptop, record it, and decide in Phase 4 whether the backend gets an explicit `environment:` allowlist.
4. **Committing the captured corpus** (names carry scene/site tags). Recommendation: gitignore the real corpus, commit the script and a synthetic sample.
5. **TV browser identity.** The doc may record the browser engine major version only. Method: open any user-agent echo page on the TV, copy only the Chromium major version. No other device data.
6. **TMDb egress and API key limits.** Jellyfin uses its bundled TMDb key; heavy rescans of 30 names are fine. Phase 4 decides the opt-in `TMDB_API_KEY` for the backend.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Docker / Compose | Jellyfin, Caddy | yes | Docker 29.7.2, Compose v5.4.0 (Docker Desktop) | none needed |
| `ffmpeg`, `ffprobe` (host) | clip generator | yes | 6.1.1-3ubuntu5 (libx264, libx265, aac, ac3, eac3, dca, srt, ass, mov_text) | none needed |
| `mkvmerge` (MKVToolNix) | PGS row | no | - | row `not tested`, or install on host (apt) |
| `curl`, `unzip`, `jq` | docs/checks, BBB zip | yes | system | - |
| Python 3.12, `uv` | scripts, tests | yes | 3.12.3, uv 0.6.14 | - |
| Headless Chromium (Playwright cache) | optional CSP check | yes | chromium-1217 headless shell | manual console check |
| Internet from the Jellyfin container | TMDb scan | yes | verified scan | none (metadata would be empty) |
| Real Hisense TV, same LAN, Ethernet | COMPAT-01..04, D-81 | not verifiable here | firmware V0003.09.60A.Q0707 (from CONTEXT) | none; human checkpoint |
| `avahi-daemon` | production mDNS | not on the future box yet (a binary exists in WSL, useless for the LAN) | - | IP fallback |
| Free disk | Blender sources (~1.5 GB) | yes | 845 GB free | - |

**Missing dependencies with no fallback:** the real TV session (human).
**Missing with fallback:** `mkvmerge` (PGS row).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 (+ pyyaml), already locked |
| Config file | `backend/pyproject.toml` (`testpaths`, markers `integration`, `sandbox`; add marker `jellyfin`) |
| Quick run command | `uv run --project backend --frozen pytest infra/tests -q` |
| Full suite command | `uv run --project backend --frozen pytest backend/tests infra/tests -q` |
| Opt-in live checks | `uv run --project backend --frozen python scripts/jellyfin_setup.py --check` (needs the running stack) and `docker run --rm -v "$PWD/web/Caddyfile:/etc/caddy/Caddyfile:ro" caddy:2.11.7-alpine caddy validate --config /etc/caddy/Caddyfile` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| JFIN-01 | `jellyfin` service: pinned (not `latest`), no `ports`, `user` = PUID:PGID, hardened flags, healthcheck on `/jellyfin/health`, rotated logging, volumes `/config` `/cache` rw and `/scratch` read-only, no `/data` mount | unit (YAML) | `pytest infra/tests/test_compose_invariants.py -q` | extend, Wave 0 |
| JFIN-01 | household and admin exist, household unhidden, `/Users/Public == ["household"]`, language prefs | live | `python scripts/jellyfin_setup.py --check` | Wave 0 |
| JFIN-02 | libraries exist; every sample item has `Overview` and a Primary image | live | `jellyfin_setup.py --check` | Wave 0 |
| JFIN-03 | `RemoteClientBitrateLimit` equals the documented value; doc records measured throughput | live + doc lint | `--check`, `test_docs_contract.py` | Wave 0 |
| COMPAT-01..03 | `docs/tv-compatibility.md` layout: five H2 groups, nine columns, Method in the four allowed values, no `not tested` in gating rows once a verdict exists, forbidden content absent (serial, ESN, MAC, dotted IP) | doc lint | `pytest infra/tests/test_docs_contract.py -q` | Wave 0 |
| COMPAT-01..03 | classifier and row rendering with synthetic Sessions/log fixtures; clip generator command lists | unit | `pytest backend/tests/test_jellyfin_scripts_contract.py -q` | Wave 0 |
| COMPAT-04 | verdict heading holds exactly one of `GO`, `GO with conditions`, `NO-GO` and the follow-up line | doc lint | `test_docs_contract.py` | Wave 0 |
| INFRA-03 | only `web` publishes; `jellyfin` on `{"jellyfin"}`, `web` on `{"edge","jellyfin"}`, backend/qbit/sandbox not on it; `docs/ports-and-media.md` Jellyfin row updated; `web` does not depend on jellyfin | unit | `pytest infra/tests/test_compose_invariants.py -q` | extend |
| INFRA-03 | Caddyfile: portal CSP text equal to the pre-phase string and no `'unsafe-inline'`; jellyfin handle has `reverse_proxy jellyfin:8096` and a CSP with `'wasm-unsafe-eval'`; redir; `handle_errors` text; last `handle` still the catch-all | unit (text) | `pytest infra/tests/test_caddyfile.py -q` | Wave 0 |
| INFRA-03 | live: exactly one CSP header on `/jellyfin/web/index.html`, portal policy unchanged on `/`, 308 on bare path, 502 text with Jellyfin stopped | live | the four curl checks from UI-SPEC plus `docker compose stop jellyfin` | manual script in plan |
| INFRA-04 | `docs/setup.md` has `## Jellyfin and the TV`, `### Keep the laptop on the same address`, placeholders only; hygiene test still green | doc lint | `pytest infra/tests -q` | Wave 0 |
| INFRA-04 | restart laptop and router, TV reaches the same address | manual (human) | recorded in the doc | - |
| NAME-01 | evaluation logic (identified / unidentified / wrong title, D-92 bar) on synthetic Items JSON; PROJECT.md decision row no longer `Pending` | unit + doc lint | `test_jellyfin_scripts_contract.py`, `test_docs_contract.py` | Wave 0 |
| NAME-01 | the real 30-name scan | live + human labels | `python scripts/name_scan.py run` | Wave 0 |
| UI-SPEC | `git diff --stat -- frontend/` empty for the phase | check | `git diff --stat main -- frontend/` | - |

### Sampling Rate
- **Per task commit:** `uv run --project backend --frozen pytest infra/tests -q` (seconds)
- **Per wave merge:** `uv run --project backend --frozen pytest backend/tests infra/tests -q`
- **Phase gate:** full suite green, the live checks green on the running stack, `docs/tv-compatibility.md` verdict written, before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `infra/tests/test_caddyfile.py` (new): portal CSP identical, Jellyfin route contract, tolerant of `handle_errors`
- [ ] `infra/tests/test_docs_contract.py` (new): doc structure, forbidden content, PROJECT.md row
- [ ] extend `infra/tests/test_compose_invariants.py`: Jellyfin service, network sets (replace the `web == {"edge"}` assertion), image pin, ports doc row
- [ ] `backend/tests/test_jellyfin_scripts_contract.py` (new): classifier, renderer, name evaluator, clip command builder, loaded by path like `test_smoke_contract.py`
- [ ] `.gitignore`: `jellyfin/`; `.env.example`: `JELLYFIN_ADMIN_PASSWORD`, `JELLYFIN_HOUSEHOLD_PASSWORD`, empty `TMDB_API_KEY`; `dev_env.py` rule for a short household password
- [ ] `scripts/init-host-dirs.sh`: create `jellyfin/{config/config,cache,scratch}` and the seed file; extend the test-less dir list
- Framework install: none.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | Jellyfin accounts with passwords from `.env` (never committed); admin hidden from login screens; wizard run immediately (Pitfall 9) |
| V3 Session Management | yes | Jellyfin access tokens; setup scripts authenticate per run and keep no API key on disk |
| V4 Access Control | yes | household non-admin, no delete, no remote control; Jellyfin reachable only via Caddy (no published 8096); admin dashboard only via `/jellyfin` |
| V5 Input Validation | yes | scripts use argument lists and `json`, no shell strings; corpus names are data, written as file names after a character whitelist; no path from a browser |
| V6 Cryptography | no | none hand-rolled; HTTP on the LAN as for the portal (HTTPS is EXT-01) |
| V14 Configuration | yes | pinned image, read-only root, `cap_drop ALL`, `no-new-privileges`, scratch mount read-only, own network, CSP scoped per route, gitignored `jellyfin/` |

### Known Threat Patterns for Jellyfin + Caddy

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Unauthenticated first-run wizard on the LAN | Elevation of privilege | Provision in the same step as `up`; verify `StartupWizardCompleted` |
| CSP weakened for the whole origin while loosening for Jellyfin | Tampering | Scoped matcher; infra test pins the portal policy text and forbids `'unsafe-inline'` there (Pitfall 1) |
| Token in URLs (`ApiKey=` appears in `TranscodingUrl` and stream URLs) | Information disclosure | Never log full URLs in scripts; Caddy has no access log; do not paste URLs into docs |
| Untrusted media parsed by Jellyfin's ffmpeg | Tampering / DoS | Phase 3 mounts only trusted scratch files; Phase 4 keeps `media` read-only and relies on Phase 2.1 validation. PROJECT.md already notes Jellyfin is not isolated by the sandbox |
| Jellyfin admin password in the backend's env | Information disclosure | Open Question 3 |
| Public repo leaks (serial, ESN, MAC, LAN IP, names with site tags) | Information disclosure | Doc lint forbids them; hygiene test; corpus gitignored |
| Spoofed `X-Forwarded-For` | Spoofing | Caddy replaces client-sent values by default; do not add `trusted_proxies` |

## Sources

### Primary (HIGH confidence)
- Local reproduction, 2026-10-25: `jellyfin/jellyfin:12.3.20261023-013714` (server 12.3.0), `caddy:2.11.7-alpine`, host ffmpeg 6.1.1, headless Chromium 1217 (CDP script). Covers every `[VERIFIED: local run]` tag. Jellyfin's own OpenAPI document served at `/jellyfin/api-docs/openapi.json` (schemas `UserPolicy`, `UserConfiguration`, `NetworkConfiguration`, `ServerConfiguration`, `LibraryOptions`, `TranscodingInfo`, `PlayerStateInfo`, `PlayMethod`, `TranscodeReason`).
- Jellyfin source at tag v12.3 via raw.githubusercontent.com: `Jellyfin.Api/Helpers/MediaInfoHelper.cs` (`GetMaxBitrate`), `Emby.Server.Implementations/Library/MediaStreamSelector.cs` (Smart mode), `Emby.Server.Implementations/Session/SessionManager.cs` (line 456 stores `info.PlayMethod`); jellyfin-web v12.3 `src/scripts/browser.js`, `browserDeviceProfile.js`, `package.json`.
- GitHub releases (jellyfin/jellyfin v12.0, v12.2, v12.3 notes) and Docker Hub tag listings for `jellyfin/jellyfin` and `linuxserver/jellyfin`.
- Repo files read this session: `CLAUDE.md`, `home-theater.md`, `docs/ports-and-media.md`, `docs/setup.md` (headings, phone access, troubleshooting), `docker-compose.yml`, `docker-compose.admin.yml`, `web/Caddyfile`, `web/Dockerfile`, `.env.example`, `scripts/init-host-dirs.sh`, `scripts/make_probe_fixtures.py`, `scripts/dev_env.py`, `.gitignore`, `infra/tests/test_compose_invariants.py`, `infra/tests/test_repo_hygiene.py` (head), `backend/pyproject.toml`, `backend/tests/test_smoke_contract.py` (head), CONTEXT, UI-SPEC, REQUIREMENTS, STATE.
- Jellyfin docs, Caddy reverse proxy and subpath: jellyfin.org/docs/general/post-install/networking/reverse-proxy/caddy/ (`redir /jellyfin /jellyfin/`, BaseUrl in `network.xml`).
- Docker Desktop settings page (start on sign-in, off by default); avahi-daemon.conf(5) man page (man.archlinux.org).
- repo.jellyfin.org/test-videos/ directory listing and file HEAD; download.blender.org directory listings and HEADs.

### Secondary (MEDIUM confidence)
- forum.jellyfin.org "Setting up Jellyfin on a Hisense VIDAA OS TV" (55U7QF; HEVC claimed but glitchy, `hisense://debug` web-app install, `browser.vidaa` patch).
- ctrl.blog "mDNS and DNS-SD slowly making their way into Windows 10"; forums.docker.com thread on mDNS and docker0.
- Jellyfin forum threads on bitrate limit behind a proxy (confirms the `RemoteClientBitrateLimit ... IsInLocalNetwork` log line as the check).

### Tertiary (LOW confidence)
- Anything about VIDAA `.local` resolution, VIDAA Chromium version and Windows mDNS responder behaviour: no source found, marked `[ASSUMED]`, resolved only by testing on the real TV.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - image, Caddy and ffmpeg all executed this session.
- Architecture (network, route, CSP, provisioning): HIGH - reproduced end to end, including a real browser.
- Pitfalls: HIGH for Jellyfin/Caddy ones (reproduced), MEDIUM for host/Windows ones.
- TV-side outcomes and `.local`: LOW until the real-TV session; the plan must treat them as measurements.

**Research date:** 2026-10-25
**Valid until:** 2026-11-08 for Jellyfin specifics (12.x is moving, new minor roughly every two to three weeks); the Caddy and compose findings remain valid while the pinned tags stay.
