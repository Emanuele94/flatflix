# Constraints (from SPECs)

Docs are written in Italian; content below is translated to English. Identifiers, endpoints, paths and code are verbatim.

# Part A: home-theater (Jellyfin + Hisense VIDAA TV app)

## HT: Product requirements and out-of-scope
- source: /home/emanuele/projects/flatflix/home-theater.md
- type: nfr
- content:
  Goal: personal home theater app for the home Hisense TV (VIDAA OS), to browse and watch own films and series in at least Full HD. Must feel like a real app, launched from an icon on the TV home, usable by non-technical household members.
  Requirements:
  - Smooth playback at least at 1080p, no quality loss versus the original file
  - Launch from an icon on the VIDAA home, full screen, without going through the browser
  - Full use with the remote only: arrows, OK, Back, Play/Pause
  - Library with posters, plots, seasons and episodes
  - "Continue watching" and watched/unwatched state
  - Frontend as lightweight as possible, suited to the TV's dated browser
  Out of scope for now: access from outside the home, multiple users with separate profiles, publishing on the VIDAA store.

## HT: Overall architecture and topology
- source: /home/emanuele/projects/flatflix/home-theater.md
- type: protocol
- content:
  Two pieces at home: the TV (shows the frontend) and the laptop (runs everything else in Docker). The only code to write is the frontend.
  The TV calls a single address, Caddy's, which serves the frontend files and forwards API and video to Jellyfin (avoids CORS; when the server moves to another machine only the IP changes).
  Backend is Jellyfin (configured, not coded), used via REST API. Trial phase: Docker on the laptop.
  Laptop setup: container `jellyfin/jellyfin` with volumes for config, cache and media folder; a Caddy container in front serving the frontend and acting as reverse proxy; Jellyfin admin interface on port 8096 (library created there); DHCP reservation on the router so the laptop keeps the same LAN IP.
  Embedded diagram (not recoverable from source): "architettura - TV, laptop e metadati online".

## HT: Jellyfin API surface used by the frontend
- source: /home/emanuele/projects/flatflix/home-theater.md
- type: api-contract
- content:
  - Authentication: user login or API key created from the admin panel
  - Film/series lists: `Items` endpoint, filtered by type and library
  - Posters: image endpoint, requesting the already reduced size for the TV
  - Start playback: `PlaybackInfo` with the TV's device profile; returns the streaming URL
  - Progress: reports for playback start, progress and stop

## HT: Media file naming (required for Jellyfin scan)
- source: /home/emanuele/projects/flatflix/home-theater.md
- type: schema
- content:
  "To be respected for the scan to work":
  - Films: `Titolo (Anno)/Titolo (Anno).mkv`
  - Series: `Serie/Season 01/Serie S01E01.mkv`

## HT: Playback and codec matrix
- source: /home/emanuele/projects/flatflix/home-theater.md
- type: nfr
- content:
  Full HD is achieved by avoiding video transcoding; the TV hardware-decodes H.264 and HEVC, so the server should at most change container or audio.
  - Already compatible file: direct play, sent as is; server cost none; quality original
  - Unsupported container (typically MKV): remux to HLS without re-encoding; cost very low; quality original
  - Unsupported audio (DTS, TrueHD): transcode audio only; cost low; video original
  - Unsupported video codec: full ffmpeg transcode; cost high; quality reduced
  Player: native `<video>` element with HLS if the TV supports it, otherwise hls.js over Media Source Extensions. The device profile sent to `PlaybackInfo` declares what the TV can do.
  Network: 1080p needs about 8-20 Mbps; Ethernet on the TV where possible, otherwise 5 GHz Wi-Fi; max bitrate configured on Jellyfin.
  Compatibility test (to do BEFORE the frontend, all unchecked in source): open Jellyfin web UI from the TV and try films; check H.264 and HEVC incl. 10-bit; check audio AAC, AC3, EAC3, DTS; check SRT and embedded subtitles; check in admin panel which playbacks end in transcoding.

## HT: TV and frontend constraints (framework proposal, not locked)
- source: /home/emanuele/projects/flatflix/home-theater.md
- type: nfr
- content:
  TV limits: CPU/memory far below a phone (no heavy animations, few large images at a time); dated VIDAA browser (transpiled build, e.g. Vite legacy plugin, real TV tests); remote only (needs spatial navigation).
  Proposed choice: Preact + Vite with a spatial-navigation library and a transpiled build for old browsers (status: proposed; see open decisions in context.md).
  Options evaluated: Preact + Vite (very low weight; preact-spatial-navigation or Norigin core); SolidJS (very low; solidjs-spatial-navigation, declared tested on VIDAA); Lightning 3 + Blits (low, WebGL render; WebGL support on VIDAA to be verified); Vanilla TypeScript (minimal; everything from scratch).
  App structure: four screens (Home, Library, Detail, Player), thin API client to Jellyfin, minimal router, Back-key handling on every screen.
  Fallback rule: if TV tests show grid scroll lag, fall back to SolidJS; Lightning only if that is not enough.
  Frontend must stay a pure web app with no VIDAA-specific APIs so plan A to plan B needs no rewrite.

## HT: TV distribution plan
- source: /home/emanuele/projects/flatflix/home-theater.md
- type: nfr
- content:
  Delivered as a hosted app: the TV only holds an icon opening the frontend URL full screen; code lives on the server.
  Plan A: community open-source tool that, with a temporary DNS redirect, adds a VIDAA home app pointing to a chosen URL; one-time install pointing to `http://<ip-laptop>:<porta>` (port not specified); unofficial, firmware update may break it, tool code must be read before use; official publication (developer account, NDA, certification) judged not worthwhile.
  Plan B: Google TV or Fire TV HDMI stick (30-70 EUR); same frontend in a WebView (e.g. Capacitor) installed as APK; official and stable, usually better codec compatibility; HDMI-CEC allows a single remote.

# Part B: qbit-wrapper (self-service download portal on qBittorrent)

## QB: Context, goals and non-goals
- source: /home/emanuele/projects/flatflix/qbit-wrapper.md
- type: nfr
- content:
  Custom, simple, secure frontend letting a non-technical user (the author's wife) search films and TV series, select a result, start the download on qBittorrent, and save automatically into predefined separate folders. Relies on qBittorrent and its search plugins via the official Web API. The user must never see qBittorrent, save paths or credentials.
  Goals: minimal web UI for search and download; automatic mapping of content type to destination folder; no manual path config by end user; use search plugins already installed in qBittorrent; simple download status monitoring; qBittorrent credentials isolated from the browser.
  Non-goals: replacing Sonarr/Radarr or other library managers; music, books, games, software; exposing qBittorrent WebUI directly to the Internet; letting the end user change categories, paths or qBittorrent settings.

## QB: Functional requirements F1-F8
- source: /home/emanuele/projects/flatflix/qbit-wrapper.md
- type: nfr
- content:
  - F1: user can search films and TV series by keyword
  - F2: results show name, size, seeders, leechers and source
  - F3: user can start the download of a result
  - F4: download is automatically assigned to category `Film` or `SerieTV`
  - F5: each category saves to a predefined path
  - F6: user can see in-progress and completed downloads
  - F7: user can cancel a download
  - F8: access is protected by login

## QB: Non-functional requirements NF1-NF6
- source: /home/emanuele/projects/flatflix/qbit-wrapper.md
- type: nfr
- content:
  - NF1: responsive interface, usable from a smartphone
  - NF2: perceived response time < 2 s for search
  - NF3: qBittorrent credentials never exposed to the frontend
  - NF4: communication with qBittorrent only from internal network or container
  - NF5: configuration via environment variables
  - NF6: essential logs for debug and audit

## QB: Categories and save paths
- source: /home/emanuele/projects/flatflix/qbit-wrapper.md
- type: schema
- content:
  Category `Film` -> `/media/Film` (films); category `SerieTV` -> `/media/SerieTV` (TV series).
  Rules: create categories via API or manually in WebUI; disable "Append category name to save path"; backend accepts no paths from the frontend (category is the only parameter); paths must be mounted volumes writable by the qBittorrent container.
  Creation: `POST /api/v2/torrents/createCategory` (application/x-www-form-urlencoded) with `category=Film&savePath=/media/Film` and `category=SerieTV&savePath=/media/SerieTV`.

## QB: Backend API
- source: /home/emanuele/projects/flatflix/qbit-wrapper.md
- type: api-contract
- content:
  - POST `/api/login`: application user login
  - GET `/api/search`: start and fetch search results (e.g. `GET /api/search?q=Inception&type=film`)
  - POST `/api/download`: add torrent to qBittorrent; body `{"magnet": "magnet:?xt=urn:btih:...", "type": "film"}`
  - GET `/api/torrents`: list Film/SerieTV downloads (frontend polls every 5 s)
  - DELETE `/api/torrents/{hash}`: cancel or remove a torrent
  - GET `/api/health`: service status
  Type mapping: `film` -> `Film`, `serie` -> `SerieTV`. Backend stack stated as "FastAPI/Node" (undecided).

## QB: qBittorrent Web API integration
- source: /home/emanuele/projects/flatflix/qbit-wrapper.md
- type: api-contract
- content:
  Backend logs in via `POST /api/v2/auth/login` (username/password form) and keeps the session cookie.
  Endpoints used: `POST /api/v2/auth/login`; `POST /api/v2/search/start`; `GET /api/v2/search/status`; `GET /api/v2/search/results`; `GET /api/v2/search/plugins`; `POST /api/v2/torrents/add` (urls=magnet, category=Film); `GET /api/v2/torrents/info` (category=Film,SerieTV); `POST /api/v2/torrents/createCategory`; `GET /api/v2/torrents/categories`; `GET /api/v2/app/webapiVersion`.
  Version notes: `category` in `torrents/add` supported in recent versions; category-level `savePath` is the recommended approach; verify WebAPI >= 2.1.0 for advanced features.
  Search: `search/start` params `pattern`, `plugins` (separated by `|`), `category` (`movies` or `tv`). Film -> `movies`, Serie TV -> `tv`. Results normalized and sorted by seeders descending.

## QB: Security rules
- source: /home/emanuele/projects/flatflix/qbit-wrapper.md
- type: nfr
- content:
  Application login separate from qBittorrent; qBittorrent credentials only in backend; HTTPS mandatory if reachable from outside home; rate limiting on search and download endpoints; strict validation of `type` (only `film` or `serie`); no user-supplied file paths; logs without credentials; qBittorrent not exposed directly to the Internet.

## QB: Suggested deployment (docker compose)
- source: /home/emanuele/projects/flatflix/qbit-wrapper.md
- type: protocol
- content:
  ```yaml
  version: "3.8"
  services:
    frontend:
      build: ./frontend
      ports:
        - "8080:80"
      depends_on:
        - backend
    backend:
      build: ./backend
      environment:
        QBITTORRENT_URL: http://qbittorrent:8080
        QBITTORRENT_USER: admin
        QBITTORRENT_PASS: ${QB_PASS}
        CATEGORY_FILM: Film
        CATEGORY_TV: SerieTV
        APP_USER: moglie
        APP_PASS: ${APP_PASS}
        SECRET_KEY: ${SECRET_KEY}
      depends_on:
        - qbittorrent
    qbittorrent:
      image: lscr.io/linuxserver/qbittorrent:latest
      volumes:
        - /media/Film:/media/Film
        - /media/SerieTV:/media/SerieTV
        - ./qbittorrent/config:/config
      environment:
        - WEBUI_PORT=8080
  ```
  Note from source: frontend publishes host port 8080 (container 80); qBittorrent WebUI listens on 8080 inside its container (no host port published in this example).

## QB: Backend environment variables
- source: /home/emanuele/projects/flatflix/qbit-wrapper.md
- type: schema
- content:
  `QBITTORRENT_URL` (qBittorrent WebUI URL); `QBITTORRENT_USER`; `QBITTORRENT_PASS`; `CATEGORY_FILM` (default `Film`); `CATEGORY_TV` (default `SerieTV`); `APP_USER` (portal user); `APP_PASS` (portal password); `SECRET_KEY` (session key).

## QB: Error handling
- source: /home/emanuele/projects/flatflix/qbit-wrapper.md
- type: api-contract
- content:
  - 401: wrong qBittorrent credentials -> log, generic message
  - 403: user not authenticated -> redirect to login
  - 409: invalid category path -> verify volumes
  - 415: invalid torrent -> message to user
  - 502: qBittorrent unreachable -> retry and message
  - 504: search timeout -> reduce plugins or timeout
