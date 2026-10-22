# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

The portal part (Phase 1) exists: FastAPI backend in `backend/`, Preact + Vite frontend in `frontend/`, Caddy, qBittorrent and compose files at the repo root. The home-theater part is still design only (`home-theater.md`). Setup and admin guide: `docs/setup.md`; ports and media folders: `docs/ports-and-media.md`. Commands, run from the repo root:

- Backend tests: `uv run --project backend --frozen pytest backend/tests -q`
- Infra tests: `uv run --project backend --frozen pytest infra/tests -q`
- Frontend tests: `npm --prefix frontend ci && npm --prefix frontend test`
- Frontend build: `npm --prefix frontend run build`
- Dev env (random secrets into `.env`): `uv run --project backend --frozen python scripts/dev_env.py`
- Host folders: `bash scripts/init-host-dirs.sh`
- Run the stack: `docker compose up -d --build --wait`
- Doctor: `docker compose exec -T backend python -m app.tools.doctor --wait 120`
- End-to-end probe: `python3 scripts/smoke.py --base http://127.0.0.1 all` (downloads only Blender open movies)
- Real-engine guard (opt-in, needs `docker-compose.admin.yml`): `QBIT_TEST_URL=http://127.0.0.1:8088 uv run --project backend --frozen pytest backend/tests/integration -m integration`

Public open source repo (MIT): https://github.com/Emanuele94/flatflix. Do not commit secrets, LAN IPs, or real credentials.

## The two parts

Both run in Docker on a home laptop on the LAN, used by non-technical household members.

1. **Home theater** (`home-theater.md`): TV app for a Hisense TV (VIDAA OS).
   - Backend is stock **Jellyfin**: configure it, write no server code. **Caddy** serves the frontend and reverse-proxies Jellyfin API and video from one origin, so there is no CORS.
   - The only custom code is the frontend. Proposed stack: **Preact + Vite** with spatial navigation (Norigin or preact-spatial-navigation) and a legacy/transpiled build for the old VIDAA browser. SolidJS is the fallback; the framework choice is still open.
   - Screens: Home, Library, Detail, Player. Remote-only input: arrows, OK, Back, Play/Pause.
   - Playback must avoid video transcoding. Send a TV device profile to `PlaybackInfo`; remuxing or audio-only transcoding is fine.
   - Keep it a pure web app with no VIDAA-specific APIs, so it can later be wrapped as an APK (plan B).
   - Phases 1–2 (Jellyfin setup, codec tests on the real TV) come before any frontend code.

2. **qBittorrent wrapper** (`qbit-wrapper.md`): mobile-friendly self-service portal to search and download films and series.
   - Frontend → own backend → qBittorrent Web API v2, using its search plugins. The backend is FastAPI (D-01); the frontend is Preact + Vite, served by Caddy on port 80 (D-03, D-04).
   - The backend owns the qBittorrent credentials and session cookie. The browser never sees them, nor any save path.
   - The frontend sends only `type` (`film` | `serie`), which maps to category `Film` → `/media/Film` or `SerieTV` → `/media/SerieTV`.
   - Config comes from env vars (see the doc §12). The app has its own login, separate from qBittorrent.

## Download safety and hosts

- Only video and subtitle files may be downloaded: a qBittorrent exclusion list plus a per-file allowlist. Torrents are added with `stopCondition=MetadataReceived` (they stop themselves as soon as metadata arrives, before any file data; a magnet added fully stopped never fetches metadata), the file list is filtered, and only then are they started (D-23, Phase 1).
- Completed downloads go to a quarantine folder. ffprobe checks them inside a throwaway Firecracker microVM, and only passing files move to the media folders (Phase 2.1).
- This laptop (WSL2, `/dev/kvm` available) is the dev machine only. Production will be a dedicated KVM-capable x86_64 box running Ubuntu Server. Anything host-specific must work on both.

## Planning

GSD planning lives in `.planning/` (`ROADMAP.md`, `REQUIREMENTS.md`, `STATE.md`). Phase order: 1 → 2 → 2.1 → 3 → 4 → 5 → 6.

## Cross-part constraints

- qBittorrent writes into the folders that Jellyfin scans. Jellyfin needs `Title (Year)/Title (Year).mkv` and `Series/Season 01/Series S01E01.mkv`, while torrent names won't match. Renaming or organizing files is an unsolved gap between the two parts.
- The compose example in `qbit-wrapper.md` uses port 8080 both for the frontend and for qBittorrent's WebUI. Resolved by the one port map in `docs/ports-and-media.md` (no service uses 8080).
