# Phase 2: Portal Download Management & Hardening - Research

**Researched:** 2026-10-22
**Domain:** FastAPI + Preact portal on top of qBittorrent WebAPI v2 (5.2.4): download list, cancel/remove, error mapping, rate limiting, audit logging, Caddy cache headers, Docker log rotation
**Confidence:** HIGH (qBittorrent behavior read from the 5.2.4 source; Caddy and compose behavior run against the pinned images; existing code read in full)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

### Downloads list (DOWN-04)
- **D-25:** The list shows **every torrent in the `Film` and `SerieTV` categories**, including ones the admin added by hand in the WebUI, not only `fx`-tagged ones. Torrents in other categories never appear.
- **D-26:** Layout: **two tabs, Search | Downloads**, under the app header. Switching tabs must not lose the search (it already lives in sessionStorage, D-24).
- **D-27:** Each row: **name, Movie/TV badge, progress bar with %, plain state**, plus a rough time left while downloading (e.g. "about 20 min left"). No speed, seeders or raw qBittorrent state names. Plain states map qBittorrent states to a small set: Preparing / Downloading / Ready / Stalled / plus the failure states below. Exact mapping is Claude's discretion.
- **D-28:** A completed download stays in the list **7 days after completion**, then drops off the list (the file stays on disk, the torrent is not touched by this). Env-configurable, default 7 days.
- **D-29:** Failed attempts (rejected, unsupported, unavailable, failed, D-11..D-13) **show in the list for 24 h** with their existing plain message, so a "Preparing" row that later failed is not silently lost. Kept in the in-memory job registry; a backend restart clears them (acceptable).
- **D-30:** Order: **active first** (Preparing, Downloading, Stalled), then the rest, **newest first** within each group.
- **D-31:** Polling every ~5 s **only while the Downloads tab is visible** and the page is not hidden (Page Visibility); refresh immediately when the user comes back.

### Cancel rules (DOWN-05)
- **D-32:** Cancelling an **in-progress** download (including Preparing) deletes the torrent **and its partial files** from qBittorrent, after **one confirm tap** ("Cancel this download?"). The row then disappears.
- **D-33:** A **completed** download has **no Cancel**. It has **"Remove from list"**, which removes the torrent from qBittorrent **keeping the files** (`deleteFiles=false`; stops seeding early, overriding D-21 for that torrent). The film never gets deleted from the phone. — **Reversibility:** reversible.
- **D-34:** Admin-added Film/SerieTV torrents follow **the same rules** as portal-started ones (one shared account, one household).
- **D-35:** The browser identifies a torrent by an opaque id from the list response, never by sending a path or category; the backend re-checks that the torrent is in `Film` or `SerieTV` before acting (SEC-03 spirit).

### Errors and outage (DOWN-06)
- **D-36:** When qBittorrent is unreachable with the Downloads tab open: **keep the last known list, greyed**, show a banner "Can't reach the download service. Retrying…", keep polling, clear the banner on its own when it comes back. Cancel / Remove are disabled meanwhile.
- **D-37:** Every failure shows plain English from `messages.js`; invalid torrent (415), unreachable (502, auto-retry), invalid category path (409), wrong qBittorrent credentials (401: logged, generic message only). No status codes or qBittorrent text reach the screen (same rule as Phase 1, 01-11 / 01-12).

### Throttling (SEC-05)
- **D-38:** **Generous limits:** search **10 per minute**, download **20 per minute**, env-configurable. Only a stuck finger or a script should hit them. Reusing the `LoginThrottle` sliding-window approach is Claude's discretion (keying per address vs global as in WR-07).
- **D-39:** When throttled the user sees **"Too many requests. Wait a moment and try again."** on the search box or the row. No countdown.

### Audit logs (SEC-06)
- **D-40:** Logs go to **stdout only** (`docker compose logs backend`); compose sets Docker's json-file driver with **size rotation (e.g. 10 MB x 5)**. No log volume.
- **D-41:** Audit events: login (success / fail / throttled), search (**with the search text** and type), download (**with the torrent name** and outcome), cancel / remove (torrent name), throttled requests, errors. **Client IP included.** Never: passwords, hashes, session cookies, `SECRET_KEY`, qBittorrent credentials or its SID. Log format (plain lines vs JSON) is Claude's discretion, consistent with the existing `LOG_FORMAT`.

### Phase 1 leftovers (folded)
- **D-42:** **Stale clients:** Caddy sends `Cache-Control: no-cache` on `index.html` (and the SPA fallback) and long immutable caching on hashed `/assets/*`, so phones pick up a new version after a redeploy.
- **D-43:** **WR-01:** when choosing the main video, the allowlist counts **non-allowlisted videos too**. If the largest video in the torrent is not allowlisted (e.g. a big `.webm` film with a small `.mp4` trailer), the torrent is rejected as **`unsupported`** with the existing text "This video format isn’t supported. Try another result." (D-13 amended). The FILT-02 allowlist itself is unchanged.

### Claude's Discretion
- Mapping of qBittorrent states to plain states, and the ETA wording/rounding.
- List API shape (one endpoint merging qBittorrent torrents and in-memory failed jobs is the expected shape).
- Throttle keying and whether the login throttle class is generalized.
- Log format and event field names.
- Visual design of tabs, rows, confirm dialog; keep large tap targets and the existing CSP (no inline styles, D-03 / 01-04).

### Deferred Ideas (OUT OF SCOPE)
- Deleting a completed film from the library from the phone — rejected for now (D-33); revisit only with a strong confirm if the household needs to free space.
- Verifying / rejected-by-probe states in the list — Phase 2.1.

Out of this phase (from CONTEXT domain): quarantine, ffprobe and the verifying / rejected-by-probe states (Phase 2.1); renaming into Jellyfin layout (Phase 4); deleting a completed film from the library; multiple accounts.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DOWN-04 | User can see downloads in progress and completed (Film and SerieTV only) with state and progress, refreshed about every 5 s | One `torrents/info` call, exact-category filter, pure state mapper (Pattern 1), list endpoint merging failed jobs (Pattern 2), visibility-aware polling hook (Pattern 6), `<progress>` element (CSP-safe) |
| DOWN-05 | User can cancel a download from the list and it is removed from qBittorrent | HMAC opaque id (Pattern 3), server-decided `deleteFiles`, job-task cancellation to avoid ghost "unavailable" rows (Pitfalls 1, 2), inline confirm (jsdom has no `showModal`) |
| DOWN-06 | Plain messages for invalid torrent, unreachable (auto-retry), invalid category path, wrong credentials | Error-mapping table (Pattern 7); never answer 401 for a qBittorrent auth failure (it would log the user out, Pitfall 4); polling keeps retrying (D-36) |
| SEC-05 | Search and download endpoints rate limited with a clear message | Extract `LoginThrottle` into a generic sliding-window class (Pattern 4); throttle only the two POST start routes, in the handler after validation; 429 + `MSG.throttled` |
| SEC-06 | Essential logs for debugging and audit, no credentials in any line | Typed `audit` helpers with value sanitizing, independent audit-logger level, redacting `logging.Filter` on every handler, canary leak test (Pattern 5), json-file rotation in compose |
</phase_requirements>

## Summary

Phase 2 is almost entirely additive on code that already exists and is well tested (447 backend + infra tests and 135 frontend tests pass at HEAD, measured this session). The backend needs one new pure module (state mapping + list assembly), two new routes (`GET /api/downloads`, `DELETE /api/downloads/{id}`), two new client-side calls on `QbitClient` (none: `torrents_info` and `delete` already exist), a generic throttle extracted from `LoginThrottle`, an audit helper, and a one-function change in `allowlist.decide()` for WR-01. The frontend needs a tab bar, a `Downloads` view with a visibility-aware 5 s poll, a row component with an inline confirm, new `MSG` strings and a 429/`cancelled` mapping in `Search`. Infra work is a three-line Caddy change (verified to behave correctly by running `caddy:2.11.7-alpine`) and a compose `logging:` anchor (verified with `docker compose config`).

The decisions that carry the most risk are not the obvious ones. (1) Cancelling a Preparing download while its background job task is still running leaves a task that waits for files that will never come and then marks the job `unavailable`, which would resurface as a ghost failed row for 24 h; the cancel path must cancel the job task first and mark the job `cancelled`. (2) A cancelled `started` job still blocks a re-tap of Download for 60 s through `STARTED_DEDUPE_SECONDS` unless its state leaves `ACTIVE_STATES`. (3) The frontend `api()` wrapper treats every 401 as "session expired" and shows the login page, so the backend must never answer 401 for a qBittorrent credential failure (the spec's section 13 table says 401; do not copy it onto the portal API). (4) `Search` owns timers that stop on unmount, so the tab switch must keep `Search` mounted and only hide it. (5) qBittorrent's `category` filter on `torrents/info` also matches sub-categories (`Film/x`), so filter by exact equality in the backend. (6) The WR-01 wording in D-43 ("if the largest video is not allowlisted, reject") conflicts with an existing test if applied literally; the 10 % sample rule from the original review fix preserves current behavior and should be confirmed by the user (Assumption A1).

**Primary recommendation:** Build one pure `app/download/listing.py` (state mapper, ETA/progress, list assembly, opaque ids) and keep every route, log line and UI string a thin consumer of it; cancel goes through `DownloadPipeline` so the job task, the job state, the tags and the torrent are always changed together.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Downloads list assembly (torrents + failed jobs, ordering, 7 d / 24 h windows) | API / Backend | — | Only the backend can reach qBittorrent and holds the job registry; browser must never see hashes, categories or paths |
| Plain-state mapping | API / Backend | — | One place (Phase 2.1 adds verifying/rejected-by-probe); browser only maps state codes to text |
| Opaque torrent id and category re-check on cancel | API / Backend | — | SEC-03 / D-35: authorization decision, never trusted from the client |
| `deleteFiles` decision (cancel vs remove) | API / Backend | — | Safety rule: a completed film must never be deleted because of a client flag |
| Rate limiting | API / Backend | — | In-memory sliding window per client address, after auth and validation |
| Audit logging and redaction | API / Backend | Container runtime (Docker json-file) | App writes lines to stdout; Docker owns rotation and storage |
| Cache headers for `index.html` vs hashed assets | CDN / Static (Caddy) | — | Caddy serves the SPA; headers are static config |
| Tabs, rows, confirm, polling, Page Visibility, ETA text | Browser / Client | — | Presentation and timing only |
| User-facing wording | Browser / Client (`messages.js`) | — | Existing rule: all copy lives in `MSG`; backend sends codes only |

## Standard Stack

No new runtime dependency is needed. Everything below is already pinned in the lockfiles.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| FastAPI | 0.159.1 | New routes via `protected_router()` | Already the backend (D-01) [VERIFIED: backend/pyproject.toml] |
| httpx | 0.28.1 | qBittorrent calls (existing `QbitClient`) | Existing client already has `torrents_info` and `delete` [VERIFIED: backend/app/qbit/client.py:312-326, 351-357] |
| Python stdlib `hmac`, `hashlib`, `logging`, `json`, `collections.deque` | 3.12 | Opaque ids, audit lines, throttle | No dependency needed |
| Preact | 11.0.1 | Tabs, Downloads view | Existing frontend [VERIFIED: frontend/package.json] |
| Caddy | 2.11.7-alpine | Cache headers | Existing image [VERIFIED: web/Dockerfile] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest 9.1.1 + pytest-asyncio 1.4.0 | pinned | Backend tests with `FakeQbit` | All backend tests [VERIFIED: backend/pyproject.toml] |
| vitest 5.0.5 + @testing-library/preact 3.2.4 + jsdom 30.1.3 | pinned | Frontend tests, fake timers | All frontend tests [VERIFIED: frontend/package.json] |
| PyYAML 6.0.3 | pinned | Infra invariants for compose logging | New infra tests |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| In-memory throttle | `slowapi`, `fastapi-limiter` | New dependency plus a package-legitimacy review for something the repo already implements and tests; Redis variant needs a new service. Do not add. |
| Plain key=value audit lines | `structlog` / `python-json-logger` | New dependency; the existing `LOG_FORMAT` is plain text and `docker compose logs` is read by one admin |
| `<dialog>.showModal()` confirm | Inline confirm inside the row | jsdom 30.1.3 has no `showModal` (checked: `'showModal' in dialog` is `false`), so a dialog cannot be tested the way the other components are |
| Inline `style="width:NN%"` progress bar | native `<progress>` element | CSP is `style-src 'self'`; a `<progress>` needs no style attribute and is accessible |

**Installation:** none. No `npm install` / `uv add` in this phase.

**Version verification:** no package is added, so no registry lookup applies. Pinned versions were read from `backend/pyproject.toml` and `frontend/package.json` this session.

## Package Legitimacy Audit

This phase installs no external packages (Python additions use the standard library; the frontend adds only source files). The Package Legitimacy Gate therefore has nothing to check.

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| (none) | — | — | — | — | — | — |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

If a plan proposes adding any dependency (rate limiter, logger, UI kit), it must be rejected by the planner: all of it is covered by the Don't Hand-Roll section below using code already in the repo.

## Architecture Patterns

### System Architecture Diagram

```
Phone (Preact SPA)
  |  Tabs: [Search] [Downloads]      Search stays mounted (hidden attr), Downloads mounts on demand
  |
  |-- every 5 s while Downloads visible & page not hidden ----> GET /api/downloads
  |-- tap Cancel -> inline confirm -> DELETE /api/downloads/{id}
  |-- POST /api/search | POST /api/download   (429 -> "Too many requests...")
  v
Caddy :80  (/api/* -> backend:8000, X-Forwarded-For = real client; /assets/* immutable; everything else no-cache + SPA fallback)
  v
FastAPI backend
  |  TrustedProxyHeaders -> request.client.host = phone address
  |  protected_router(): require_user (401) -> [require_ready] -> body validation (422)
  |      -> throttle.try_acquire(ip)  (429 + audit "throttled")   <- only POST /search, POST /download
  |
  |  GET /api/downloads
  |     QbitClient.torrents_info()            one call, no category param
  |     listing.build_items(rows, jobs, now)  exact category check, plain_state(), 7 d / 24 h windows, order
  |     -> {items:[{id,name,type,state,progress,eta_seconds,action}]}
  |
  |  DELETE /api/downloads/{id}
  |     torrents_info() -> find row where hmac_id(hash)==id AND category in {Film,SerieTV}   (else 404)
  |     JobRegistry.cancel_for(hash)  -> cancel job task, job.state = CANCELLED
  |     QbitClient.delete([hash], delete_files = decided HERE from live state)
  |     delete job tag, audit "cancel"/"remove"
  |
  |  audit(): one logger "app.audit", typed helpers, sanitised values, redacting Filter -> stdout
  v
qBittorrent 5.2.4 (WebAPI v2.15.1), internal network only
  v
Docker json-file driver (max-size 10m, max-file 5) -> `docker compose logs backend`
```

### Recommended Project Structure
```
backend/app/
├── throttle.py              # NEW: SlidingWindowThrottle (extracted from auth.LoginThrottle)
├── audit.py                 # NEW: typed audit helpers + RedactingFilter + sanitiser
├── download/
│   ├── listing.py           # NEW: plain_state, eta/progress, opaque ids, build_items (pure, no I/O)
│   ├── jobs.py              # EDIT: Job.name, Job.finished_at, JobState.CANCELLED, registry.cancel_for
│   ├── pipeline.py          # EDIT: cancel(), _discard(delete_files=), 415 -> unavailable, name capture
│   └── allowlist.py         # EDIT: decide() for WR-01
├── routers/
│   ├── downloads.py         # NEW: GET /api/downloads, DELETE /api/downloads/{id}
│   ├── download.py          # EDIT: throttle + audit + job body knows "cancelled"
│   ├── search.py            # EDIT: throttle + audit
│   └── auth.py              # EDIT: audit login/logout/throttled
├── config.py                # EDIT: new settings
└── main.py                  # EDIT: build throttles, register router, configure audit logging
frontend/src/
├── App.jsx                  # EDIT: tab bar; Search always mounted, hidden when Downloads active
├── Downloads.jsx            # NEW: list, polling hook, banner, greyed stale list
├── DownloadRow.jsx          # NEW: pure view with inline confirm
├── eta.js                   # NEW: formatEta(seconds)
├── messages.js              # EDIT: new strings
├── Search.jsx / ResultRow.jsx   # EDIT: 429 and "cancelled" mapping
└── styles.css               # EDIT: tabs, progress, [hidden]
web/Caddyfile                # EDIT: two handle blocks
docker-compose.yml           # EDIT: x-logging anchor on all three services
.env.example, docs/setup.md  # EDIT: new variables, log viewing
```

### Pattern 1: One pure state mapper (the only place that knows qBittorrent state names)

**What:** `plain_state(row) -> str` returns one of `preparing | downloading | stalled | ready | problem`. Failure states (`rejected | unsupported | unavailable | failed`) come from jobs, never from qBittorrent. Phase 2.1 will add `verifying`/`rejected-by-probe` here and nowhere else.

**Source of truth for the state strings:** `torrentStateToString` in qBittorrent release-5.2.4 `src/webui/api/serialize/serialize_torrent.cpp` [VERIFIED: raw.githubusercontent.com/qbittorrent/qBittorrent/release-5.2.4]. The 19 strings it returns, verbatim: `error`, `missingFiles`, `uploading`, `stoppedUP`, `queuedUP`, `stalledUP`, `checkingUP`, `forcedUP`, `downloading`, `metaDL`, `forcedMetaDL`, `stoppedDL`, `queuedDL`, `stalledDL`, `checkingDL`, `forcedDL`, `checkingResumeData`, `moving`, and the default `unknown`. The public wiki page lists `pausedUP/pausedDL` and omits `stoppedUP/stoppedDL/forcedMetaDL` (it describes the 4.x names); the 5.2.4 source is authoritative for the pinned image.

**Rule from `updateState()` (same release, `torrentimpl.cpp`):** the `...UP` states are produced only when `isFinished()`; `stoppedDL` is produced for an unfinished torrent that is stopped, and also for a torrent without metadata that is stopped.

| qBittorrent state | Plain state | Note |
|---|---|---|
| `uploading`, `stalledUP`, `stoppedUP`, `queuedUP`, `forcedUP`, `checkingUP` | `ready` | The only route to `ready`; D-21 seeding limits end in `stoppedUP`, still `ready` |
| `downloading`, `forcedDL` | `downloading` | |
| `moving` | `downloading` (progress 100, no ETA) | Files are not at their final place yet: never show Ready while moving |
| `stalledDL` | `stalled` | |
| `stoppedDL` / `pausedDL` with tag `fx-pending` | `preparing` | Portal torrent waiting for the allowlist (tags in Pattern 2) |
| `stoppedDL` / `pausedDL` without `fx-pending` | `stalled` | Stopped by the admin in the WebUI |
| `metaDL`, `forcedMetaDL`, `checkingResumeData`, `checkingDL`, `queuedDL` | `preparing` | `queuedDL` can last long when more than the queue limit are active; "Preparing" is acceptable |
| `error`, `missingFiles` | `problem` | New plain state; text suggests asking the admin (planner chooses wording) |
| anything else, including `unknown` | `stalled` | Safe default: never claim Ready for an unrecognised state |

**Progress:** `progress` is relative to the wanted (priority > 0) files: `TorrentImpl::progress()` returns `total_wanted_done / total_wanted`, `1.` when equal, and `0.` when `total_wanted == 0` [VERIFIED: release-5.2.4 torrentimpl.cpp:904-924]. So a torrent whose unwanted files have priority 0 reaches 1.0 correctly. Send an integer percent: `floor(progress * 100)`, and 100 only for `ready`.

**ETA:** `eta` is seconds; `MAX_ETA = 8640000` means "infinite" [VERIFIED: `const qlonglong MAX_ETA = 8640000;` at src/base/types.h:33, release-5.2.4]. A stopped torrent and a download with zero average speed both return `MAX_ETA` (torrentimpl.cpp:1337, 1380). Send `eta_seconds: null` when `eta >= 8640000`, or when the plain state is not `downloading`.

**Completion time:** `completion_on` is `Utils::DateTime::toSecsSinceEpoch(torrent.completedTime())`, and that function is `return dateTime.isValid() ? dateTime.toSecsSinceEpoch() : -1;` [VERIFIED: release-5.2.4 serialize_torrent.cpp and src/base/utils/datetime.cpp]. So an unfinished torrent reports `-1`. For the D-28 window use `completion_on` when it is greater than 0, otherwise fall back to `added_on` (a torrent that was already complete when added may have no completion time: [ASSUMED], covered by the fallback).

### Pattern 2: List assembly (pure function over rows and jobs)

**What:** `build_items(rows, jobs, settings, now, secret) -> list[dict]`.

1. Keep a row only if `row["category"]` is **exactly** `settings.category_film` or `settings.category_tv`. Do not rely on the `category=` query parameter: `belongsToCategory` also matches sub-categories (`m_category.startsWith(category + '/')`) [VERIFIED: release-5.2.4 torrentimpl.cpp:931-940]. One unfiltered `torrents_info()` call, then filter locally; this also keeps the re-check at cancel time identical.
2. Item per kept row: `id = hmac_id(secret, hash)`, `name = row["name"]`, `type` from category (add `type_for_category(settings, category)` next to `qbit_category` in `content_type.py`), `state = plain_state(row)`, `progress`, `eta_seconds`, `action = "remove"` if `ready` else `"cancel"` (`stalled`/`downloading`/`preparing`/`problem` all cancellable).
3. Hide `ready` rows older than `COMPLETED_VISIBLE_DAYS` (D-28), measured with `time.time()` against the completion time rule above.
4. Add job rows from `JobRegistry`:
   - failure states (`REJECTED`, `UNSUPPORTED`, `UNAVAILABLE`, `FAILED`) with `finished_at` within `FAILED_VISIBLE_HOURS` (D-29): `id = job_id`, `state` = the job state value, `progress 0`, `action = null`. `DUPLICATE` and `CANCELLED` are never listed.
   - `PREPARING` jobs whose `torrent_hash` is `None` or absent from the qBittorrent rows (a plugin-page add shows up seconds later): `state = "preparing"`, `id = job_id`, `action = "cancel"`. A job whose torrent is present is skipped: the torrent row represents it.
5. Order (D-30): group 0 = `preparing/downloading/stalled`, group 1 = everything else; inside a group newest first by `completion_on` (if > 0) else `added_on` for torrents, `finished_at`/`created_at` for jobs.

**Name for a Preparing magnet:** until metadata arrives qBittorrent reports the magnet's `dn` or the bare info-hash as `name`. If `name` matches 40 or 64 hex characters, prefer the matching job's `name` (captured from the search cache at submit time, see Job changes below) and otherwise send `name: null` so the UI shows a placeholder string. Never show a raw hash to the household.

**Tags used by the pipeline** [VERIFIED: backend/app/download/pipeline.py:45-47]:
```
TAG_PORTAL = "fx"
TAG_PENDING = "fx-pending"
TAG_JOB_PREFIX = "fx-job-"
```
`_tags_of(row)` and `_job_tag_of(tags)` already parse the comma-separated `tags` field (pipeline.py:65-70); reuse them (move to `listing.py` or import).

**Job changes** (current dataclass [VERIFIED: backend/app/download/jobs.py:39-47]):
```python
@dataclass(slots=True)
class Job:
    job_id: str
    # None for a job resumed after a restart: the search result is long gone.
    result_id: str | None
    type: ContentType | None
    state: JobState
    torrent_hash: str | None
    created_at: float
```
Add `name: str | None = None` (from `cached.name` in `submit`, from `row["name"]` in `reconcile`) and `finished_at: float | None = None`. Stamp `finished_at` in `JobRegistry._guard` when the task ends (every job passes through `_guard`; pipeline code assigns `job.state` in about a dozen places, so stamping in one place is far less invasive than a state setter). `JobState` today [VERIFIED: jobs.py:24-36]:
```
    PREPARING = "preparing"  # waiting for metadata or for the allowlist to finish
    STARTED = "started"  # filtered and running
    REJECTED = "rejected"  # no usable video inside: deleted with its files (D-13)
    ...
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"  # no metadata before METADATA_TIMEOUT: deleted (D-12)
    DUPLICATE = "duplicate"  # qBittorrent already has it
    FAILED = "failed"  # anything else: nothing was started
```
and `ACTIVE_STATES = frozenset({JobState.PREPARING, JobState.STARTED})`. Add `CANCELLED = "cancelled"` (not in `ACTIVE_STATES`).

### Pattern 3: Opaque ids that survive restarts, no new storage

**What:** `id = hmac.new(secret_key_bytes, b"download-id:" + hash.encode(), hashlib.sha256).hexdigest()[:16]`. 16 lowercase hex matches the id shape the frontend already validates (`const ID = /^[0-9a-f]{16}$/` [VERIFIED: frontend/src/Search.jsx:~33]) and the `RESULT_ID_PATTERN = r"^[0-9a-f]{16}$"` convention in `routers/download.py`. The backend resolves an id by listing torrents and comparing; there is no id table to keep in sync. Using HMAC (not a bare hash) means an id cannot be tested against a known info-hash. Changing `SECRET_KEY` changes ids, which only makes an open page's next tap return 404 (treated as "already gone", then refresh).

The browser never receives the real hash, consistent with the Phase 1 router rule: "Every response is exactly `{status, job_id}`: no hash, save path, category or URL ever reaches the browser" [VERIFIED: backend/app/routers/download.py:1-6].

**DELETE resolution order:** (a) torrent row whose `hmac_id(hash) == id` and whose category is exactly one of the two configured names; (b) otherwise an active `PREPARING` job with `job_id == id`. Neither found: `404 {"detail": "download_not_found"}` (the UI treats 404 as success and refreshes). Validate the path parameter with `Path(pattern=r"^[0-9a-f]{16}$")`.

### Pattern 4: Generic throttle extracted from `LoginThrottle`

Current class [VERIFIED: backend/app/auth.py:59-121]: `LoginThrottle(max_attempts=5, window_seconds=900, clock=time.monotonic, global_max_attempts=None)` with `try_acquire(ip) -> float | None` (None = allowed and recorded, float = seconds to wait) and `reset(ip)`. The existing tests construct it as `LoginThrottle(max_attempts=5, window_seconds=900, clock=fake)` and swap `app.state.login_throttle` [VERIFIED: backend/tests/test_login_throttle.py:26-29].

**Recommendation:** move the body unchanged to `app/throttle.py` as `SlidingWindowThrottle`, keep `LoginThrottle = SlidingWindowThrottle` (or a trivial subclass) importable from `app.auth`, so `test_login_throttle.py` and `main.py` keep working untouched. Add `app.state.search_throttle` and `app.state.download_throttle`, built in `create_app` next to `login_throttle` (same "built here, not in the lifespan" reason).

**Keying decision:** per client address, **no global ceiling** (`global_max_attempts=None`) for search and download. Reason: WR-07's global ceiling exists to bound password guessing across spoofed addresses; these routes are already behind a login, and the limits are meant to stop a stuck finger or a script (D-38). Document the same caveat as the login lockout: when the host hides real addresses (Docker Desktop and WSL2), every phone shares one key and the limit becomes household-wide; 10 searches and 20 downloads per minute is still generous for that case.

**What counts:**
- Throttle only `POST /api/search` (10 per 60 s) and `POST /api/download` (20 per 60 s). Do NOT throttle `GET /api/search/{id}` (the frontend polls it every 700 ms, `POLL_MS = 700` [VERIFIED: Search.jsx:5]), `GET /api/download/{job_id}` (every 2 s), `GET /api/downloads` (every 5 s) or `DELETE`.
- Call `try_acquire` **inside the handler**, after body validation and after `require_user`/`require_ready` (router/route dependencies run before the handler), so unauthenticated and malformed requests never consume a slot or grow the state.
- On refusal: `HTTPException(429, detail="too_many_requests", headers={"Retry-After": str(max(1, math.ceil(retry_in)))})` (same shape as the login route [VERIFIED: backend/app/routers/auth.py:31-37]) plus an audit "throttled" line.
- Settings (names are a recommendation): `SEARCH_RATE_PER_MINUTE=10`, `DOWNLOAD_RATE_PER_MINUTE=20`, both `Field(default=..., ge=1)`.
- Stale per-address keys are only pruned when that address is seen again; with a handful of household addresses this is negligible, no sweeper needed.

### Pattern 5: Audit logging and redaction

**Logger and format.** One module `app/audit.py`; logger name `app.audit`; plain `key=value` text lines through the existing root handler and `LOG_FORMAT` (`"%(asctime)s %(levelname)s %(name)s %(message)s"` [VERIFIED: backend/app/main.py:26]). Example output line: `2026-10-22 18:00:01,123 INFO app.audit event=search ip=203.0.113.7 type=film q="sintel 1080p"`.

**Typed helpers, not a generic `**kwargs`.** `audit.login(outcome, ip)`, `audit.logout(ip)`, `audit.search(ip, type, q)`, `audit.download_requested(ip, type, name, job_id)`, `audit.download_finished(job_id, name, outcome)`, `audit.removed(ip, action, name, outcome)`, `audit.throttled(ip, scope)`, `audit.error(where, exc_class, status)`. A helper that can only be handed those fields cannot be handed a `Request`, a body, a header or a settings object. Do **not** log the attempted username on a failed login: a person who types the password into the username box would put it in the log; with one shared account the name adds no information.

**Sanitising values.** Search text and torrent names are attacker-controlled (a torrent name or a typed query can contain newlines and forge a log line). Render every free-text value with `json.dumps(value[:200], ensure_ascii=False)` (escapes `\n`, `\r`, quotes and control characters, and truncates). IP addresses and enum-like values are printed bare.

**Level independence.** `LOG_LEVEL=WARNING` must not silence the audit trail. Verified this session: setting `logging.getLogger("app.audit").setLevel(logging.INFO)` after `basicConfig(level="WARNING")` still emits INFO audit lines while other INFO loggers stay silent (ancestor logger levels are not consulted for propagated records). Do this in `configure_logging`.

**Redacting filter (defence in depth).** A `logging.Filter` that, for every record, rewrites the formatted message and `exc_text`, replacing: the values of `SECRET_KEY`, `QBITTORRENT_PASS`, `APP_PASS_HASH` (only when length is at least 8), and the regex `QBT_SID\w*=[^;\s]+` and `flatflix_session=[^;\s]+`. Install it on the root handlers **and** on the handlers of `uvicorn.error` and `uvicorn.access` (uvicorn configures those loggers with their own handlers before the app factory runs, so a root-only filter would not see them) [ASSUMED: uvicorn 0.54.0 default LOGGING_CONFIG uses non-propagating `uvicorn.*` handlers; verify by inspecting `logging.getLogger("uvicorn.access").handlers` in a test or the running container].

**Existing convention to keep:** log exception class and HTTP status only, never bodies or messages (pipeline `_settle`, search `unavailable()`).

**What the audit must contain (D-41):** login success/fail/throttled; search text and type; download with torrent name and outcome; cancel/remove with torrent name; throttled requests; errors; client IP on every request-scoped line (`request.client.host`, already the forwarded address thanks to `TrustedProxyHeaders` [VERIFIED: backend/app/proxy.py:79-88]).

**Download outcome logging.** The HTTP request ends before the job does (D-11), so log two lines joined by `job_id`: `download_requested` in the route (has ip and cached name) and `download_finished` when the job settles (stamp in `JobRegistry._guard`, same place as `finished_at`). The job does not need to carry the IP.

### Pattern 6: Visibility-aware polling in Preact

Mirror the existing `Search.jsx` discipline (epoch counter, `setTimeout` chain, cleanup in `useEffect`). Rules:
- Chain `setTimeout` after each request completes (never `setInterval`), 5000 ms.
- Treat the page as visible unless `document.visibilityState === 'hidden'` (jsdom reports `prerender`, so do not compare with `'visible'`).
- On `visibilitychange` to not hidden: clear the timer and fetch now. When hidden: clear the timer.
- Mount `Downloads` only while its tab is active; unmount stops everything through the effect cleanup. This satisfies D-31 with no extra tab-visibility prop.
- On failure keep `items`, set `stale = true`, show `MSG.downloadServiceDown`, keep scheduling (D-36). On the next success clear `stale`. A 401 is handled globally by `api()`'s unauthorized handler.
- Ignore a response that arrives after unmount or after a newer request started (epoch check), exactly like `if (run !== runId.current) return;` in `Search.poll`.

### Pattern 7: Failure-to-message mapping (DOWN-06)

| Situation | Where it arises today | Backend outcome | User text (all from `messages.js`) |
|---|---|---|---|
| qBittorrent unreachable, list/cancel | `QbitUnavailable` from `QbitClient._send` | `502 {"detail":"qbit_unreachable"}` | Banner "Can’t reach the download service. Retrying…" + automatic retry by polling |
| qBittorrent unreachable, Download tap | pipeline `_settle` catches `QbitError` → `FAILED` | job `failed` | existing `downloadFailed`, row retryable by tap |
| Wrong qBittorrent credentials / IP ban | `QbitAuthError` / `QbitBanned` (client blocks login for 900 s / 3600 s) | `502 {"detail":"qbit_refused"}` and ERROR/WARNING line in logs; **never HTTP 401** | generic "something is wrong with the download service" text, no retry loop needed beyond normal polling |
| Invalid torrent (qBittorrent `torrents/add` answers 415: `APIErrorType::BadData`, "is not a valid torrent file") | pipeline `added.status_code` non-2xx → currently `FAILED` | map 415 to `JobState.UNAVAILABLE` | existing `unavailable` "Not available. Try another result." (retrying the same result cannot help) |
| Add answers 409 | `added.status_code == HTTP_CONFLICT` → `DUPLICATE` | unchanged | existing `duplicate` |
| Invalid category path (409 from `createCategory`/`editCategory`, or drift repair failing) | `bootstrap.sync_categories` / `repair_drift` raise `QbitError(status=409)` | job `failed` (logged with status) | `downloadFailed`; admin sees the 409 in logs |
| Throttled | new | `429 too_many_requests` | `MSG.throttled` "Too many requests. Wait a moment and try again." |
| Cancel races (already gone) | `DELETE` finds nothing | `404 download_not_found` | silent: refresh the list |

Add `torrents/add` 415 handling and a unit test in `test_download_pipeline.py`. `add_torrent` already "returns the status code without raising for 409 (already present) and 415" [VERIFIED: backend/app/qbit/client.py:286-288 docstring], but the pipeline only special-cases 409 today (pipeline.py:189-195).

### Pattern 8: Cancel / Remove flow

`DownloadPipeline.cancel(row_or_job)` (new, so job state, task, tags and torrent are changed in one place):
1. Re-read the row (`torrents_info(hashes=hash)`), recheck exact category.
2. Decide `delete_files` **server-side from live state**: `True` only when `progress < 1` **and** the plain state is one of `preparing/downloading/stalled/problem` (an in-progress download). `False` for `ready`, for `moving`, and for any state not recognised. A confirm tap on a row that completed a second ago therefore keeps the film (D-33).
3. Cancel the job first: `registry.cancel_for(hash)` finds the job with that `torrent_hash`, calls `task.cancel()`, awaits it, sets `job.state = CANCELLED`. Only then call `qbit.delete([hash], delete_files)`.
4. Best-effort `delete_tags([job_tag])` (same as `_discard`). Generalise `_discard(torrent_hash, job_tag)` to take `delete_files: bool = True` instead of writing a second helper.
5. Audit `cancel` or `remove` with the row name.
6. Return 204.

qBittorrent semantics verified from `TorrentsController::deleteAction` (release-5.2.4): `requireParams({"hashes","deleteFiles"})` (a missing `deleteFiles` is a 400, which is why `QbitClient.delete` always sends it), hashes split on `|`, an unknown hash is silently skipped and the call still returns an empty result (HTTP 200), `all` is special only when it is the sole entry. Never pass user-derived data to `hashes`; only a hash read from the row just fetched.

### Pattern 9: Caddy cache headers (verified by running `caddy:2.11.7-alpine`)

Current block [VERIFIED: web/Caddyfile:35-39]:
```
	handle {
		root * /srv/portal
		try_files {path} /index.html
		file_server
	}
```
Replace with two blocks (hashed assets must NOT fall back to `index.html`, or a missing asset would answer 200 HTML and be cached for a year):
```
	handle /assets/* {
		root * /srv/portal
		header {
			match status 2xx
			Cache-Control "public, max-age=31536000, immutable"
		}
		file_server
	}

	handle {
		root * /srv/portal
		header Cache-Control "no-cache"
		try_files {path} /index.html
		file_server
	}
```
Observed with a scratch site and `curl -si`:
```
/                      200  Cache-Control: no-cache
/index.html            200  Cache-Control: no-cache
/downloads             200  Cache-Control: no-cache   (SPA fallback)
/favicon.svg           200  Cache-Control: no-cache
/assets/index-abc123.js 200  Cache-Control: public, max-age=31536000, immutable
/assets/missing.js     404  (no Cache-Control)
conditional GET with If-None-Match -> 304 Not Modified, Cache-Control: no-cache
```
`caddy validate` printed `Valid configuration`. A Vite build of this repo emits `/assets/index-<hash>.js` and `/assets/index-<hash>.css` and `index.html` references them with absolute `/assets/...` paths (built this session into a scratch directory), so the `/assets/*` rule matches every hashed file. `Cache-Control: no-cache` means "revalidate" (not "do not store"): with the ETag Caddy sends, a revalidation is a cheap 304, and a redeploy is picked up on the next load. The existing global `header` block (CSP, nosniff, `-Server`) is unaffected.

### Pattern 10: Compose log rotation (verified with `docker compose config`)

```yaml
name: flatflix

x-logging: &default-logging
  driver: json-file
  options:
    max-size: "10m"
    max-file: "5"

services:
  backend:
    ...
    logging: *default-logging
```
Apply `logging: *default-logging` to all three services (`qbittorrent`, `backend`, `web`). `docker compose config` rendered the driver and options on each service. Docker defaults are `max-size` -1 (unlimited) and `max-file` 1, and `max-file` is only effective when `max-size` is set [CITED: docs.docker.com/engine/logging/drivers/json-file/]. `docker logs` works with the json-file driver and `docker inspect` showed `{"Type":"json-file","Config":{"max-file":"5","max-size":"10m"}}` (run this session). The base compose file is also loaded together with `docker-compose.admin.yml`; the anchor lives in the base file only.

### Pattern 11: WR-01 in `decide()`

Current logic [VERIFIED: backend/app/download/allowlist.py:115-118]:
```python
    videos = [f for f in files if final_extension(f.name) in VIDEO_EXTENSIONS]
    largest = max((f.size for f in videos), default=0)
    # Integer math: a video of exactly 10 % of the largest is kept (ratio 0.10 == 1/10).
    main_videos = {f.index for f in videos if not is_sample_name(f.name) and f.size * 10 >= largest}
```
Minimal change that preserves every existing test (including `test_a_mixed_mkv_and_webm_torrent_keeps_only_the_mkv` at 2 GB vs 2 GB and the exact-10 % boundary test): include non-sample videos of the other formats in `largest`:
```python
    videos = [f for f in files if final_extension(f.name) in VIDEO_EXTENSIONS]
    other = [
        f for f in files
        if final_extension(f.name) in OTHER_VIDEO_EXTENSIONS and not is_sample_name(f.name)
    ]
    largest = max((f.size for f in (*videos, *other)), default=0)
    main_videos = {f.index for f in videos if not is_sample_name(f.name) and f.size * 10 >= largest}
```
Result: 20 GB `Movie.m2ts` + 100 MB `Trailer.mp4` gives `main_videos == set()` and, because a non-sample other-format video exists, `reason="video_format"`, which the pipeline already maps to `JobState.UNSUPPORTED` with the existing text. 20 GB `.m2ts` + 4 GB `.mkv` is still accepted (the mkv is at least 10 % of the largest). Add tests for: large `.m2ts` + small `.mp4` (reject `video_format`), `.webm` + trailer with the trailer below 10 %, `.webm` + `.mkv` at exactly 10 % (accept), a sample-named large other-format file ignored. This is the fix proposed in WR-01 of 01-REVIEW.md (which computed `largest` over non-sample videos of both lists). See Assumption A1 and Open Question 1 for the wording conflict with D-43.

### Anti-Patterns to Avoid
- **Passing `category=` to `torrents/info` and trusting it.** It includes sub-categories; filter by equality in code.
- **Letting the browser send `deleteFiles` or a hash.** The server decides from live state.
- **Answering 401 for a qBittorrent credential failure.** `api()` shows the login page on any 401 (`if (res.status === 401 && path !== '/api/login' && unauthorizedHandler) unauthorizedHandler();` [VERIFIED: frontend/src/api.js:43]).
- **Unmounting `Search` on tab change.** Its cleanup bumps `runId` and `jobEpoch` and clears job timers (Search.jsx effect cleanup), so an in-flight Download POST result is dropped and the row restores as `lost`. Keep it mounted with the `hidden` attribute.
- **Inline `style` for the progress bar.** CSP is `style-src 'self'`.
- **Throttling poll endpoints.** The search poll alone is about 85 requests per minute.
- **A second state table in the frontend.** The frontend maps state codes to text only.
- **Logging `request.json()`, `request.headers`, `request.cookies` or a settings object** anywhere near an audit line.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Sliding-window limiter | A new counter/bucket class, or `slowapi` | `SlidingWindowThrottle` extracted from `LoginThrottle` | Already race-safe (check and record in one synchronous step), tested with a fake clock |
| Opaque ids | An id table with TTLs | `hmac` over the info-hash with `SECRET_KEY` | Stateless, restart-safe, nothing to leak or expire |
| Delete + tag cleanup | New delete code | `DownloadPipeline._discard` generalised with `delete_files` | Already handles the job-tag cleanup and `QbitError` logging |
| Hash/tag parsing | New parsing | `_tags_of`, `_job_tag_of`, `TAG_*` constants | Existing and tested |
| Client address | Reading `X-Forwarded-For` again | `request.client.host` | `TrustedProxyHeaders` already settles it (WR-02) |
| Confirm dialog | `<dialog>`/modal library | Inline two-button confirm inside the row | No `showModal` in jsdom; trivially testable; large tap targets |
| Progress bar | Width via inline style | `<progress max="100" value={n}>` | CSP-safe and accessible |
| Page visibility | A visibility library | `document.visibilityState` + `visibilitychange` | Two lines |
| Log rotation | A logrotate sidecar or a log volume | Docker `json-file` `max-size`/`max-file` | D-40; no extra service |
| Cache busting | A service worker or version query strings | Vite content-hashed filenames + Caddy headers | D-42 |
| qBittorrent state names | Re-deriving states from several fields | `plain_state()` keyed on the documented state string | One place; Phase 2.1 extends it |

**Key insight:** every hard part of this phase (race-safe throttling, safe deletes, tag handling, forwarded client address, leak canaries) already exists in Phase 1 code. The risk is wiring new features around those pieces incorrectly, not missing capability.

## Common Pitfalls

### Pitfall 1: Cancelling a Preparing download leaves its job task running
**What goes wrong:** The user cancels a Preparing row. The torrent is deleted, but the pipeline task is still in `_wait_for_files`, which treats the resulting 404 like an empty list ("A 404 from torrents/files right after a magnet add is retried like an empty list, bounded by METADATA_TIMEOUT" [VERIFIED: .planning/STATE.md, 01-12 decisions]). After up to `METADATA_TIMEOUT` (300 s) it calls `_discard` and sets `UNAVAILABLE`, which D-29 then lists for 24 h as a failure the user never caused.
**How to avoid:** Cancel the job task first and mark the job `CANCELLED` before deleting the torrent (Pattern 8). Test: add a magnet that never gets metadata, cancel it, advance time past `METADATA_TIMEOUT`, assert the list is empty.
**Warning signs:** An "Not available" row appearing minutes after a cancel.

### Pitfall 2: A cancelled started job blocks the next Download tap
**What goes wrong:** `submit()` returns the existing job when `active_for_result` finds a `STARTED` job younger than `STARTED_DEDUPE_SECONDS = 60` [VERIFIED: pipeline.py:53-54, 130-135]. A user who cancels and immediately re-taps Download gets the old "started" job and nothing is added.
**How to avoid:** `CANCELLED` is not in `ACTIVE_STATES`. Test: submit, cancel, submit again within 60 s, assert a second `torrents/add`.

### Pitfall 3: The 24 h failure window needs a finish time the job does not have
**What goes wrong:** `Job` has only `created_at`. A job that sat Preparing for 5 minutes then failed would expire 5 minutes early, and `MAX_JOBS = 500` pruning removes by insertion order without regard to age.
**How to avoid:** `finished_at` stamped in `_guard`. Pruning by oldest-finished is fine (500 jobs is far above household use).

### Pitfall 4: A 401 from the portal API logs the user out
**What goes wrong:** Mapping "wrong qBittorrent credentials" to HTTP 401 as in the spec table (section 13) makes `api()` call the unauthorized handler and show the login form while the real problem is server-side.
**How to avoid:** Use 502 with `detail` `qbit_refused`. A guard test: every route that catches `QbitAuthError`/`QbitBanned` must not return 401.

### Pitfall 5: Hiding the Search tab by unmounting it
See Anti-Patterns. Use `hidden` on the `<section class="search">` wrapper and add `[hidden] { display: none !important; }` to `styles.css` (author CSS such as `.search { display: flex }` would otherwise override the `hidden` attribute).

### Pitfall 6: Tab buttons collide with existing test queries
Existing tests use `screen.getByRole('button', { name: 'Search' })` for the submit button [VERIFIED: frontend/src/__tests__/Search.test.jsx submitSearch, App.test.jsx]. A tab named "Search" rendered as a `<button>` makes that query ambiguous and breaks about every Search test. Render the tabs as `<button role="tab" aria-selected=...>` inside `role="tablist"`: the explicit role takes them out of the `button` role query.

### Pitfall 7: Sub-category and other-category torrents
`torrents/info?category=Film` returns `Film/anything`. Filter by equality. Test with a fake torrent in `Film/Extra` and one in `Other`.

### Pitfall 8: The leak sweep calls every route with dummy parameters
`sweep_targets` in `test_no_leaks.py` substitutes `x` for path parameters and calls every method on every route, with and without a session [VERIFIED: backend/tests/test_no_leaks.py `sweep_targets`]. The new `DELETE /api/downloads/{id}` must return 404/422 for `x` and must never act on it, and the list response must not contain the forbidden keys (`"category"`, `save_path`, `content_path`, `/media/`, `magnet:`). Use `type`, not `category`, as the JSON key. Also add the new responses to the canary flow.

### Pitfall 9: Throttle slots consumed by the sweep and by retries
The leak sweep posts to `/api/search` and `/api/download` several times; with 10 searches per minute that stays under the limit, but tests that use the real clock and loop must set small limits through a fixture (swap `app.state.search_throttle` with a fake clock, as `test_login_throttle.py` does).

### Pitfall 10: `Retry-After` and countdowns
D-39 says no countdown. Send `Retry-After` for correctness but do not render it.

### Pitfall 11: Raw hash shown as a name
A magnet without `dn` reports the info-hash as `name` until metadata arrives (`FakeQbit._info_row` does the same: `"name": torrent.hash`). Substitute the job name or a placeholder (Pattern 2).

### Pitfall 12: Log forging and secrets via free text
Newlines in a torrent name or a search string can create fake audit lines; a password typed into the search box lands in the log by design of D-41. Sanitise (Pattern 5). Note this in `docs/setup.md`: the audit log contains what people searched for, and a person who types a secret into the search box puts it in the log.

### Pitfall 13: ETA text flicker and absurd values
`eta` jumps with speed. Round coarsely and omit it when null. Suggested `formatEta(s)`: `< 60` "less than a minute left"; `< 90 min` "about N min left" with N = ceil(s/60), rounded to the nearest 5 once N >= 10; `< 24 h` "about N h left" (nearest hour, minimum 2 once above 90 min); otherwise "more than a day left".

### Pitfall 14: `moving` and `checking` states
A finished torrent in `moving` is not at its final path yet; showing Ready there would let someone start looking for the file too early (and Phase 3/4 scanning could pick up a partial move). Map `moving` to `downloading` with no ETA, per Pattern 1.

### Pitfall 15: apostrophes in `messages.js`
`messages.js` uses the typographic apostrophe (`Can’t reach the server.`). CONTEXT writes the new strings with a straight `'`. Use `’` in `MSG` for consistency; tests must match the file's character.

## Code Examples

### State mapper (sketch)
```python
# app/download/listing.py
READY_STATES = frozenset({"uploading", "stalledUP", "stoppedUP", "queuedUP", "forcedUP", "checkingUP", "pausedUP"})
DOWNLOADING_STATES = frozenset({"downloading", "forcedDL", "moving"})
PREPARING_STATES = frozenset({"metaDL", "forcedMetaDL", "checkingResumeData", "checkingDL", "queuedDL"})
PROBLEM_STATES = frozenset({"error", "missingFiles"})
STOPPED_DL_STATES = frozenset({"stoppedDL", "pausedDL"})
MAX_ETA = 8640000  # qBittorrent's "infinite" ETA (src/base/types.h)

def plain_state(row: dict) -> str:
    state = str(row.get("state") or "")
    if state in READY_STATES:
        return "ready"
    if state in PROBLEM_STATES:
        return "problem"
    if state in DOWNLOADING_STATES:
        return "downloading"
    if state in PREPARING_STATES:
        return "preparing"
    if state in STOPPED_DL_STATES:
        return "preparing" if "fx-pending" in _tags_of(row) else "stalled"
    return "stalled"  # stalledDL and anything unknown: never claim Ready
```

### Opaque id
```python
import hashlib, hmac

def download_id(secret: str, torrent_hash: str) -> str:
    mac = hmac.new(secret.encode("utf-8"), b"download-id:" + torrent_hash.encode("utf-8"), hashlib.sha256)
    return mac.hexdigest()[:16]
```

### Throttle in a handler
```python
@router.post("/search", dependencies=[Depends(require_ready)])
async def start_search(body: SearchRequest, request: Request) -> dict[str, str]:
    ip = request.client.host if request.client else "unknown"
    retry_in = request.app.state.search_throttle.try_acquire(ip)
    if retry_in is not None:
        audit.throttled(ip, "search")
        raise HTTPException(429, "too_many_requests",
                            headers={"Retry-After": str(max(1, math.ceil(retry_in)))})
    audit.search(ip, body.type, body.q)
    ...
```

### Audit helper and redaction filter (sketch)
```python
audit_logger = logging.getLogger("app.audit")

def _t(value: str) -> str:  # free text: one line, quoted, truncated
    return json.dumps(value[:200], ensure_ascii=False)

def search(ip: str, content_type: str, q: str) -> None:
    audit_logger.info("event=search ip=%s type=%s q=%s", ip, content_type, _t(q))

class RedactingFilter(logging.Filter):
    def __init__(self, secrets: list[str]) -> None:
        super().__init__()
        self._secrets = [s for s in secrets if len(s) >= 8]
        self._patterns = [re.compile(r"QBT_SID\w*=[^;\s]+"), re.compile(r"flatflix_session=[^;\s]+")]

    def filter(self, record: logging.LogRecord) -> bool:
        text = record.getMessage()
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        for value in self._secrets:
            text = text.replace(value, "[redacted]")
            if record.exc_text:
                record.exc_text = record.exc_text.replace(value, "[redacted]")
        for pattern in self._patterns:
            text = pattern.sub("[redacted]", text)
        record.msg, record.args = text, ()
        return True
```

### Downloads polling hook (sketch)
```jsx
useEffect(() => {
  let alive = true, timer = null, epoch = 0;
  const hidden = () => document.visibilityState === 'hidden';
  async function load() {
    const mine = ++epoch;
    try {
      const data = await api('/api/downloads');
      if (!alive || mine !== epoch) return;
      setItems(data.items); setStale(false); setLoaded(true);
    } catch (err) {
      if (!alive || mine !== epoch) return;
      setStale(true); // keep the last known list (D-36)
    }
    schedule();
  }
  function schedule() { clearTimeout(timer); if (!hidden()) timer = setTimeout(load, 5000); }
  function onVisibility() { clearTimeout(timer); if (!hidden()) load(); }
  document.addEventListener('visibilitychange', onVisibility);
  load();
  return () => { alive = false; clearTimeout(timer); document.removeEventListener('visibilitychange', onVisibility); };
}, []);
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| qBittorrent 4.x state names `pausedUP`/`pausedDL` | 5.x `stoppedUP`/`stoppedDL` (plus `forcedMetaDL`) | qBittorrent 5.0 | Map both families; pinned image is 5.2.4, `MIN_WEBAPI_VERSION=2.15.1` |
| `torrents/pause` / `resume` | `torrents/stop` / `start` | 5.0 | Existing client already uses `start` |
| Unbounded Docker json logs | `max-size`/`max-file` per service | always required explicitly | Compose anchor |

**Deprecated/outdated:**
- The qBittorrent wiki page "WebUI API (qBittorrent 5.0)" still lists 4.x state names; use the 5.2.4 source for the pinned image.
- The portal spec (`qbit-wrapper.md` section 7) names `/api/torrents` and `DELETE /api/torrents/{hash}`; this phase deliberately deviates (`/api/downloads`, opaque id) to honor D-35 and PUI-02.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | D-43 is satisfied by the review's 10 % rule (the main video is the largest non-sample video of any format; an allowed video below 10 % of it does not count): "20 GB `.m2ts` + 4 GB `.mkv`" is still accepted, "20 GB `.m2ts` + 100 MB `.mp4`" is rejected as unsupported. A literal reading ("largest video not allowlisted, always reject") would also reject the first case and would break the existing equal-size mkv/webm test. | Pattern 11 | A user who wants the literal rule gets a different behavior for mixed-format torrents; needs user confirmation |
| A2 | A torrent that was already complete when added may report `completion_on` of -1 or 0; falling back to `added_on` for the 7-day window is acceptable | Pattern 1 | Admin-added complete torrents could vanish from the list too early or too late |
| A3 | uvicorn 0.54.0 gives `uvicorn.error` / `uvicorn.access` their own non-propagating handlers, so the redacting filter must be attached to them as well | Pattern 5 | If wrong the extra attachment is harmless; if right and skipped, access/error lines bypass redaction |
| A4 | `queuedDL` rows (waiting behind qBittorrent's active-download limit) are acceptable as "Preparing" | Pattern 1 | Household may see "Preparing" for a long time when many downloads are queued; a "Waiting" state could be added |
| A5 | No automatic re-POST of a failed Download tap is wanted; "automatic retry when unreachable" is satisfied by list polling (D-36) plus tap-to-retry on rows | Pattern 7 | If the user expects the add itself to auto-retry, extra pipeline work is needed |
| A6 | New environment variable names (`SEARCH_RATE_PER_MINUTE`, `DOWNLOAD_RATE_PER_MINUTE`, `COMPLETED_VISIBLE_DAYS`, `FAILED_VISIBLE_HOURS`) are Claude's choice | Pattern 4 | Cosmetic; rename freely before the first plan |
| A7 | Failed-attempt rows have no action (no dismiss button); they expire after 24 h | Pattern 2 | A user may want to dismiss a failure row; small UI addition |

## Open Questions

1. **D-43 wording vs the 10 % sample rule (Assumption A1)**
   - What we know: the original review fix and the existing tests keep the 10 % rule; D-43 says "if the largest video is not allowlisted, reject".
   - What's unclear: whether the user wants a torrent with a huge `.m2ts` plus a good-size `.mkv` rejected.
   - Recommendation: implement the 10 % rule (Pattern 11), record it in the plan as the interpretation, and let the discuss/verify step confirm.

2. **Does the household need to dismiss failed rows?**
   - What we know: D-29 shows them for 24 h with no action.
   - Recommendation: no dismiss in this phase.

3. **Auto-retry scope (Assumption A5)**
   - Recommendation: polling resumes on its own; Download rows keep tap-to-retry; no hidden re-POSTs (a retried add could race the btih duplicate check).

4. **Which wording for `problem` (qBittorrent `error` / `missingFiles`)**
   - Recommendation: one plain sentence telling her to ask the admin; planner picks the exact text and adds it to `MSG`.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Docker Engine + Compose | stack, Caddy and compose checks | yes | 29.7.2 / Compose v5.4.0 | — |
| `caddy:2.11.7-alpine` image | Caddyfile validation and header probes | yes (pulled this session) | 2.11.7 | — |
| `lscr.io/linuxserver/qbittorrent:5.2.4` image | opt-in integration guard | yes (local image present) | 5.2.4 | skip integration tests |
| `flatflix-backend` / `flatflix-web` images | stack run | yes (local) | latest | rebuild |
| uv | backend tests | yes | `/home/emanuele/.local/bin/uv` | — |
| Node + npm | frontend tests/build | yes | node via fnm, `node_modules` present | — |
| `/dev/kvm` | Firecracker | not needed in this phase | — | — |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none.

Baseline measured this session: `uv run --project backend --frozen pytest backend/tests infra/tests -q` gives 447 passed, 4 deselected (33 s); `npm --prefix frontend test` gives 135 passed in 5 files.

## Validation Architecture

`.planning/config.json` has no `workflow.nyquist_validation` key (only `workflow._auto_chain_active`), so this section is included.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | Backend: pytest 9.1.1 + pytest-asyncio 1.4.0 + respx 0.23.1 with `FakeQbit`; Frontend: vitest 5.0.5 + @testing-library/preact 3.2.4 + jsdom 30.1.3; Infra: pytest + PyYAML |
| Config file | `backend/pyproject.toml` (`asyncio_mode = "auto"`, integration marker deselected by default), `frontend/vite.config.js` (`test.environment = 'jsdom'`) |
| Quick run command | `uv run --project backend --frozen pytest backend/tests -x -q` and `npm --prefix frontend test` |
| Full suite command | quick commands plus `uv run --project backend --frozen pytest infra/tests -q`; stack probes `python3 scripts/smoke.py --base http://127.0.0.1 all` and the opt-in `QBIT_TEST_URL=http://127.0.0.1:8088 uv run --project backend --frozen pytest backend/tests/integration -m integration` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DOWN-04 | `plain_state` maps every one of the 19 qBittorrent state strings, `stoppedDL`+`fx-pending` = preparing, unknown = stalled, `moving` never ready | unit | `uv run --project backend --frozen pytest backend/tests/test_download_listing.py -q` | ❌ Wave 0 |
| DOWN-04 | list includes only exact `Film`/`SerieTV`; excludes `Film/Extra` and `Other`; includes admin-added torrents | API + FakeQbit | `... pytest backend/tests/test_downloads_api.py -q` | ❌ Wave 0 |
| DOWN-04 | progress floor, ETA null at 8640000, completed older than 7 d hidden, failed job older than 24 h hidden, ordering active-first/newest-first | unit | `... pytest backend/tests/test_download_listing.py -q` | ❌ Wave 0 |
| DOWN-04 | frontend polls every 5 s only when tab visible and page not hidden; refetch on `visibilitychange`; stale list greyed with banner on failure; banner clears | component (fake timers) | `npm --prefix frontend test -- Downloads` | ❌ Wave 0 |
| DOWN-04 | switching tabs keeps Search mounted and its saved state | component | `npm --prefix frontend test -- App` | partial (App.test.jsx exists) |
| DOWN-05 | cancel of in-progress calls `torrents/delete` with `deleteFiles=true`; completed uses `false`; progress 1.0 but `moving` uses `false` | API + FakeQbit (`fake.deleted`) | `... pytest backend/tests/test_downloads_api.py -q` | ❌ Wave 0 |
| DOWN-05 | cancel of Preparing cancels the job task, marks `cancelled`, no ghost failed row after `METADATA_TIMEOUT`; re-tap within 60 s adds again | API + FakeQbit | `... pytest backend/tests/test_download_cancel.py -q` | ❌ Wave 0 |
| DOWN-05 | DELETE with unknown id, a torrent in `Other`, or id `x` is 404/422 and deletes nothing | API | `... pytest backend/tests/test_downloads_api.py -q` | ❌ Wave 0 |
| DOWN-05 | row shows inline confirm "Cancel this download?"; one confirm tap sends one DELETE; completed row shows "Remove from list" | component | `npm --prefix frontend test -- DownloadRow` | ❌ Wave 0 |
| DOWN-06 | qBittorrent down gives 502 `qbit_unreachable`; bad credentials give 502 `qbit_refused` and never 401 | API | `... pytest backend/tests/test_downloads_api.py -q` | ❌ Wave 0 |
| DOWN-06 | `torrents/add` 415 gives job `unavailable`; 409 gives `duplicate` | pipeline | `... pytest backend/tests/test_download_pipeline.py -q` | partial (file exists) |
| DOWN-06 | no status code or raw backend text reaches the DOM for 0/401/429/502/503/404 | component | `npm --prefix frontend test` | extend existing tests |
| SEC-05 | 11th search within 60 s is 429 `too_many_requests` with `Retry-After`; poll routes never throttled; slot freed after the window; unauthenticated requests do not consume slots | API with fake clock | `... pytest backend/tests/test_rate_limit.py -q` | ❌ Wave 0 |
| SEC-05 | `LoginThrottle` import and behavior unchanged | unit | `... pytest backend/tests/test_login_throttle.py -q` | ✅ |
| SEC-05 | frontend shows `Too many requests. Wait a moment and try again.` on the search box and on a row (retryable) | component | `npm --prefix frontend test -- Search` | extend |
| SEC-06 | audit lines for login ok/fail/throttled, search (text, type), download requested/finished, cancel/remove (name), throttled, error; each has the client IP | API + `caplog` | `... pytest backend/tests/test_audit.py -q` | ❌ Wave 0 |
| SEC-06 | canary run: no password, hash, session cookie, `SECRET_KEY`, qBittorrent password or SID in any captured record, including exception text; newline in a torrent name or query yields one line | API + `caplog` | `... pytest backend/tests/test_audit.py -q` | ❌ Wave 0 |
| SEC-06 | `LOG_LEVEL=WARNING` still emits audit lines | unit | `... pytest backend/tests/test_audit.py -q` | ❌ Wave 0 |
| SEC-06 | every compose service has `json-file` with `max-size` and `max-file` | infra | `uv run --project backend --frozen pytest infra/tests -q` | extend `test_compose_invariants.py` |
| D-42 | Caddyfile: `/assets/*` handle sets immutable cache and has no `try_files`; fallback handle sets `no-cache` | infra (text) | `... pytest infra/tests -q` | ❌ Wave 0 |
| D-42 | served stack: `/` and `/downloads` no-cache; hashed asset from `index.html` immutable; missing asset 404 | smoke (Docker) | `python3 scripts/smoke.py --base http://127.0.0.1 cache` (new subcommand) | ❌ Wave 0 |
| D-43 | `decide()` cases from Pattern 11 | unit | `... pytest backend/tests/test_allowlist.py -q` | ✅ extend |
| all | leak sweep still clean with new routes and canary flow | API | `... pytest backend/tests/test_no_leaks.py -q` | ✅ extend |
| all | route enumeration: new routes behind `require_user` | API | `... pytest backend/tests/test_routes_protected.py -q` | ✅ automatic |
| all | settings validation for the four new variables, `.env.example` keys present | unit | `... pytest backend/tests/test_config.py -q` | ✅ extend |

### Sampling Rate
- **Per task commit:** the backend quick command (plus `npm --prefix frontend test` when frontend files changed). Both finish in about 40 s combined at baseline.
- **Per wave merge:** full suite (backend + infra + frontend).
- **Phase gate:** full suite green, `docker compose up -d --build --wait`, doctor, `smoke.py all` and the new cache probe, then manual phone check of: start a download, watch it in Downloads, cancel it, stop the qBittorrent container and watch the banner then restart it.

### Wave 0 Gaps
- [ ] `backend/tests/fakeqbit.py` — richer `torrents/info` rows: `name`, `progress`, `eta`, `completion_on`, `size`, an explicit `state` override, arbitrary `category`, helper to add a torrent without going through the pipeline (admin-added), optional failure injection (unreachable, auth refused). Today `_info_row` returns only `hash, name(=hash), category, tags, added_on, state, downloaded` [VERIFIED: backend/tests/fakeqbit.py:395-404].
- [ ] `backend/tests/test_download_listing.py`, `test_downloads_api.py`, `test_download_cancel.py`, `test_rate_limit.py`, `test_audit.py`
- [ ] `frontend/src/__tests__/Downloads.test.jsx`, `DownloadRow.test.jsx`, `eta.test.js`; extend `App.test.jsx` and `Search.test.jsx`
- [ ] `infra/tests` additions for logging and Caddy headers; `scripts/smoke.py` `cache` subcommand (every smoke subcommand ends with the leak scan, 01-09)
- [ ] Optional: one integration test against the real 5.2.4 engine asserting the fields the mapper reads (`state`, `progress`, `eta`, `completion_on`, `category`, `tags`, `name`) and `delete` with `deleteFiles=false` leaving files, using the Blender/synthetic-torrent helpers already in `backend/tests/integration/test_real_qbit.py`

## Security Domain

`security_enforcement` is not set in `.planning/config.json`, so it is treated as enabled.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no change (existing) | `protected_router()` + route-enumeration test cover the new routes |
| V3 Session Management | no change | unchanged cookie; note 401 semantics (Pitfall 4) |
| V4 Access Control | yes | Opaque HMAC id; server-side exact category re-check before any delete (D-35); server decides `deleteFiles` |
| V5 Input Validation | yes | Path parameter pattern `^[0-9a-f]{16}$`; no request body on DELETE; existing strict `extra="forbid"` bodies unchanged |
| V6 Cryptography | yes (small) | `hmac`/`hashlib` from the standard library keyed with `SECRET_KEY`; no hand-rolled primitives |
| V7 Error Handling and Logging | yes | Typed audit helpers, free-text sanitising, redacting filter, class-and-status-only exception logging |
| V11 Business Logic / rate limiting | yes | Sliding-window throttle on the two start routes |
| V14 Configuration | yes | Cache headers, log rotation, new env vars only in `.env.example` placeholders |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| IDOR: cancelling a torrent outside Film/SerieTV by guessing a hash | Tampering | The browser never holds a hash; id resolved only against rows whose category equals a configured name |
| Deleting a finished film through a stale confirm tap or a crafted request | Tampering / Information loss | `deleteFiles` decided server-side from live state; `False` unless clearly in progress |
| Log forging via newline in a search string or torrent name | Repudiation | `json.dumps` sanitising of free text, truncation |
| Secret in logs (typed password in username/search box, exception text, access log, SID header) | Information disclosure | No username on failed login; typed helpers; redacting filter on root and uvicorn handlers; canary tests |
| Request flooding of search/download from a script on the LAN | Denial of service | Per-address sliding window, 429 |
| Stale or poisoned cache serving an old SPA or HTML as an asset | Tampering | `no-cache` on `index.html`/fallback; immutable only on hashed `/assets/*` with no fallback and only for 2xx |
| qBittorrent text or status reaching the user | Information disclosure | Plain codes from backend, text only from `messages.js`; `test_no_leaks` extended |
| Unbounded Docker logs filling the disk | Denial of service | `json-file` `max-size`/`max-file` on every service |
| XSS via torrent names | Tampering | Names rendered only as Preact text children (existing rule in `ResultRow`) |
| CSRF on DELETE | Tampering | Session cookie is `SameSite=Lax` (not sent on cross-site non-GET subrequests); JSON-only bodies elsewhere. DELETE carries no body and is covered by Lax [ASSUMED: browser behavior per SameSite spec] |

## Sources

### Primary (HIGH confidence)
- qBittorrent `release-5.2.4` source, read from raw.githubusercontent.com this session: `src/webui/api/serialize/serialize_torrent.cpp` (state strings, field list, `completion_on`, `eta`), `src/base/bittorrent/torrentimpl.cpp` (`updateState`, `progress`, `eta`, `belongsToCategory`, `isCompleted`), `src/base/types.h` (`MAX_ETA = 8640000`), `src/base/utils/datetime.cpp` (`-1` for an invalid date), `src/webui/api/torrentscontroller.cpp` (`infoAction`, `deleteAction`, `addAction` error types), `src/base/torrentfilter.cpp` (`matchCategory`)
- Repo code read in full this session: `backend/app/{auth,config,main,proxy,content_type}.py`, `backend/app/download/{jobs,pipeline,allowlist}.py`, `backend/app/qbit/{client,bootstrap}.py`, `backend/app/routers/*.py`, `backend/app/search/service.py` (cache shape), `backend/tests/{conftest,fakeqbit,test_no_leaks,test_routes_protected,test_login_throttle}.py`, `frontend/src/*.{jsx,js,css}`, `web/Caddyfile`, `web/Dockerfile`, `docker-compose.yml`, `.env.example`, `docs/setup.md`
- Executed this session: `caddy:2.11.7-alpine` against the proposed Caddyfile (header matrix above); `docker compose config` with the proposed `x-logging` anchor; `docker run/inspect/logs` with json-file options; `vite build` into a scratch directory; baseline test runs; Python logging level check; jsdom `showModal` check
- CONTEXT, REQUIREMENTS, STATE, 01-REVIEW (WR-01), `qbit-wrapper.md` sections 5.3, 7, 8, 10, 13

### Secondary (MEDIUM confidence)
- https://docs.docker.com/engine/logging/drivers/json-file/ — `max-size`/`max-file` defaults and semantics
- https://caddyserver.com/docs/caddyfile/directives/header and `.../try_files` — `?`/`-` prefixes and response `match`; the docs do not state matcher/rewrite ordering, which is why the behavior was tested empirically instead
- qBittorrent wiki WebUI API (5.0) — `torrents/info` parameters and field descriptions; its state list is the 4.x one and was superseded by the source above

### Tertiary (LOW confidence)
- None used for recommendations. The only web search (`MAX_ETA`) returned nothing useful; the constant was confirmed from the source instead.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependencies; every version read from lockfiles/manifests
- Architecture: HIGH — built on code read in full; the riskiest interactions (job task vs cancel, dedupe window, 401 handling, Search unmount) were traced to specific lines
- qBittorrent behavior: HIGH — read from the 5.2.4 source of the pinned image tag
- Caddy and compose: HIGH — executed against the real images
- Pitfalls: HIGH for the code-traced ones; MEDIUM for the uvicorn handler propagation (A3) and `completion_on` of pre-completed torrents (A2)

**Research date:** 2026-10-22
**Valid until:** 2026-11-21 (re-check the state table and `deleteAction` only if the qBittorrent image tag changes)
