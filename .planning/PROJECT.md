# flatflix

## What This Is

flatflix is a home media system for one household, running in Docker on the home LAN: developed on a WSL2 laptop, then installed on a dedicated box running Ubuntu Server. It has two parts that share one media folder: (1) a phone-friendly portal where a non-technical person searches for a film or series and starts the download on qBittorrent, and (2) a TV app for a Hisense VIDAA TV that browses and plays the library from Jellyfin in full HD. It is a public open-source repo (MIT): https://github.com/Emanuele94/flatflix

## Core Value

A non-technical household member can get a film or series onto the TV using only a phone and the TV remote, and watch it in at least 1080p with no video transcoding.

**Success metric:** a non-technical household member can (1) search and start a film/series download from a phone, and (2) find it and play it in at least 1080p from an icon on the TV, using only the remote, with no video transcoding.

## Requirements

Full list with IDs, source references and phase mapping: `.planning/REQUIREMENTS.md`. Both source docs are SPECs (no PRD), so the IDs were derived by the roadmapper from qbit-wrapper.md F1-F8 / NF1-NF6 and the home-theater.md requirements list.

### Validated

(None yet — ship to validate)

### Active

- [ ] Portal: login-protected, mobile-friendly search of films and series, results with size/seeders/leechers/source, one-tap download into the right predefined folder (Film or SerieTV) — Phase 1
- [ ] Portal: see in-progress and completed downloads, cancel a download, friendly errors, rate limiting, audit logs — Phase 2
- [ ] Download filtering: only video and subtitle files are ever downloaded (qBittorrent exclusion list + per-file allowlist), torrents without a video are rejected up front — Phase 1
- [ ] Quarantine: completed files are verified with ffprobe inside a throwaway Firecracker microVM before reaching the media folders; rejected files never reach Jellyfin — Phase 2.1
- [ ] Jellyfin on the laptop behind Caddy (single origin), stable LAN IP, real-TV compatibility gate (H.264/HEVC, audio, subtitles) proving no video transcoding — Phase 3
- [ ] Downloads from the portal land in Jellyfin's required naming layout and appear in the Film / SerieTV libraries without manual steps — Phase 4
- [ ] TV app (Home, Library, Detail, Player) fully usable with the remote only, playing at 1080p or better, with Continue watching and watched state — Phase 5
- [ ] Launch from an icon on the VIDAA home, end-to-end phone-to-TV acceptance, whole stack reproducible from the repo — Phase 6

### Out of Scope

- Replacing Sonarr/Radarr or other library managers — portal non-goal; note the Phase 3 naming decision may still evaluate adopting one as an external tool
- Music, books, games, software — films and TV series only
- Exposing the qBittorrent WebUI to the Internet — security rule; qBittorrent stays on the internal network
- End users changing categories, save paths or qBittorrent settings — the user must never see them
- Access from outside the home (VPN/HTTPS exposure) — deferred; LAN-only for v1
- Multiple users with separate profiles — out of scope for now (a single shared Jellyfin user unless Phase 3 decides otherwise)
- Publishing on the official VIDAA store — developer account, NDA and certification not worth it for home use

## Context

- Source docs (originally Italian, now English, SPEC type, not locked): `home-theater.md` (low classification confidence) and `qbit-wrapper.md` (medium). They are the detailed spec; planning files are in English. Ingest intel is in `.planning/intel/`; the conflict report is `.planning/INGEST-CONFLICTS.md`.
- Home theater part: backend is stock Jellyfin (configured, no server code); Caddy serves the frontend and reverse-proxies Jellyfin API and video from one origin (no CORS); the only custom code is the frontend. Proposed stack Preact + Vite with spatial navigation and a transpiled build for the old VIDAA browser; SolidJS is the fallback (not locked).
- Portal part: frontend -> own backend (FastAPI, D-01) -> qBittorrent Web API v2 and its search plugins. The backend owns qBittorrent credentials and session cookie; the browser sends only `type` (`film` | `serie`), mapped to category `Film` -> `/media/Film` or `SerieTV` -> `/media/SerieTV`.
- The parts meet at the shared media folders: qBittorrent writes, Jellyfin scans. Neither doc references the other, which produced three ingest warnings. The user approved all three and asked that each become explicit roadmap work:
  - W1 Naming gap: torrent names do not match Jellyfin's `Title (Year)/Title (Year).mkv` and `Series/Season 01/Series S01E01.mkv` — decided in Phase 3, implemented in Phase 4.
  - W2 Shared media wiring: host paths, permissions, incomplete-downloads folder, read-only Jellyfin mounts, libraries, rescan trigger — contract in Phase 1, Jellyfin side in Phase 4.
  - W3 Port map: port 8080 appears twice in the portal compose example and Caddy has no port — defined in Phase 1, applied to Caddy/Jellyfin in Phase 3.
- Build order is a user decision: portal first, then home theater. The Phase 3 Jellyfin library uses a scratch sample folder so the two parts are not integrated until the naming decision is made (Phase 4 integrates them).
- Runtime: the laptop is only the dev machine (WSL2, `/dev/kvm` available). Production is a dedicated box the user will buy and install with Ubuntu Server; it must support KVM so Firecracker runs (x86_64 with VT-x, e.g. Intel N100/N150). Clients: Hisense VIDAA TV browser, smartphones.
- Download safety (user request, added after roadmap creation): the household user must not be able to download anything other than films and series. Three layers: qBittorrent exclusion list and per-file allowlist (Phase 1), then quarantine plus ffprobe inside a Firecracker microVM (Phase 2.1). Note: Jellyfin still runs its own ffmpeg on validated files, so the sandbox catches anomalous files but does not isolate Jellyfin itself.

## Constraints

- **Runtime**: Docker on the LAN, no cloud — dev on a WSL2 laptop, production on a dedicated Ubuntu Server box; moving must only change the host address
- **Sandbox**: file validation runs in Firecracker microVMs — host needs KVM (`/dev/kvm`); production CPU must have VT-x/AMD-V; Raspberry Pi 5 likely unsuitable (Firecracker on ARM expects GICv3)
- **Download filtering**: only video (`.mkv`, `.mp4`, `.avi`, `.m4v`) and subtitle files are downloaded; nothing reaches the media folders without passing quarantine validation
- **Playback**: at least 1080p, no video transcoding (direct play, remux to HLS or audio-only transcode only) — Full HD without quality loss; TV hardware-decodes H.264 and HEVC; about 8-20 Mbps needed, Ethernet or 5 GHz Wi-Fi
- **TV client**: dated VIDAA browser, low CPU/memory, remote-only input — transpiled lightweight build, spatial navigation, few large images, real-TV tests from the first screen
- **Portability**: frontend is a pure web app with no VIDAA-specific APIs — so plan A (VIDAA icon tool) to plan B (HDMI stick + WebView APK) needs no rewrite
- **Backend (home theater)**: stock Jellyfin, no server code; TV calls one Caddy address — avoids CORS
- **Security (portal)**: qBittorrent credentials only in the backend; qBittorrent never exposed beyond the internal network; no paths from the browser; strict `type` validation; rate limiting; logs without credentials
- **Naming**: Jellyfin scan requires `Title (Year)/Title (Year).<ext>` for films and `Series/Season 01/Series S01E01.<ext>` for series
- **Repository**: public MIT repo — never commit secrets, LAN IPs or real credentials; config via env vars with `.env.example` placeholders
- **Distribution**: hosted app; plan A uses an unofficial community tool (tool source must be read before use; a firmware update may break it)

## Key Decisions

<decisions>
No locked decisions. No ADRs were ingested (both source docs are unlocked SPECs), so every row below is either a user decision or an open/proposed choice. Open items stay open until the phase that resolves them.
</decisions>

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Build the qBittorrent portal first, then the home theater | User decision at roadmap intake | Decided (user, 2026-10-21) |
| Public MIT repo, no secrets / LAN IPs / real credentials | User constraint; protects the household | Decided (user, 2026-10-21) |
| Planning files in English; user communicates in Italian | User instruction | Decided (user, 2026-10-21) |
| Portal UI text and all repo docs/planning in English | User instruction (2026-10-22: changed from Italian to English at user request — household includes an English speaker; repo is public) | Decided (user, 2026-10-22) |
| Jellyfin + Caddy single origin as the home-theater backend/proxy | SPEC architecture (not ADR-locked); avoids CORS and server code | Baseline (SPEC, revisitable) |
| Validate downloads with ffprobe inside Firecracker microVMs (not a hardened container) | User choice; strongest isolation for parsing untrusted files; KVM available on dev and required on production | Decided (user, 2026-10-21) |
| Production host: dedicated box with Ubuntu Server, KVM-capable | User decision; the laptop is only for development | Decided (user, 2026-10-21); exact model pending |
| Who puts downloads into Jellyfin naming layout (W1) | Options: portal post-download step, external library manager, relaxed Jellyfin requirement; decide on scan-test evidence | — Pending (Phase 3 decides, Phase 4 implements) |
| Shared media wiring contract (W2): host paths, PUID/PGID, incomplete folder, read-only mounts, libraries, rescan trigger | Neither doc specified it | Phase 1 part defined in docs/ports-and-media.md; Phase 4 rest pending |
| Laptop port map and whether Caddy also fronts the portal (W3) | Port 8080 ambiguity; Caddy port undefined | Port map defined in docs/ports-and-media.md; Caddy on port 80 fronts the portal since Phase 1 (D-03, D-04); Phase 3 adds Jellyfin and TV routes |
| Portal backend stack: FastAPI or Node | Spec says "FastAPI/Node" | FastAPI (D-01) — Decided (user, 2026-10-21) |
| TV frontend framework: Preact + Vite (proposed) or SolidJS | Decide after a grid prototype on the real TV | — Pending (Phase 5) |
| One shared Jellyfin user or separate profiles | Separate profiles are out of scope for now | — Pending (Phase 3) |
| Default audio and subtitle language | Open decision in home-theater.md | — Pending (Phase 3) |
| TV distribution: plan A (VIDAA icon tool) or plan B (HDMI stick + APK) | Plan A is unofficial and may break on firmware updates | — Pending (Phase 6) |
| Exact production box model | Must be x86_64 with VT-x + KVM for Firecracker; N100/N150 class also covers Jellyfin transcoding if Phase 3 needs it | — Pending (before Phase 6; informed by Phase 3 gate) |
| If and when to open access from outside home (Tailscale / WireGuard) | Out of scope for v1 | — Pending (v2) |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition:**
1. Requirements invalidated? Move to Out of Scope with reason
2. Requirements validated? Move to Validated with phase reference
3. New requirements emerged? Add to Active
4. Decisions to log? Add to Key Decisions
5. "What This Is" still accurate? Update if drifted

**After each milestone:**
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-10-21 after adding download filtering and Firecracker validation (Phase 2.1)*
