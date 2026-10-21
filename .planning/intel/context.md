# Context (running notes by topic)

Translated from Italian. Prose sections of the SPEC-classified docs that are not constraints.

## Project phases and milestones (home-theater)
- source: /home/emanuele/projects/flatflix/home-theater.md
- Five phases, four gates. Frontend is written only after verifying the TV plays files without video transcoding. Phases 1 and 2 need no code: they remove technical doubts before investing in the UI.
- Embedded diagram "fasi del progetto - 5 fasi, 4 gate" is not recoverable from the source; phase names are absent.

## Risks and mitigations (home-theater)
- source: /home/emanuele/projects/flatflix/home-theater.md
- Community tool breaks after VIDAA update -> disable auto-updates if possible; plan B HDMI stick.
- Laptop off or IP changes -> DHCP reservation; polished "server unreachable" screen; later an always-on server.
- Codec/subtitles unsupported by TV player -> compatibility test before frontend; remux and audio-only transcode.
- VIDAA browser too old for modern JS -> transpiled build, TV tests from first screen.
- Poor poster-grid performance -> reduced images server-side, virtualized lists, fall back to SolidJS.
- Unstable Wi-Fi -> Ethernet on TV, max bitrate set on Jellyfin.

## Open decisions (home-theater, all unchecked in source)
- source: /home/emanuele/projects/flatflix/home-theater.md
- Final framework: Preact or SolidJS, to decide after a grid prototype on the TV.
- Final server hardware after laptop trial (Intel N100/N150 mini PC if transcoding is needed, otherwise possibly a Raspberry Pi 5).
- One Jellyfin user for the household or separate profiles.
- Default audio and subtitle language.
- If and when to open access from outside home (VPN such as Tailscale or WireGuard).

## References listed (home-theater)
- source: /home/emanuele/projects/flatflix/home-theater.md
- External only: VIDAA partner/HTML5 support, VIDAA web app development guide (PDF), Lightning 3/Blits performance blog, Norigin Spatial Navigation, preact-spatial-navigation, solidjs-spatial-navigation. No links to other project docs.

## Architecture components and flows (qbit-wrapper)
- source: /home/emanuele/projects/flatflix/qbit-wrapper.md
- Components: Frontend (search, results, download, status), Backend (auth, proxy to qBittorrent, category logic), qBittorrent (download engine, hosts search plugins), Search Plugins, File System (final Film/SerieTV folders), Reverse Proxy (HTTPS, secure external access), TMDB (optional: metadata, covers, normalized titles).
- Flow chain: user -> HTTPS reverse proxy -> frontend -> backend (FastAPI/Node) -> qBittorrent Web API v2 -> search plugins / download engine -> file system.
- Download flow: backend determines category, calls `torrents/add` with magnet + category, qBittorrent saves in `/media/Film` (or `/media/SerieTV`).
- Monitoring: frontend polls backend every 5 s; backend calls `torrents/info?category=Film,SerieTV`.

## Future extensions (qbit-wrapper)
- source: /home/emanuele/projects/flatflix/qbit-wrapper.md
- TMDB integration for covers and normalized titles; automatic season/episode search for series; push notifications on completion; multi-user with separate categories; integration with Jellyfin/Plex for the library; quality filter (1080p, 4K) and language; automatic subtitle download.

## Closing note (qbit-wrapper)
- source: /home/emanuele/projects/flatflix/qbit-wrapper.md
- Architecture keeps the frontend deliberately simple; all qBittorrent/category/path complexity stays in the backend. End user sees only a search and a "Download" button.

## Cross-doc relationship (derived from project note)
- source: orchestrator project note (not a document)
- Both SPECs describe parts of one home project ("flatflix") sharing a LAN laptop running Docker. They share `/media/Film` and `/media/SerieTV`: qBittorrent writes there, Jellyfin scans there. Neither doc references the other.
