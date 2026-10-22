# Setup and admin guide

How to bring the Flatflix portal (search and download for the household) up on a
fresh machine, reach it from a phone, and keep it healthy. For ports and media
folders see [ports-and-media.md](ports-and-media.md); this guide only links to it.

Write `<laptop-ip>` wherever an address is needed. Never commit a real LAN
address, a password or the local `.env`.

## Prerequisites

- Dev laptop (Windows): Docker Desktop with WSL integration enabled for the
  distro you work in (Docker Desktop -> Settings -> Resources -> WSL
  integration, D-20). `docker compose version` must work inside the distro.
- Production box: Ubuntu Server with Docker Engine and the compose plugin.
- `uv` for the helper scripts and the backend tests.

## First run

1. Create the local env file from the template. Either copy it and edit every
   `change-me` value by hand:

   ```
   cp .env.example .env
   ```

   or let the helper fill random dev secrets (it also writes a random dev
   password to `.dev-portal-password`, gitignored):

   ```
   uv run --project backend --frozen python scripts/dev_env.py
   ```

2. Set the household password. The env file holds a hash, never the password
   (D-17):

   ```
   docker compose run --rm --no-deps backend python -m app.tools.hash_password
   ```

   Paste the printed line into `.env`, **keeping the single quotes**:

   ```
   APP_PASS_HASH='$argon2id$...'
   ```

   Without the quotes Compose swallows the `$` signs and the backend refuses to
   start with "APP_PASS_HASH is not an argon2id hash".

3. Create the host folders with the right owner (before the first `up`, or
   Docker creates them as root):

   ```
   bash scripts/init-host-dirs.sh
   ```

   `SAVE_PATH_FILM`, `SAVE_PATH_TV` and `INCOMPLETE_PATH` in `.env` must match
   the container mounts in `docker-compose.yml`; otherwise qBittorrent writes
   to a folder nothing scans. The defaults already match.

4. Start everything with one command:

   ```
   docker compose up -d --build --wait
   ```

5. Check that qBittorrent is configured the way the portal needs:

   ```
   docker compose exec -T backend python -m app.tools.doctor --wait 120
   ```

   Every line must start with `OK`. The first start installs the search plugins
   and sets the categories, so allow up to two minutes.

6. Optional end-to-end probe (log in, search, start one open-licensed film,
   scan every response for leaks):

   ```
   python3 scripts/smoke.py --base http://127.0.0.1 all
   ```

   It only ever starts the Blender open movies (Big Buck Bunny, Sintel, Tears
   of Steel, Elephants Dream, Cosmos Laundromat; CC BY). `doctor --torrents`
   lists what the portal has added.

## Phone access (D-04)

The phone opens `http://<laptop-ip>/`. Only Caddy is published to the LAN.

- Windows laptop with Docker Desktop: Docker Desktop publishes port 80 on
  Windows itself, so no `netsh portproxy` is needed. Allow inbound TCP 80 in
  Windows Defender Firewall for the **Private** profile only (never Public):

  ```
  netsh advfirewall firewall add rule name="Flatflix portal" dir=in action=allow protocol=TCP localport=80 profile=private
  ```

- If port 80 is already taken on the host, set `WEB_PORT` in `.env` (for
  example `WEB_PORT=8081`), restart with `docker compose up -d --wait`, and use
  `http://<laptop-ip>:8081/`.
- A native Docker Engine inside WSL (no Docker Desktop) is not reachable from
  the LAN by default: add a `netsh interface portproxy` rule to the WSL
  address or use WSL mirrored networking.
- Ubuntu Server: nothing extra. ufw does not filter Docker-published ports,
  which is why only Caddy is ever published (see
  [ports-and-media.md](ports-and-media.md)).
- Bookmark `http://<laptop-ip>/` on each phone. A stable address (DHCP
  reservation on the router) comes in Phase 3.

## Admin tasks

### qBittorrent WebUI

The WebUI is not on the LAN. To open it, on the laptop itself:

```
docker compose -f docker-compose.yml -f docker-compose.admin.yml up -d
```

It answers at `http://127.0.0.1:8088/` only. Return to the base stack with
`docker compose up -d`.

### Trusted search plugins (D-08, D-19)

The official plugins named in `SEARCH_PLUGINS` are installed automatically from
one reviewed commit of the official repo, pinned by `SEARCH_PLUGINS_REF`.
The portal searches with every plugin that is enabled and never re-enables one:
disable any you do not trust in WebUI -> Search -> Search plugins. Unofficial,
Italian-language or series-focused plugins and Jackett are a deferred idea;
add them by hand through the WebUI at your own judgement.

### Seeding policy (D-21)

A finished torrent seeds until ratio 1.0 or 24 hours, whichever comes first,
then stops. The files stay in place. Tune with `SHARE_RATIO_LIMIT` and
`SHARE_TIME_LIMIT_MINUTES`; the doctor checks that qBittorrent holds them.

### qBittorrent is pinned to 5.2.4 (D-22)

`docker-compose.yml` pins `lscr.io/linuxserver/qbittorrent:5.2.4`, never
`latest`. Before changing the tag, start the new image with the admin override
and run the opt-in guard against it:

```
QBIT_TEST_URL=http://127.0.0.1:8088 uv run --project backend --frozen pytest backend/tests/integration -m integration
```

Only raise `MIN_WEBAPI_VERSION` and the tag together after it passes.

### Login lockout

Two limits protect the one shared password, both counted over a 15-minute window
(`LOGIN_WINDOW_MINUTES`):

- **Per address:** five wrong logins (`LOGIN_MAX_ATTEMPTS`) from one source address block
  that address for the rest of the window. A correct login clears that address.
- **For everyone:** 20 wrong logins (`LOGIN_GLOBAL_MAX_ATTEMPTS`) from all addresses together
  block every address for the rest of the window. This keeps guesses spread over many
  addresses bounded, and it is the price of the trade-off: someone on the LAN who fails 20
  times locks the household out for up to 15 minutes. The login screen then says to wait.

The per-address limit only protects individual people when the backend sees each
client's real address. Caddy passes it in `X-Forwarded-For` and the backend believes that
header only from the `web` container (`TRUSTED_PROXY_HOSTS`); other containers are throttled
under their own address. When the host hides the real address (Docker Desktop and WSL2
userland proxying, a NAT in front of the box), every phone looks like the same address, and
five wrong attempts from anyone block the whole household. After the first start on the
Ubuntu server, check that separate phones get separate counters: fail five logins from one
phone and confirm another phone can still sign in.

To unlock immediately:

```
docker compose restart backend
```

### Downloads list

The Downloads tab shows every torrent in the Film and SerieTV categories, including
ones you added by hand in the qBittorrent WebUI. Torrents in any other category are
never shown and cannot be cancelled from the portal.

- **Finished downloads** leave the list `COMPLETED_VISIBLE_DAYS` days after they
  complete (default 7). Only the list entry goes: the files and the torrent stay.
- **Failed attempts** (for example a torrent with no video file) stay for
  `FAILED_VISIBLE_HOURS` hours (default 24). They live in the backend's memory, so a
  backend restart also clears them.
- **Cancel download** deletes the torrent and its partly downloaded files, after one
  confirm tap.
- **Remove from list**, on a finished download, removes the torrent but keeps the film
  on disk. It also ends seeding early for that torrent, whatever the seeding policy says.

The server, not the phone, decides whether files are deleted. It re-reads the torrent
when the tap arrives, so a download that finished a second earlier still keeps its film.
A row offers "Cancel download" only when the server would delete its partial files. Every
other download still in qBittorrent, including the rare finished one in an error state,
offers "Remove from list". Failed attempts offer no button.

### Rate limits

Each address may start `SEARCH_RATE_PER_MINUTE` searches (default 10) and
`DOWNLOAD_RATE_PER_MINUTE` downloads (default 20) per minute. Over the limit, the
phone shows "Too many requests. Wait a moment and try again." Status polling and the
Downloads list are never limited, and a backend restart clears the counters.

Like the login lockout, the limits count per client address. When the host hides real
addresses (Docker Desktop and WSL2 userland proxying, a NAT in front of the box), every
phone looks like the same address and the whole household shares one budget.

### Logs and audit trail

Everything is written to the containers' output, and Docker rotates it (json-file,
10 MB x 5 files per container). There is no log file or volume to clean up.

```
docker compose logs backend
docker compose logs backend | grep app.audit
```

Audit lines carry the logger name `app.audit` and plain `key=value` text. One example of
each kind (the address is from the documentation range):

```
INFO app.audit event=login ip=203.0.113.7 outcome=ok
INFO app.audit event=search ip=203.0.113.7 type=film q="Big Buck Bunny"
INFO app.audit event=download ip=203.0.113.7 type=film job_id=0d9707f6a78d2c7a name="Sintel.2010.1080p"
INFO app.audit event=download_done job_id=0d9707f6a78d2c7a name="Sintel.2010.1080p" outcome=started
INFO app.audit event=cancel ip=203.0.113.7 name="Sintel.2010.1080p" outcome=done
INFO app.audit event=throttled ip=203.0.113.7 scope=search
INFO app.audit event=error where=downloads ip=203.0.113.7 exc=QbitError status=500
```

The audit log contains what people searched for, the names of the downloads they started
or cancelled, and client addresses. Anyone with access to the laptop can read it, and
someone who types a secret into the search box puts it there. Passwords, password hashes,
session cookies, `SECRET_KEY` and the qBittorrent credentials are never written. A log filter
also blanks these secrets if one ever shows up in a log line, but only values of 8 or more
characters, so use a qBittorrent password of at least 8 characters. A failed
login records the outcome and the address only, never the username that was typed.

`LOG_LEVEL=WARNING` quiets the ordinary application lines but keeps the audit lines.

### Phones and new versions

After a redeploy, a plain reload on the phone loads the new portal. The page itself
(`index.html`) is revalidated on every load, while the hashed script and style files are
cached for a year because their names change with every build. Nobody needs to clear the
phone's cache.

## Where files go

Finished films land in `data/media/Film` and series in `data/media/SerieTV`
(or under `MEDIA_ROOT`); partial downloads stay in the incomplete folder until
they finish. See the media contract in [ports-and-media.md](ports-and-media.md).

## Troubleshooting

| Symptom | Likely cause and fix |
|---------|----------------------|
| `GET /api/health` answers `degraded` | Run the doctor and read the `FAIL` lines, then `docker compose logs backend`. |
| Backend exits with "APP_PASS_HASH is not an argon2id hash" | The hash line in `.env` lost its single quotes, or it is not an argon2id hash. Regenerate it (First run, step 2). |
| Doctor says qBittorrent refused access | Check the credentials from inside the container: `docker compose exec -T qbittorrent python3 - < scripts/qbit_login_check.py`. Fix `.env`, then `docker compose up -d --wait`. |
| Bootstrap stopped after wrong qBittorrent credentials | qBittorrent bans an address for an hour after five failed logins, so the backend stops retrying. Fix `.env` and restart: `docker compose restart backend`. |
| Phone cannot open the page | Windows firewall rule for TCP 80 on the Private profile, the right `<laptop-ip>`, and `WEB_PORT` if you changed it. |
| Everybody is locked out of the login | See "Login lockout" above. |
| Downloads tab says it can’t reach the download service | qBittorrent is down or restarting. The list retries every 5 seconds on its own and recovers when it is back. Check `docker compose ps` and `docker compose logs qbittorrent`. |
