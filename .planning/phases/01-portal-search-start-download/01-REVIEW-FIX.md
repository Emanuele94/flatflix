---
phase: 01-portal-search-start-download
fixed_at: 2026-10-22T12:20:00Z
review_path: .planning/phases/01-portal-search-start-download/01-REVIEW.md
iteration: 1
findings_in_scope: 8
fixed: 8
skipped: 0
status: all_fixed
---

# Phase 1: Code Review Fix Report

**Fixed at:** 2026-10-22T12:20:00Z
**Source review:** .planning/phases/01-portal-search-start-download/01-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 8 (1 critical, 7 warning; Info findings are out of scope for `critical_warning`)
- Fixed: 8
- Skipped: 0

**Verification (where it ran):** all gates ran in the main checkout on branch
`gsd/phase-01-portal-search-start-download`, not in an isolated worktree (see "Worktree note"). After
the last fix: `uv run --project backend --frozen pytest backend/tests infra/tests -q` gave 431 passed
(4 integration tests deselected by default); `npm --prefix frontend test` gave 104 passed (was 357 and
100 at the start). The 4 real-qBittorrent integration tests passed against the pinned 5.2.4 image
through the admin override. The stack was then rebuilt with `docker compose up -d --build --wait`:
all three services healthy, `/api/health` returned `{"status":"ok","qbittorrent":"up"}`, and the
admin port 8088 is no longer published.

**Worktree note:** `workflow.use_worktrees` is not set in `.planning/config.json` (default true), but
the fixes had to be verified against the project's `uv`/`node_modules` environments, the untracked
`.env` and the running Docker stack, none of which exist in a fresh worktree. The caller also pinned the
branch and asked for a stack rebuild, so edits and commits were made directly in the main checkout.
No temp branch, worktree or recovery sentinel was created.

## Fixed Issues

### CR-01: `reconcile()` deletes a running download and its files when the pending tag was left behind

**Status:** fixed: requires human verification (logic change)
**Files modified:** `backend/app/download/pipeline.py`, `backend/tests/fakeqbit.py`, `backend/tests/test_download_pipeline.py`
**Commit:** d09a526
**Applied fix:**
- `reconcile()` only auto-deletes an expired pending torrent that never started. A torrent counts as started when its state is not one of `stoppedDL`, `pausedDL`, `metaDL`, `forcedMetaDL`, or when `downloaded`, `completed` or `progress` is above 0 (unreadable values count as started). A started torrent goes through `_process` again (idempotent allowlist, priorities, start, tag cleanup) with a full `METADATA_TIMEOUT` wait, so one failed file-list read cannot turn into a delete.
- Tag cleanup after `start` is retried up to 3 times.
- Tests (fail without the fix): a started torrent with `fx-pending`, age 3600 s, is not deleted and ends with tags `["fx"]`; a stopped torrent that holds payload bytes is not deleted; a flaky `removeTags` is retried. The fake's torrent info rows now carry `downloaded`.
- Deviation from the review's snippet: the review suggested a deadline of `now` for started torrents; a full timeout is used instead so a transient 404 cannot cause a delete. The review's "remove `fx-pending` before `STARTED`" was not applied, because a failed start would then leave a stopped torrent with no tag that no restart could find; the retry shrinks the window instead.

### WR-01: A job that fails after the add leaves a stopped torrent, and the next tap reports "Already added"

**Status:** fixed: requires human verification (logic change)
**Files modified:** `backend/app/download/pipeline.py`, `backend/tests/test_download_pipeline.py`
**Commit:** d09a526 (same commit as CR-01: both touch the same pipeline code and tests)
**Applied fix:** the duplicate check now looks at the existing torrent. If it carries `fx-pending` and no running job owns it (the job tag's task is done or unknown), the new job resumes it through `_process` instead of answering `duplicate`. Torrents without `fx-pending` and torrents owned by a running job are still `duplicate`. This is the review's second option (resume), chosen over a best-effort delete because it never deletes anything after an ambiguous failure.
Tests: a `start` 500 followed by a recovered `start` ends `started` on the second tap with one add and no delete; a pending torrent owned by a live job is still `duplicate`.

### WR-02: `--forwarded-allow-ips "*"` lets any container on the `qbit` network spoof the throttle key

**Status:** fixed: requires human verification (logic change)
**Files modified:** `backend/app/proxy.py` (new), `backend/app/netutil.py` (new), `backend/app/main.py`, `backend/app/config.py`, `backend/app/routers/auth.py`, `backend/Dockerfile`, `web/Caddyfile`, `.env.example`, `backend/tests/test_proxy.py` (new), `infra/tests/test_compose_invariants.py`
**Commit:** c4beba1 (shared with WR-07)
**Applied fix:** uvicorn now runs with `--no-proxy-headers`. A new ASGI middleware, `TrustedProxyHeaders`, believes `X-Forwarded-For` only when the TCP peer is one of `TRUSTED_PROXY_HOSTS` (default `web`, resolved through the compose network's DNS, refreshed every 30 s and at most every 2 s for an unknown peer). It uses the right-most entry, which is the one the proxy appended. A name that does not resolve trusts nobody. Caddy now sets `header_up X-Forwarded-For {remote_host}` explicitly. The review suggested pinning a subnet; the repo's hygiene test bans private address literals, and DNS-based trust needs no pinned address. Live check on the rebuilt stack: seven spoofed-header logins sent from the qBittorrent container straight to `backend:8000` gave `401 x5` then `429 x2`, so the container is throttled as itself.
Tests: middleware unit tests (trusted peer, other peer, malformed or missing header, unresolvable name, recreated proxy, no lookup per request), two through-the-app throttle tests, and infra tests on the Dockerfile `CMD` and the Caddyfile (the Dockerfile flags are the part uvicorn-less tests cannot see).

### WR-03: Untrusted plugin `fileUrl` is passed to qBittorrent/plugin downloader without a scheme check

**Status:** fixed
**Files modified:** `backend/app/search/filters.py`, `backend/app/search/service.py`, `backend/app/download/pipeline.py`, `backend/tests/test_filters.py`, `backend/tests/test_download_pipeline.py`, `backend/tests/test_search_flow.py`
**Commits:** 1bb402d, 4b7cf90 (follow-up so the LAN-address scan in `infra/tests` stays green; 1bb402d alone left that one hygiene test failing)
**Applied fix:**
- `normalize_and_filter` drops rows whose URL is not a `magnet:` link or a plain http(s) URL, rows with embedded credentials, control characters or a bad port, and rows whose host is `localhost`, a single-label compose name (`qbittorrent`, `backend`, `web`), a `.local`/`.lan`/`.internal`-style name, or a non-global IP literal.
- Rows from an engine that is not in `SEARCH_PLUGINS` are dropped (engine names are the plugin file ids; checked against the real 5.2.4 rows).
- The pipeline resolves the host of every non-magnet URL before the add and refuses it unless every resolved address is global; an unresolvable host is refused too. The job ends `failed` and nothing reaches qBittorrent.
- Known limit: the name is resolved by the backend, and qBittorrent resolves it again later (DNS rebinding is not covered). Magnet `tr=`/`ws=`/`xs=` parameters are not inspected.

### WR-04: The "stop before any payload" guarantee for non-magnet results is unproven

**Status:** fixed
**Files modified:** `backend/app/qbit/client.py`, `backend/app/download/pipeline.py`, `backend/tests/fakeqbit.py`, `backend/tests/test_download_pipeline.py`, `backend/tests/integration/test_real_qbit.py`
**Commit:** 7fa6969
**Applied fix:**
- Non-magnet results are now added with `stopped=true` (and no `stopCondition`), the review's alternative; `add_torrent` takes a keyword-only `stopped`. Magnets keep `stopCondition=MetadataReceived`.
- The fake models payload: a torrent that is not stopped runs and gets `downloaded = 1` at add, and a metadata-complete torrent is assumed not to honor a stop condition. Pipeline tests assert `downloaded == 0` for the magnet and for the non-magnet path and check the add forms; the non-magnet test fails without the fix.
- The real-qBittorrent magnet test asserts `evidence[0] == 0` (it only recorded it before). It also no longer asserts that Sintel is absent and no longer deletes it in `finally` unless the test added it; it skips if the torrent exists. The household's Sintel download (a different torrent) was untouched; qBittorrent still holds only that one torrent.
- Two new real-engine tests (synthetic locally bencoded torrents only, deleted with files afterwards): a metadata-complete torrent added `stopped` reaches `stoppedDL` with 0 bytes and a readable file list, then goes through the pipeline's resume path (allowlist, priorities, verify, start, tags). A second test records what `stopCondition=MetadataReceived` does to such a torrent. Evidence on 5.2.4: it ends `stoppedDL`, 0 bytes, so the condition would also have held it; `stopped=true` is kept because it does not depend on that and was only measured through a file upload, not through the plugin downloader.
- Not run: the plugin-downloader route itself (it needs a real search plugin to serve a `.torrent`).
- Behaviour to know: if a plugin's downloader ever hands back a magnet, a stopped magnet never gets its metadata, so the job ends `unavailable` and the torrent is deleted after `METADATA_TIMEOUT`. That fails closed.

### WR-05: Rows can stay on "Preparing" forever (job gone after restart, 404/401, or give-up)

**Status:** fixed
**Files modified:** `frontend/src/Search.jsx`, `frontend/src/ResultRow.jsx`, `frontend/src/messages.js`, `frontend/src/__tests__/Search.test.jsx`, `frontend/src/__tests__/ResultRow.test.jsx`
**Commit:** 9396400
**Applied fix:** a 404 from the job poll, or the 330 s give-up, sets a new retryable `lost` row state ("We lost track of this download. Tap Download to check it again.") with an enabled Download button and stops polling. A new tap hits the server-side resume or duplicate path (WR-01). A 401 still hands over to the login screen. The old test "gives up after 330 s and keeps Preparing" pinned the bug and was rewritten; both new tests fail without the fix.

### WR-06: Readiness is checked once; later qBittorrent config drift is not detected

**Status:** fixed: requires human verification (logic change)
**Files modified:** `backend/app/qbit/bootstrap.py`, `backend/app/download/pipeline.py`, `backend/tests/test_download_pipeline.py`
**Commit:** 42deab2
**Applied fix:** `repair_drift` runs before every add. It reads the live preferences and categories and checks the exclusion list (enabled, every required pattern present), auto torrent management for torrents and category changes, the incomplete folder, and both categories with their save paths (a missing category counts as drift). If anything differs it re-applies `build_preferences` and the idempotent category sync, which keeps patterns an admin added. If the repair fails the job ends `failed` before anything is added. `Bootstrapper._sync_categories` now delegates to the shared `sync_categories`. `/api/health` was not changed (the check costs two extra qBittorrent calls per add instead of per health poll). Tests: a changed category path, a deleted category and a switched-off exclusion list are each repaired before the add; an untouched configuration is not rewritten; an unrepairable one adds nothing. Four of the five tests fail without the fix. The live stack showed no drift warnings after the rebuild.

### WR-07: Login lockout is per source address only, and the whole household can be locked out

**Status:** fixed: requires human verification (design trade-off)
**Files modified:** `backend/app/auth.py`, `backend/app/config.py`, `backend/app/main.py`, `.env.example`, `docs/setup.md`, `backend/tests/test_login_throttle.py`
**Commit:** c4beba1 (shared with WR-02)
**Applied fix:** the per-address limit (5 per 15 minutes) stays. A second ceiling across all addresses (`LOGIN_GLOBAL_MAX_ATTEMPTS`, default 20) was added. Only allowed attempts are recorded, so the throttle's state never holds more than that many entries (this also closes the unbounded-growth note in WR-02). A correct login clears the slots of its address in both counters. The 429 `Retry-After` is the longer of the two waits. `docs/setup.md` now explains both limits, the trade-off (someone on the LAN who fails 20 times locks the household out for up to 15 minutes), the case where the host hides real client addresses (Docker Desktop/WSL2 proxying, NAT), a check to run on the Ubuntu box (fail five logins from one phone, confirm another phone can still sign in), and the unlock command. The throttle was not removed or weakened. Still open by design: on a host where every phone looks like one address, one person's five wrong attempts still block everyone; the doc says so.

---

_Fixed: 2026-10-22T12:20:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
