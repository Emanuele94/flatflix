# Setup and admin guide

How to bring the Flatflix portal (search and download for the household) up on a
fresh machine, reach it from a phone, and keep it healthy. For ports and media
folders see [ports-and-media.md](ports-and-media.md); this guide only links to it.

Write `<laptop-ip>` wherever an address is needed. Never commit a real LAN
address, a password or the local `.env`.

## Prerequisites

Every download is checked in a throwaway microVM (Firecracker) before it reaches the media
folders, so both machines need an **x86_64 CPU with virtualization switched on** and a working
`/dev/kvm`. A Raspberry Pi or any ARM board cannot run the safety check.

- Dev laptop (Windows): Docker Desktop with WSL integration enabled for the
  distro you work in (Docker Desktop -> Settings -> Resources -> WSL
  integration, D-20). `docker compose version` must work inside the distro.
  Virtualization must be on in the BIOS, and WSL2 needs nested virtualization so
  `/dev/kvm` exists in the distro: `ls -l /dev/kvm` must list a device. Docker Desktop
  passes it on to the sandbox container.
- Production box (Ubuntu Server, x86_64 only): Docker Engine and the compose plugin from
  Docker's apt repository (not the distro's `docker.io` package), then check virtualization:

  ```
  sudo apt install cpu-checker
  kvm-ok
  uname -r
  ```

  `kvm-ok` must say "KVM acceleration can be used". Note the kernel from `uname -r`:
  Firecracker validates host kernels 5.10, 6.1 and 6.18; other versions are expected to
  work but are not validated.
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

   It creates the whole `DATA_ROOT` tree (`media`, `quarantine`, `rejected`,
   `incomplete`) and checks that `KVM_GID` in `.env` equals the group of `/dev/kvm`
   (`dev_env.py` filled it in step 1; `stat -c %g /dev/kvm` prints the real one).
   `SAVE_PATH_FILM`, `SAVE_PATH_TV` and `INCOMPLETE_PATH` in `.env` must match
   the container mounts in `docker-compose.yml`; otherwise qBittorrent writes
   to a folder nothing scans. The defaults already match.

4. Start everything with one command:

   ```
   docker compose up -d --build --wait
   ```

   The first build also compiles the sandbox kernel: about 8 minutes on the dev laptop
   and longer on a small box (an N100 takes noticeably more). Later builds reuse the cache.

5. Check that qBittorrent and the sandbox are set up the way the portal needs:

   ```
   docker compose exec -T backend python -m app.tools.doctor --wait 120
   ```

   Every line must start with `OK`. The first start installs the search plugins
   and sets the categories, so allow up to two minutes. The doctor also checks the
   sandbox (see "The doctor's sandbox lines" below).

6. Optional end-to-end probe (log in, search, start one open-licensed film,
   scan every response for leaks):

   ```
   python3 scripts/smoke.py --base http://127.0.0.1 all
   ```

   It only ever starts the Blender open movies (Big Buck Bunny, Sintel, Tears
   of Steel, Elephants Dream, Cosmos Laundromat; CC BY). `doctor --torrents`
   lists what the portal has added. `all` follows one film through Checking to
   Ready and Remove, which needs a lowered film minimum: see "Tests and the smoke
   probe" below.

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

Everything lives under one host folder, `DATA_ROOT` (default `./data`):

- `quarantine/Film` and `quarantine/SerieTV`: finished downloads wait and seed here until the
  safety check passes.
- `media/Film` and `media/SerieTV`: checked films and series, hardlinked from quarantine.
  Nothing else writes here.
- `rejected`: files that failed the check, owner-only, purged after `REJECTED_RETENTION_DAYS`.
- `incomplete`: partial downloads.

See the media contract in [ports-and-media.md](ports-and-media.md). All of it must be on one
filesystem on the Linux side (never `/mnt/c` on WSL), because the hand-off is a hardlink and
the backend never copies.

## Upgrading from Phase 2

Phase 2 saved films straight into `media`. From now on they wait in quarantine first.

1. Pull the new version and add the new keys: `uv run --project backend --frozen python scripts/dev_env.py`
   (it adds what is missing and fills `KVM_GID`; it never overwrites a value).
2. In `.env` set `SAVE_PATH_FILM=/data/quarantine/Film`, `SAVE_PATH_TV=/data/quarantine/SerieTV`
   and `INCOMPLETE_PATH=/data/incomplete`, and delete the two old host-path keys
   (`MEDIA_ROOT` and the old incomplete host path). `DATA_ROOT` is the one host folder now.
3. `bash scripts/init-host-dirs.sh`, then `docker compose up -d --build --wait`.
4. Move your existing films if they sit in an old folder: they must end up under
   `DATA_ROOT/media/Film` and `DATA_ROOT/media/SerieTV`. Films already in media are not
   re-checked (D-49).
5. Open the qBittorrent WebUI (admin override, see "qBittorrent WebUI") and remove every
   Phase 1-2 torrent from the Film and SerieTV categories with **"Also delete the files"
   unchecked** (D-79). The films stay in media. A torrent that still saves outside
   quarantine is never checked, and the doctor's `note:` line counts them; it should
   read 0 when you are done.
6. Run the doctor again: every line `OK`.

## Safety check of finished downloads

What the household sees on the Downloads tab:

- **Checking...** a finished download is being looked at. It takes a few minutes.
- **Ready** the film passed and is in the library.
- **Ready with a note** the film passed but some extra files (a sample, an unwanted file) were left out.
- **Didn't pass the safety check** the file was held back and the download removed. The tab shows
  it for 24 hours.
- **Problem** the check has been waiting longer than `CHECKING_PROBLEM_HOURS` (default 6), usually
  because the sandbox is down. Nothing is lost.

The rules, in plain words. A video file passes only when its container matches its extension, it
holds a real video stream, it runs at least `MIN_FILM_DURATION_MINUTES` (film, default 40) or
`MIN_EPISODE_DURATION_MINUTES` (episode, default 10), and its size is plausible for its length
(`MIN_BITRATE_KBPS` to `MAX_BITRATE_KBPS`). Subtitles are screened by size and content without
starting a VM (`SUBTITLE_TEXT_MAX_MB`, `SUBTITLE_BITMAP_MAX_MB`).

How it runs. Each video gets its own microVM: no network, the file mounted read-only, 1 vCPU,
256 MiB and 60 seconds (`VM_VCPUS`, `VM_MEMORY_MIB`, `VM_TIMEOUT_SECONDS`). A crash or a timeout
is retried once. A failing file is hardlinked into `DATA_ROOT/rejected` (owner-only) and purged
after `REJECTED_RETENTION_DAYS` (default 7); the torrent is removed at once. A passing file is
hardlinked into `media`. A torrent that finished seeding is removed from qBittorrent and the film
stays in media, because the media name is a second link to the same data.

When the sandbox is down nothing is lost and nothing is let through: rows wait in Checking and
the check resumes by itself when the sandbox is back. There is no copy fallback and no bypass.

### Audit events

```
docker compose logs backend | grep quarantine.
```

| Event | Meaning |
|-------|---------|
| `quarantine.passed` | A torrent passed; `files=` counts the files linked into media. |
| `quarantine.rejected` | A file failed: `reason`, `format`, `codec`, `duration`, `size`, `ffmpeg`. The reason is a short code such as `too_short` or `no_video_stream`. |
| `quarantine.runner_unavailable` | The sandbox could not be used (`why=`). Written once per outage. |
| `quarantine.link_failed` | A hardlink failed (`why=` an error name such as `EXDEV`). Nothing was copied or deleted. |
| `quarantine.purged` | Held files older than the retention were removed (`count=`). |
| `quarantine.seeding_done` | A verified torrent finished seeding and left qBittorrent. |

Lines carry names, counts and short codes, never a path or a hash.

### Releasing a false rejection by hand (D-59)

If a good file was rejected (a short film under the minimum, say), within `REJECTED_RETENTION_DAYS`:

1. Find it: `ls DATA_ROOT/rejected`. Each held torrent is a folder `DATA_ROOT/rejected/<id>/`
   with a `<id>.json` next to it that holds the display name. The audit line
   `quarantine.rejected name=... file=...` tells you which one.
2. As the `PUID` user (the same owner as the data folders), move the file into the matching
   media folder and keep the file readable:

   ```
   mv "DATA_ROOT/rejected/<id>/<file>" "DATA_ROOT/media/Film/<file>"
   chmod 0644 "DATA_ROOT/media/Film/<file>"
   ```

   Use `media/SerieTV` for a series. Held files are mode 0600, so without the `chmod` Jellyfin
   could not read it later.
3. To stop it happening again for films of that kind, lower the minimum in `.env` and run
   `docker compose up -d backend`.

### The doctor's sandbox lines

`docker compose exec -T backend python -m app.tools.doctor --wait 120` prints, after the
qBittorrent lines:

- `sandbox runner reachable, kvm True, firecracker ..., kernel ..., ffmpeg ...`
- `sandbox selftest ok` (a real VM booted on a clip baked into the image)
- `quarantine and media are on one filesystem` and `hardlink quarantine -> media works`
- `N file(s) held in rejected (purged after 7 days)`
- `note: N Film/SerieTV torrent(s) save outside quarantine and are never checked`

A sandbox that is down, has no usable `/dev/kvm` or fails its selftest prints `FAIL` and the doctor
exits 1; the qBittorrent lines are still printed.

### Tuning

The verifier keys live in `.env.example` with a comment each: `MIN_FILM_DURATION_MINUTES`,
`MIN_EPISODE_DURATION_MINUTES`, `MIN_BITRATE_KBPS`, `MAX_BITRATE_KBPS`, `SUBTITLE_TEXT_MAX_MB`,
`SUBTITLE_BITMAP_MAX_MB`, `PROBE_TIMEOUT_SECONDS`, `VERIFY_POLL_SECONDS`,
`REJECTED_RETENTION_DAYS`, `CHECKING_PROBLEM_HOURS`. The VM limits are `VM_VCPUS`, `VM_MEMORY_MIB`
and `VM_TIMEOUT_SECONDS`. A `VM_MEMORY_MIB` above about 500 needs a higher `mem_limit` on the
`sandbox` service in `docker-compose.yml`. Run `docker compose up -d` after any change.

### Updating the sandbox pins

Everything the sandbox runs is pinned in `sandbox/Dockerfile`:

- `FIRECRACKER_VERSION` and `FIRECRACKER_SHA256`: take the sha256 from the release's
  `.sha256.txt` file on the Firecracker release page.
- `KERNEL_VERSION` and `KERNEL_SHA256`: take the sha256 from kernel.org's `sha256sums.asc`.
- `FFMPEG_APK_VERSION`: the exact Alpine package revision. When Alpine publishes a new one the
  build stops with an apk "unable to select" error (D-73 keeps the exact pin on purpose); raise it
  to the new revision.

Then `docker compose build sandbox`, `docker compose up -d --wait`, the doctor, and the opt-in
sandbox suite below.

### Tests and the smoke probe

- Sandbox unit tests (no VM): `uv run --project backend --frozen pytest sandbox/tests -q`
- Opt-in real-sandbox suite (needs the running stack and `ffmpeg` on the host to make clips):

  ```
  SANDBOX_TEST=1 uv run --project backend --frozen pytest backend/tests/sandbox_real -m sandbox -q -rs
  ```

  Every test must run; a skipped one means the setup is incomplete.
- `python3 scripts/smoke.py --base http://127.0.0.1 all` starts one Blender open movie and follows it
  Downloading, Checking, Ready, then removes it from the list and confirms the film is still in
  `media/Film`. The Blender films run about 10-15 minutes, so the default 40-minute film minimum would
  reject them: set `MIN_FILM_DURATION_MINUTES=5` in `.env`, run `docker compose up -d backend`, run the
  probe, then set it back to 40 and run `docker compose up -d backend` again. The probe refuses to
  start while the value is above 5. It leaves one copy of the film in `media/Film` per run, exits 2
  with `SKIP handoff` when every open film is already in qBittorrent (remove it from the Downloads
  tab and run again), and a download can take many minutes (`--ready-timeout`, default 3600 s).

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
| Doctor: `sandbox cannot use /dev/kvm` | `KVM_GID` in `.env` is not the group of `/dev/kvm` (`stat -c %g /dev/kvm`), or virtualization is off. Fix it, run `bash scripts/init-host-dirs.sh`, then `docker compose up -d --force-recreate sandbox`. On WSL2 check that `ls -l /dev/kvm` shows a device. |
| Doctor: `sandbox runner not reachable` | The sandbox container is down: `docker compose ps`, `docker compose logs sandbox`, then `docker compose up -d --wait`. |
| Doctor: `sandbox selftest failed (...)` | The VM could not boot. `docker compose logs sandbox` names the cause; a kernel or Firecracker change needs `docker compose build sandbox`. |
| Downloads stay in "Checking..." | The sandbox is down or the folders are on two filesystems. Run the doctor: it names which. Rows wait and resume by themselves; after `CHECKING_PROBLEM_HOURS` they read "Problem". |
| Doctor: `quarantine and media are on different filesystems` | `DATA_ROOT` spans two filesystems (a second mount inside it, or `/mnt/c` on WSL). Put the whole tree on one Linux filesystem; the backend never copies. |
