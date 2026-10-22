---
phase: 01-portal-search-start-download
reviewed: 2026-10-22T00:00:00Z
depth: standard
files_reviewed: 76
files_reviewed_list:
  - .dockerignore
  - .env.example
  - .gitignore
  - backend/.dockerignore
  - backend/Dockerfile
  - backend/app/__init__.py
  - backend/app/auth.py
  - backend/app/config.py
  - backend/app/content_type.py
  - backend/app/download/__init__.py
  - backend/app/download/allowlist.py
  - backend/app/download/jobs.py
  - backend/app/download/pipeline.py
  - backend/app/main.py
  - backend/app/qbit/__init__.py
  - backend/app/qbit/bootstrap.py
  - backend/app/qbit/client.py
  - backend/app/routers/__init__.py
  - backend/app/routers/auth.py
  - backend/app/routers/download.py
  - backend/app/routers/health.py
  - backend/app/routers/search.py
  - backend/app/search/__init__.py
  - backend/app/search/filters.py
  - backend/app/search/service.py
  - backend/app/tools/__init__.py
  - backend/app/tools/doctor.py
  - backend/app/tools/hash_password.py
  - backend/pyproject.toml
  - backend/tests/conftest.py
  - backend/tests/fakeqbit.py
  - backend/tests/integration/__init__.py
  - backend/tests/integration/conftest.py
  - backend/tests/integration/test_real_qbit.py
  - backend/tests/test_allowlist.py
  - backend/tests/test_auth.py
  - backend/tests/test_bootstrap.py
  - backend/tests/test_config.py
  - backend/tests/test_download_pipeline.py
  - backend/tests/test_filters.py
  - backend/tests/test_health.py
  - backend/tests/test_login_throttle.py
  - backend/tests/test_no_leaks.py
  - backend/tests/test_qbit_client.py
  - backend/tests/test_routes_protected.py
  - backend/tests/test_search_flow.py
  - backend/tests/test_validation.py
  - docker-compose.admin.yml
  - docker-compose.yml
  - docs/ports-and-media.md
  - frontend/.npmrc
  - frontend/index.html
  - frontend/package.json
  - frontend/src/App.jsx
  - frontend/src/Login.jsx
  - frontend/src/ResultRow.jsx
  - frontend/src/Search.jsx
  - frontend/src/__tests__/App.test.jsx
  - frontend/src/__tests__/Login.test.jsx
  - frontend/src/__tests__/ResultRow.test.jsx
  - frontend/src/__tests__/Search.test.jsx
  - frontend/src/__tests__/no-third-party.test.js
  - frontend/src/api.js
  - frontend/src/main.jsx
  - frontend/src/messages.js
  - frontend/src/styles.css
  - frontend/vite.config.js
  - infra/tests/test_compose_invariants.py
  - infra/tests/test_repo_hygiene.py
  - qbittorrent/custom-cont-init.d/10-credentials.sh
  - scripts/dev_env.py
  - scripts/init-host-dirs.sh
  - scripts/qbit_login_check.py
  - scripts/smoke.py
  - web/Caddyfile
  - web/Dockerfile
findings:
  critical: 1
  warning: 7
  info: 7
  total: 15
status: issues_found
---

# Phase 1: Code Review Report

**Reviewed:** 2026-10-22
**Depth:** standard
**Files Reviewed:** 76
**Status:** issues_found

## Summary

The backend, frontend, compose and Caddy configuration were read in full. Tests were skimmed for false-green risk. I also ran `pytest` in `backend` (298 passed), `pytest infra/tests` (59 passed) and `vitest` (100 passed). Passing tests do not cover the findings below.

The browser-facing surface is well contained. The routes expose whitelisted fields only and `extra="forbid"` bodies. `require_user` is applied at router level, with a test that guards it. Only `web` publishes a port. Pydantic validates the category and path settings.

The main problems are in the download pipeline's failure and restart paths and in what the tests prove.

- **One blocker:** `reconcile()` can delete a running download together with its files.
- **Warnings:**
  - A stuck torrent is reported to the user as "Already added".
  - The `*` trust setting on `X-Forwarded-For` lets the `qbit` network spoof throttle keys.
  - Plugin-supplied URLs reach qBittorrent with no scheme check.
  - The safety claim for non-magnet results rests on tests that never ran against real qBittorrent.
  - The UI can leave a row on "Preparing" forever.
  - Readiness is never re-checked.

## Critical Issues

### CR-01: `reconcile()` deletes a running download and its files when the pending tag was left behind

**File:** `backend/app/download/pipeline.py:192-200` and `:246-250`
**Issue:** After `start()` succeeds, the job sets `STARTED` and only then removes the `fx-pending` tag. If that cleanup fails, the torrent is running (or finished) but still carries `fx-pending`. The code comment accepts this: "a leftover tag only makes the next reconcile run the same allowlist again". Cleanup can fail through a `QbitError`, or through task cancellation at shutdown (`JobRegistry.shutdown()` cancels running tasks, and `await` is a cancellation point inside `remove_tags`).

`reconcile()` does not re-run the allowlist for such a torrent. It checks `now - added_on > timeout` first. A torrent added more than 300 s ago is passed to `_discard()`, which calls `qbit.delete(..., delete_files=True)`. This is the normal case for a download that has been running for a while. On the next backend restart, a running or completed download, and every byte already fetched, is deleted. `added_on` is the add time, not the filter time, so a started torrent looks identical to one that never got metadata.

The tests cover "expired pending, never filtered" (`stranded(... age=301)`). They never cover a started torrent that still has the tag.

**Fix:** Only auto-delete a torrent that was never started. Otherwise let the allowlist re-run, which is idempotent.
```python
STOPPED_STATES = {"stoppedDL", "pausedDL", "metaDL", "forcedMetaDL"}

started = str(row.get("state")) not in STOPPED_STATES or float(row.get("downloaded") or 0) > 0
if now - added_on > timeout and not started:
    await self._discard(torrent_hash, job_tag or TAG_JOB_PREFIX)
    continue
# else: fall through to _process(...), which re-filters and (re)starts; deadline for a
# started torrent should be `now` (the file list already exists).
```
Also remove `fx-pending` *before* `STARTED`, or retry tag removal, so the leftover-tag window shrinks. Add a test for a started torrent that still carries `fx-pending` and is older than `METADATA_TIMEOUT`.

## Warnings

### WR-01: A job that fails after the add leaves a stopped torrent, and the next tap reports "Already added"

**File:** `backend/app/download/pipeline.py:108-119`, `:127-129`
**Issue:** `_settle` turns any `QbitError`/`ValueError` after the add into `FAILED` and keeps the `fx-pending` tag. The comment says "a restart cleans up". The torrent is stopped (stop condition) and sits in qBittorrent. In-process `reconcile()` is skipped for it, because the registry still owns the id. When the user taps Download again, `torrents_info(hashes=digest)` finds the torrent and the job becomes `DUPLICATE`. The UI says "Already added" for a download that will never run, until the backend restarts. A transient qBittorrent 5xx during `set_file_priority` is enough. `test_a_qbittorrent_error_midway_fails_the_job_and_keeps_the_pending_tag` pins this behavior instead of questioning it.

**Fix:** On a post-add failure, try a best-effort `_discard()` in `_settle`, which is safe because nothing has started. Alternatively, in the duplicate check, treat a torrent that carries `fx-pending` as resumable and re-run `_process` on it instead of answering `DUPLICATE`.

### WR-02: `--forwarded-allow-ips "*"` lets any container on the `qbit` network spoof the throttle key

**File:** `backend/Dockerfile:25`, `docker-compose.yml:37`, `backend/app/routers/auth.py:27`
**Issue:** uvicorn trusts `X-Forwarded-For` from every peer, and with `*` it takes the leftmost entry. The backend is attached to the `qbit` network, which also holds the qBittorrent container. That container parses untrusted torrents and runs search-plugin Python, and the network has Internet egress. It can reach `backend:8000` directly and send a different `X-Forwarded-For` on every login attempt. The per-IP `LoginThrottle` is then bypassed, giving unlimited password guesses. The shared account's only brute-force defense is this throttle. The `_attempts` dict also grows without bound under spoofed IPs, because it is pruned only when the same IP returns.

Caddy itself is fine: by default it overwrites `X-Forwarded-For` from untrusted clients. The problem is the second network path, which no test or doc covers.

**Fix:** Trust only the Caddy peer. Pin a subnet for `edge` in compose and pass `--forwarded-allow-ips=<web container IP or edge subnet>`, or run the backend with `--no-proxy-headers` and read a header that only Caddy sets (`header_up X-Real-IP {remote_host}`) after checking the peer. Alternatively, keep the backend off the `qbit` network by routing qBittorrent traffic through a dedicated internal network. Add a test with a non-Caddy peer address that sends `X-Forwarded-For`.

### WR-03: Untrusted plugin `fileUrl` is passed to qBittorrent/plugin downloader without a scheme check

**File:** `backend/app/search/filters.py:77`, `backend/app/qbit/client.py:284-295`, `backend/app/download/pipeline.py:124-136`
**Issue:** The module doc calls result URLs untrusted, but nothing restricts them. `file_url` goes straight into `torrents/add` as `urls`. For a non-magnet URL, qBittorrent or the engine's `nova2dl` fetches it from inside the container. A hostile or compromised indexer can return `http://<lan host or qbittorrent:8088>/...`, `file://...` or `ftp://...`. That gives blind SSRF from a container on the household network, and file-scheme reads where the downloader allows them. The only check is "no newline". The `engine` string is also forwarded as `downloader` unvalidated; the allowlist in `config` (`SEARCH_PLUGINS`) is not used to constrain it.

**Fix:** In `normalize_and_filter` (or at `get_result` time), accept only `magnet:` or `http(s)://` URLs, and reject http(s) hosts that resolve to private, loopback or link-local addresses. Reject results whose `engine` is not in `settings.search_plugin_names`.

### WR-04: The "stop before any payload" guarantee for non-magnet results is unproven

**File:** `backend/tests/integration/test_real_qbit.py:88-130`, `:146-157`, `backend/tests/fakeqbit.py:320-370`
**Issue:** Three gaps in what the tests prove:
- **Magnet test never asserts the evidence.** The only real-qBittorrent test of the pipeline (Sintel magnet) records `downloaded` just before `start` but never asserts it equals 0. `record_property` and `print` are the only uses of `evidence[0]`. It cannot fail on the property it was written to prove.
- **Non-magnet path has no real test.** The "plugin page URL / .torrent" path (`downloader=engine`) is never exercised against real qBittorrent. A torrent added from a fetched `.torrent` has metadata at add time. Whether `stopCondition=MetadataReceived` stops it before any piece request is exactly the open question, and the code assumes yes.
- **Synthetic test bypasses the pipeline.** It adds with `stopped=true`, not the pipeline's `stopCondition` form.
- **Fake ignores the stop condition.** `FakeQbit` does not model `stopCondition` at all, so the 298 backend tests cannot detect start-before-filter.

If qBittorrent ignores the stop condition for a torrent that already has metadata, payload downloads before the allowlist. The exclusion list still blocks `.exe` and similar, but not `.mkv`-named content or a large video before filtering.

**Fix:** Assert `evidence[0] == 0` and add a real-engine test of the downloader or `.torrent` path that asserts the torrent is stopped with `downloaded == 0` before `start`. Have the fake mark non-stopped torrents as downloading, and fail if `start` is the first transition. Alternatively, for non-magnet adds, add with `stopped=true` and let the pipeline start after filtering.

### WR-05: Rows can stay on "Preparing" forever (job gone after restart, 404/401, or give-up)

**File:** `frontend/src/Search.jsx:8`, `:108-114`
**Issue:** `pollJob` stops silently on 404 or 401 and after `JOB_GIVE_UP_MS`, but the row state stays `preparing`. `LOCKED_LABEL.preparing` renders a disabled button, so the user has no way to retry short of a new search. Jobs live only in memory, so any backend restart turns a polled job into a 404. After a restart, `reconcile()` resumes the torrent under a *different* job id, so the client cannot find it. The household sees a permanent spinner.

**Fix:** On 404 or give-up, set the row to a retryable state, for example `{state: 'failed'}` or a new `lost` state mapped to a retry message. A retry then hits the server-side duplicate or dedupe path. On 401 the login screen already takes over.

### WR-06: Readiness is checked once; later qBittorrent config drift is not detected

**File:** `backend/app/qbit/bootstrap.py:124-132`, `backend/app/routers/download.py:34`
**Issue:** `require_ready` only checks a flag set once at start-up. If qBittorrent is recreated with a reset config, or an admin disables the exclusion list or edits a category's save path in the WebUI, the portal keeps adding torrents. qBittorrent auto-creates a missing category with an empty save path (the repo's own research note says so), so files land in the default folder, outside what Jellyfin scans. Health still reports `ok`. The per-file allowlist remains the real control, but the category/save-path/exclusion guarantees silently lapse.

**Fix:** Before each add (or on a short interval), verify that the two categories exist with the expected `savePath`, or re-run the idempotent `run_once` when qBittorrent reports a restart. At minimum, make `/api/health` reflect drift using the same checks as `app.tools.doctor`.

### WR-07: Login lockout is per source address only, and the whole household can be locked out

**File:** `backend/app/auth.py:56-87`, `backend/app/routers/auth.py:27-39`
**Issue:** Five failed attempts from one address block that address for 15 minutes. If every client appears to be the same address, one person (or a LAN neighbour) typing the wrong password five times locks out everyone. This happens whenever the proxy sees the Docker gateway rather than the real client, for example behind Docker Desktop/WSL2 userland proxying, a fronting router NAT, or `unknown` when `request.client` is missing. There is no lockout bypass, and the 429 message does not say which condition applies.

**Fix:** Document the limitation in `docs/ports-and-media.md`. Optionally also throttle per username, or add a small global ceiling, so the behavior is explicit rather than dependent on network topology. Verify on the Ubuntu box that Caddy sees real client addresses.

## Info

### IN-01: A cached result's `type` is overwritten by a later search of the other type

**File:** `backend/app/search/service.py:237-247`
**Issue:** `_remember` keys `_cache` by `result_id`, and `result_id` depends only on the btih. If a later `serie` search returns the same magnet that a `film` search returned, the cached `type` flips. A download from the earlier search or tab then fails with `422 type_mismatch`, which the UI shows as the generic "Download failed". This is rare, but the household shares one account across several devices.
**Fix:** Include `entry.type` in the cache key or in the result id.

### IN-02: `is_sample_name` rejects legitimate titles containing the word "sample"; some common video containers are not allowed

**File:** `backend/app/download/allowlist.py:51-57`, `:20`
**Issue:** The word match runs on every path component, including the torrent's root folder. A film whose title contains "Sample" has every video excluded, and the torrent is deleted as "no video". `.ts`, `.mov`, `.wmv`, `.webm` and `.m2ts` are not in `VIDEO_EXTENSIONS`, so such torrents are rejected with the message "doesn't contain a video". Neither is a safety problem, but both look like silent false rejections.
**Fix:** Match samples only on the file name or a `Sample/` directory component, and either extend the extension list or word the rejection as "no supported video file".

### IN-03: Unbounded request body size before authentication

**File:** `web/Caddyfile:5-28`
**Issue:** Caddy has no `request_body max_size`, and Starlette reads a whole body before validation. A very large POST to `/api/login` (public) consumes memory. This is only LAN-reachable, so the impact is small.
**Fix:** Add `request_body { max_size 64KB }` inside the `/api/*` handle.

### IN-04: Compose hardening and publishing defaults

**File:** `docker-compose.yml:55-62`, `:20-24`
**Issue:**
- `web` publishes `${WEB_PORT:-80}:80` on all interfaces. On the dedicated Ubuntu server, if the host has any public interface or a router forward, the portal is exposed over plain HTTP with a non-`Secure` session cookie.
- No service sets `security_opt: [no-new-privileges:true]`, `cap_drop: [ALL]` or `read_only`.
- Images are pinned by tag, not digest.
**Fix:** Add `${WEB_BIND:-0.0.0.0}:${WEB_PORT:-80}:80` so the bind address can be set to the LAN IP. Add `no-new-privileges` and `cap_drop` to `backend` and `web`.

### IN-05: Sessions cannot be revoked server-side

**File:** `backend/app/routers/auth.py:48-51`, `backend/app/main.py:79-87`
**Issue:** The signed-cookie session stays valid for `SESSION_MAX_AGE_DAYS` (30). `logout` only clears the client's copy, and changing `APP_PASS_HASH` does not invalidate existing cookies. Only rotating `SECRET_KEY` does. A cookie that leaks from a shared TV or phone keeps working after the owner logs out.
**Fix:** Document that rotating `SECRET_KEY` is the revoke action, or embed a version derived from `APP_PASS_HASH` in the session value and compare it in `require_user`.

### IN-06: Health banner never refreshes

**File:** `frontend/src/App.jsx:25-45`
**Issue:** The health result is fetched once at mount. A user who opens the portal while it is "degraded" (starting up) keeps the banner after the service becomes ready.
**Fix:** Re-check health after login and on a slow interval, or clear the banner when a search or download call succeeds.

### IN-07: Config accepts identical or nested save paths, and the credentials init script can silently do nothing

**File:** `backend/app/config.py:176-184`, `qbittorrent/custom-cont-init.d/10-credentials.sh:20-27`
**Issue:**
- `SAVE_PATH_FILM` and `SAVE_PATH_TV` (or `INCOMPLETE_PATH`) may be equal or nested. Films and series then mix in one folder, or partial files appear under the library folder.
- The init script inserts the credential lines only after a line that equals `[Preferences]`. A config without that header gets no credentials written, yet the script still prints "provisioned". The login would then fail much later.
**Fix:** Validate the three paths as distinct and not nested in `Settings`. In the script, fail with a non-zero exit when the header was not found.

---

_Reviewed: 2026-10-22_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
