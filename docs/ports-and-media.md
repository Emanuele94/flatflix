# Ports and media folders

This is the one place that lists every port and the media-folder contract. The
compose files implement it; the infra invariant tests enforce it.

## Port map

| Service | Container port | Host publish | Notes |
|---------|----------------|--------------|-------|
| web (Caddy) | 80 | `${WEB_PORT:-80}` on the LAN | Portal at `/`, `/api/*` goes to the backend, `/tv/*` is reserved for Phase 5, `/jellyfin/*` is reserved for Phase 3. The only service published to the LAN. |
| backend (FastAPI) | 8000 | not published | Reachable only on network `edge`. |
| qBittorrent WebUI | 8088 | not published; admin override `127.0.0.1:8088` only | Reachable by the backend on network `qbit`. |
| qBittorrent peers | 6881 tcp and udp | not published | Downloads work through outgoing connections. See "Peer port" below. |
| Jellyfin | 8096 | reserved for Phase 3 | Reached through Caddy, never published directly. |

No service uses 8080. That resolves the clash in `qbit-wrapper.md` section 11,
where 8080 served both the frontend and the qBittorrent WebUI.

(`docker compose ps` still lists `8080/tcp` for qBittorrent: that is only the
image's built-in EXPOSE metadata. `WEBUI_PORT=8088` moves the real listener and
nothing is published.)

`QBITTORRENT_URL` must use the `WEBUI_PORT` value (`http://qbittorrent:8088`).
Keep the container and host numbers equal: the linuxserver image warns about
CSRF problems when they differ.

### Admin access to the qBittorrent WebUI

```
docker compose -f docker-compose.yml -f docker-compose.admin.yml up -d
```

The WebUI then answers at `http://127.0.0.1:8088/` on the laptop itself, and
only there. When done, return to the base stack with `docker compose up -d`;
`docker compose port qbittorrent 8088` then prints nothing.

### Peer port

Peer port 6881 is left unpublished. Torrents still download through outgoing
connections, with fewer reachable peers and slower speeds for rare content.
To accept incoming peers, add `6881:6881` and `6881:6881/udp` to the
`qbittorrent` service. This exposes the peer port on every LAN address of the
host (and to the Internet if the router forwards it), so decide that
deliberately.

## Networks

- `edge`: web and backend.
- `qbit`: backend and qbittorrent. Not `internal: true`, because search plugins
  and peers need Internet egress. Isolation comes from network membership and
  from publishing no ports.

Docker-published ports bypass host firewalls such as ufw on the Ubuntu box
(Docker writes its own iptables rules). That is why nothing but web is ever
published, and why the admin override binds `127.0.0.1` only.

## Media folder contract

| Host path | Container path | Purpose |
|-----------|----------------|---------|
| `${MEDIA_ROOT:-./data/media}/Film` | `/media/Film` | Finished films (category `Film`) |
| `${MEDIA_ROOT:-./data/media}/SerieTV` | `/media/SerieTV` | Finished series (category `SerieTV`) |
| `${INCOMPLETE_DIR:-./data/incomplete}` | `/incomplete` | Partial downloads; qBittorrent keeps them in `/incomplete/<Category>` |

- Owner is `PUID:PGID` (default 1000:1000). Jellyfin reuses the same owner later.
- `scripts/init-host-dirs.sh` creates the folders (and `qbittorrent/config`)
  with that owner before the first start. Run it before the first
  `docker compose up`, because Docker would create missing bind sources as root.
- Compose refuses to start when a folder is missing (`create_host_path: false`),
  so a missing folder is a loud error, never a silent root-owned directory.
- `INCOMPLETE_DIR` lives outside `MEDIA_ROOT` so Jellyfin (read-only mount of
  `MEDIA_ROOT` in Phase 4) never sees partial files. Moving a finished download
  crosses two bind mounts, so qBittorrent copies and deletes instead of renaming.

### Notes for later phases

- Phase 2.1 changes the qBittorrent save paths to quarantine folders through
  env (introduced in 01-06).
- When some files of a torrent are skipped, qBittorrent can leave a hidden
  `.<hash>.parts` file next to the content. Phase 2.1 and Phase 4 must ignore
  dotfiles when moving or scanning.
- Where an address is needed in docs or config, write `<laptop-ip>`; never
  commit a real LAN address.
