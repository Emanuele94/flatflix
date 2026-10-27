# Ports and media folders

This is the one place that lists every port and the media-folder contract. The
compose files implement it; the infra invariant tests enforce it.

## Port map

| Service | Container port | Host publish | Notes |
|---------|----------------|--------------|-------|
| web (Caddy) | 80 | `${WEB_PORT:-80}` on the LAN | Portal at `/`, `/api/*` goes to the backend, `/jellyfin` and `/jellyfin/*` go to Jellyfin (D-80), `/tv/*` is reserved for Phase 5. The only service published to the LAN. |
| backend (FastAPI) | 8000 | not published | Reachable only on network `edge`. |
| qBittorrent WebUI | 8088 | not published; admin override `127.0.0.1:8088` only | Reachable by the backend on network `qbit`. |
| qBittorrent peers | 6881 tcp and udp | not published | Downloads work through outgoing connections. See "Peer port" below. |
| sandbox (runner) | 8090 | never published | Only on network `sandbox`; the backend calls it, and the opt-in real-sandbox tests go through `docker compose exec backend`. It has no login, so it must never be published. |
| Jellyfin | 8096 | never published; no admin override (D-82) | Only on network `jellyfin`; Caddy proxies `/jellyfin/*` with the BaseURL `/jellyfin`; the admin dashboard is reached through `/jellyfin` only. |

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
- `sandbox`: backend and the sandbox runner only. `internal: true`, so there is no
  Internet and no other service on it. The sandbox mounts only `quarantine`,
  read-only: it cannot see `media`, `rejected` or `incomplete`. It runs as uid
  10002 with the KVM group, no capabilities and a read-only root, and each probe
  boots a throwaway microVM that has no network device at all.

- `jellyfin`: web and jellyfin only. Not `internal: true`, because Jellyfin
  fetches posters and plots from TheMovieDb. The backend, qbittorrent and the
  sandbox are not on it (Phase 4 adds the backend only if it must call
  Jellyfin).

Docker-published ports bypass host firewalls such as ufw on the Ubuntu box
(Docker writes its own iptables rules). That is why nothing but web is ever
published, and why the admin override binds `127.0.0.1` only.

## Media folder contract

One host folder, `${DATA_ROOT:-./data}`, holds everything. The `qbittorrent` and
`backend` services each mount it once, at `/data` (a single bind each, so the
backend can hardlink a checked file without crossing a mount).

| Folder under `${DATA_ROOT:-./data}` | Container path | Purpose |
|-------------------------------------|----------------|---------|
| `media/Film`, `media/SerieTV` | `/data/media/Film`, `/data/media/SerieTV` | Checked files only, hardlinked here after the safety check. Jellyfin mounts only `media`, read-only, in Phase 4. |
| `quarantine/Film`, `quarantine/SerieTV` | `/data/quarantine/Film`, `/data/quarantine/SerieTV` | Finished downloads wait and seed here. These are the qBittorrent category save paths (`SAVE_PATH_FILM`, `SAVE_PATH_TV`). |
| `rejected` | `/data/rejected` | Files that failed the check. Owner-only (`0700`); purged after `REJECTED_RETENTION_DAYS`. |
| `incomplete` | `/data/incomplete` | Partial downloads (`INCOMPLETE_PATH`). |

- Owner is `PUID:PGID` (default 1000:1000); the backend runs as that user so it
  may hardlink qBittorrent's files. Jellyfin reuses the same owner later.
- `scripts/init-host-dirs.sh` creates the tree (and `qbittorrent/config`) with
  that owner before the first start, and checks that `KVM_GID` in `.env` equals
  the group of `/dev/kvm`. Run it before the first `docker compose up`, because
  Docker would create missing bind sources as root.
- Compose refuses to start when `DATA_ROOT` is missing (`create_host_path:
  false`), so a missing folder is a loud error, never a silent root-owned
  directory.
- The whole tree must sit on one filesystem on the Linux side, because the
  backend hardlinks checked files. On WSL that means never under `/mnt/c`.
  The backend never copies a file instead of linking it (D-48): a failed link
  is reported, not worked around.
- The settings in `.env` (`DATA_PATH`, `SAVE_PATH_*`, `INCOMPLETE_PATH`) are
  container paths and must stay inside `DATA_PATH`: a save path outside
  `DATA_PATH/quarantine` stops the backend at start, so no download can reach
  `media` without the check.

### Jellyfin folders

Apart from `DATA_ROOT`, in the repo folder (the whole `jellyfin/` folder is
gitignored):

- `./jellyfin/config`: Jellyfin's database and tokens.
- `./jellyfin/cache`: transcode segments and image cache.
- `./jellyfin/scratch`: mounted read-only, with `Movies`, `TV`, `Compat` and `Raw`
  (the Phase 3 test library, never the household's downloads).

`scripts/init-host-dirs.sh` creates them with the `PUID:PGID` owner and seeds
`jellyfin/config/config/network.xml` with the BaseURL `/jellyfin` only when that
file is absent. The media mount comes in Phase 4.

`jellyfin/config` and `jellyfin/cache` are mode `0700` (the script sets it on every
run): the database holds password hashes and access tokens, and Jellyfin runs as
`PUID:PGID`, the owner. The helper scripts that read `jellyfin/config/log` and
`jellyfin/config/metadata` must therefore run as the same user as `PUID`.

### One origin for the portal and Jellyfin

Caddy serves the portal and proxies Jellyfin at `/jellyfin` from the same origin (D-04: no
CORS, one address for phones and the TV). The cost is a known, accepted risk. Jellyfin's
policy has to allow inline script (`'unsafe-inline'`, see `web/Caddyfile`), and jellyfin-web
shows text that comes from TheMovieDb and from file names derived from torrent names. A script
injected through that text would run on the portal's origin, where the portal's own policy does
not apply. It could call `/api/*` with the household's session cookie (the browser sends it to
the same origin) and, for example, queue downloads or read the download list. It cannot read
qBittorrent or Jellyfin admin credentials: the backend keeps those, and the cookie is not
readable by script if it is `HttpOnly`.

If the risk stops being acceptable, the options are, from cheapest: scope the portal session
cookie to `Path=/api` so `/jellyfin` pages cannot send it; or serve Jellyfin from its own port
or host name (this gives up D-04 and needs CORS or a second address for the TV app). The CSP
split in `web/Caddyfile` is pinned by `infra/tests/test_caddyfile.py`; do not loosen the portal
policy to fix a Jellyfin page.

### Notes for later phases

- When some files of a torrent are skipped, qBittorrent can leave a hidden
  `.<hash>.parts` file next to the content. The checker ignores `.<hash>.parts`
  and every other dotfile; Phase 4 must do the same when it scans.
- Where an address is needed in docs or config, write `<laptop-ip>`; never
  commit a real LAN address.
