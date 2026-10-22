# Phase 2: Portal Download Management & Hardening - Pattern Map

**Mapped:** 2026-10-22
**Files analyzed:** 27 (11 new, 16 modified)
**Analogs found:** 27 / 27 (all analog paths verified git-tracked)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match |
|---|---|---|---|---|
| `backend/app/throttle.py` (new) | utility | request-response | `backend/app/auth.py` `LoginThrottle` (lines 59-121) | exact (extract) |
| `backend/app/audit.py` (new) | utility | event-driven | `backend/app/main.py` `configure_logging` + `routers/search.py` `unavailable()` logging | role-match |
| `backend/app/download/listing.py` (new) | service (pure) | transform | `backend/app/download/allowlist.py` (pure, no I/O) + `pipeline.py` `_tags_of/_job_tag_of` | role-match |
| `backend/app/routers/downloads.py` (new) | route | CRUD (list + delete) | `backend/app/routers/download.py` | exact |
| `backend/app/download/jobs.py` (edit) | model | event-driven | itself | exact |
| `backend/app/download/pipeline.py` (edit) | service | event-driven | itself (`_discard`, `submit`, `_add_and_process`) | exact |
| `backend/app/download/allowlist.py` (edit) | utility | transform | itself (`decide`, lines ~108-131) | exact |
| `backend/app/routers/download.py`, `search.py`, `auth.py` (edit) | route | request-response | `routers/auth.py` login throttle block (lines 24-37 of that file) | exact |
| `backend/app/config.py` (edit) | config | n/a | `login_max_attempts` / `download_wait_seconds` Fields | exact |
| `backend/app/main.py` (edit) | config | n/a | itself (`login_throttle` build, include_router, `configure_logging`) | exact |
| `backend/app/content_type.py` (edit) | utility | transform | `qbit_category` there | exact |
| `backend/tests/test_throttle*.py`, `test_downloads_*.py`, `test_audit*.py`, `test_listing.py` (new) | test | request-response | `backend/tests/test_login_throttle.py`, `test_download_pipeline.py`, `test_no_leaks.py` | exact |
| `backend/tests/test_allowlist.py`, `test_no_leaks.py`, `test_routes_protected.py` (edit) | test | n/a | themselves | exact |
| `backend/tests/fakeqbit.py` (edit if needed) | test util | n/a | itself | exact |
| `frontend/src/App.jsx` (edit) | component | request-response | itself | exact |
| `frontend/src/Downloads.jsx` (new) | component | polling | `frontend/src/Search.jsx` (epoch + setTimeout chain) | role-match |
| `frontend/src/DownloadRow.jsx` (new) | component | request-response | `frontend/src/ResultRow.jsx` | exact |
| `frontend/src/eta.js` (new) | utility | transform | no direct analog (pure fn; see RESEARCH Pitfall 13) | none |
| `frontend/src/messages.js`, `styles.css` (edit) | config | n/a | themselves | exact |
| `frontend/src/Search.jsx`, `ResultRow.jsx` (edit) | component | request-response | themselves (`MESSAGE`, `JOB_STATES`, `RETRYABLE`) | exact |
| `frontend/src/__tests__/Downloads.test.jsx`, `DownloadRow.test.jsx`, `eta.test.js` (new); `App.test.jsx` (edit) | test | n/a | `frontend/src/__tests__/App.test.jsx` (stubApi + fake fetch) | exact |
| `web/Caddyfile` (edit) | config | n/a | itself lines 35-39 | exact |
| `docker-compose.yml` (edit) | config | n/a | itself | exact |
| `.env.example`, `docs/setup.md` (edit) | config/docs | n/a | themselves | exact |
| `infra/tests/test_compose_invariants.py` (edit) / new Caddyfile test | test | n/a | `_load_yaml(name)` helper (line ~38) | exact |

## Pattern Assignments

### `backend/app/throttle.py` (utility, request-response)

**Analog:** `backend/app/auth.py` lines 59-121 (`LoginThrottle`). Move the body unchanged into `SlidingWindowThrottle`; keep `LoginThrottle` importable from `app.auth` (alias or trivial subclass) so `test_login_throttle.py` (`from app.auth import LoginThrottle`, swaps `app.state.login_throttle`) and `main.py` stay untouched.

**Core API to preserve** (auth.py 78-92, 118-121):
```python
def __init__(self, max_attempts: int = 5, window_seconds: float = 900,
             clock: Callable[[], float] = time.monotonic,
             global_max_attempts: int | None = None) -> None: ...
def try_acquire(self, ip: str) -> float | None:   # None = allowed+recorded, float = seconds to wait
def reset(self, ip: str) -> None:
```
Check-and-record stays one synchronous step (no `await`). Search/download: `global_max_attempts=None`, window 60 s.

**Wiring** (`main.py` lines 78-84, built in `create_app`, not lifespan):
```python
app.state.login_throttle = LoginThrottle(
    max_attempts=settings.login_max_attempts,
    window_seconds=settings.login_window_seconds,
    global_max_attempts=settings.login_global_max_attempts,
)
```
Add `app.state.search_throttle` / `app.state.download_throttle` the same way (`window_seconds=60`).

---

### `backend/app/routers/downloads.py` (route, CRUD)

**Analog:** `backend/app/routers/download.py`

**Imports/router** (lines 8-19):
```python
import asyncio
from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from app.auth import protected_router
from app.qbit.bootstrap import require_ready
router = protected_router()
RESULT_ID_PATTERN = r"^[0-9a-f]{16}$"
```
Path param: `Path(pattern=RESULT_ID_PATTERN)` (reuse the constant). Keep the docstring rule "no hash, save path, category or URL reaches the browser". JSON key is `type`, never `category`.

**Handler shape** (download.py 36-49, 52-57): `@router.post("/download", dependencies=[Depends(require_ready)])`, state from `request.app.state.{pipeline,jobs,settings,qbit}`, `HTTPException(status_code=..., detail="snake_code")`. Not-found uses `detail="download_not_found"` (404, same style as `job_not_found`). qBittorrent failure: catch `QbitUnavailable` -> `HTTPException(502, "qbit_unreachable")`; `QbitAuthError/QbitBanned` -> `502 "qbit_refused"`, NEVER 401 (api.js line 129 would log the user out).

**Error logging convention** (`routers/search.py` 73-76):
```python
def unavailable(exc: QbitError) -> HTTPException:
    logger.warning("search failed: %s (HTTP %s)", type(exc).__name__, exc.status)
    return HTTPException(status_code=503, detail="search_unavailable")
```

**Qbit calls:** `QbitClient.torrents_info(...)` (client.py 312), `delete(hashes, delete_files)` (351), `delete_tags` (366) already exist; no client change needed. Filter category by equality in code, not via `category=` param.

---

### `backend/app/download/listing.py` (service, transform; pure)

**Analog:** `allowlist.py` (pure module, no I/O) and tag helpers in `pipeline.py` lines 6-8, 26-31:
```python
TAG_PORTAL = "fx"; TAG_PENDING = "fx-pending"; TAG_JOB_PREFIX = "fx-job-"
def _tags_of(row: dict) -> list[str]:
    return [t.strip() for t in str(row.get("tags") or "").split(",") if t.strip()]
def _job_tag_of(tags: list[str]) -> str | None:
    return next((t for t in tags if t.startswith(TAG_JOB_PREFIX)), None)
```
Import/move these rather than re-implementing. State sets, `plain_state`, `download_id` (HMAC, 16 hex) and `build_items` sketches are in 02-RESEARCH.md "Code Examples" and Patterns 1-3. Existing state-constant style: `NOT_STARTED_STATES = frozenset({...})` (pipeline.py line 18).

---

### `backend/app/download/jobs.py` (edit, model)

Add to `JobState` (lines 24-33) `CANCELLED = "cancelled"` (NOT in `ACTIVE_STATES`, line 36). Add to `Job` dataclass (lines 39-47) `name: str | None = None`, `finished_at: float | None = None` (defaults, `slots=True`). Stamp `finished_at` (and emit `audit.download_finished`) in `JobRegistry._guard` (lines 76-89), the single place every task ends. Add `cancel_for(torrent_hash)`: cancel + await task (mirror `shutdown`, lines 103-108: `task.cancel(); await asyncio.gather(*tasks, return_exceptions=True)`), set `CANCELLED`. `_prune` (91-101) may need oldest-finished ordering.

---

### `backend/app/download/pipeline.py` (edit, service)

- `_discard` (lines ~316-323) -> add `delete_files: bool = True`:
```python
async def _discard(self, torrent_hash: str, job_tag: str) -> None:
    await self._qbit.delete([torrent_hash], True)
    try:
        await self._qbit.delete_tags([job_tag])
    except QbitError as exc:
        logger.warning("tag cleanup failed after delete: %s", type(exc).__name__)
```
- New `cancel(...)`: re-read row, exact category check, decide `delete_files` from live state (Pattern 8), `registry.cancel_for` first, then `_discard`.
- 415 from `add_torrent`: only 409 handled now (~lines 189-195, `HTTP_CONFLICT`); add `HTTP_UNSUPPORTED_MEDIA = 415` -> `JobState.UNAVAILABLE`.
- Capture `name` in `submit` (cached.name) and in `reconcile` (`row["name"]`, Job built at ~line 56).
- `STARTED_DEDUPE_SECONDS` (line 15) behavior depends on CANCELLED not being active.

---

### `backend/app/download/allowlist.py` (edit, WR-01)

Edit `decide()` lines ~115-118 exactly as RESEARCH Pattern 11 (include non-sample `OTHER_VIDEO_EXTENSIONS` files in `largest`). Rejection reason branch (`video_format` vs `no_video`) already exists; no pipeline mapping change. Open question A1 (D-43 literal wording vs 10 % rule) should be settled by planner/user. Tests go in `backend/tests/test_allowlist.py`.

---

### Route edits: throttle + audit in `routers/search.py`, `routers/download.py`, `routers/auth.py`

**Analog:** `routers/auth.py` lines 24-37 (login):
```python
ip = request.client.host if request.client else "unknown"
retry_in = throttle.try_acquire(ip)
if retry_in is not None:
    raise HTTPException(status_code=429, detail="too_many_attempts",
                        headers={"Retry-After": str(max(1, math.ceil(retry_in)))})
```
Use `detail="too_many_requests"`; call inside handler after body validation (after `Depends(require_ready)`); only on `POST /search` and `POST /download`. Add `audit.*` calls; do not log the attempted username. `routers/download.py` `job_body` (line 32) stays `{status, job_id}`; `cancelled` must be handled by the frontend.

---

### `backend/app/audit.py` + `main.py` `configure_logging` (utility, event-driven)

**Analog:** `main.py` lines 26-32:
```python
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
def configure_logging(level: str) -> None:
    logging.basicConfig(level=level, format=LOG_FORMAT)
    logging.getLogger().setLevel(level)
    logging.getLogger("httpx").setLevel(logging.WARNING)
```
Extend: `logging.getLogger("app.audit").setLevel(logging.INFO)` (independent of `LOG_LEVEL`), install a redacting `logging.Filter` on root and `uvicorn.*` handlers. Module logger convention: `logger = logging.getLogger(__name__)`. Free text via `json.dumps(v[:200], ensure_ascii=False)`. Exception convention: class name + status only (jobs.py line 83: `logger.error("download job %s crashed: %s", job.job_id, type(exc).__name__)`).

---

### `backend/app/config.py` (edit)

**Analog:** lines 58, 100: `login_max_attempts: int = Field(default=5, ge=1)`, `download_wait_seconds: float = Field(default=15, ge=0)`. New: `search_rate_per_minute=10`, `download_rate_per_minute=20`, `completed_visible_days=7`, `failed_visible_hours=24` (all `Field(default=..., ge=1)`). Mirror in `.env.example` and `docs/setup.md`; `backend/tests/test_config.py` covers Settings.

---

### Backend tests

- `test_login_throttle.py` pattern (lines 1-30): `FakeClock` class, fixture swapping `app.state.<x>_throttle` with the fake clock, `api: httpx.AsyncClient`, `assert response.status_code == 429`, `response.json() == {"detail": ...}`, `int(response.headers["retry-after"])`.
- `conftest.py`: `settings` fixture builds `Settings(...)` from explicit kwargs; `fake_qbit` (`tests/fakeqbit.py`, `_info_row` returns `name = hash` for magnets).
- `test_routes_protected.py`: enumerates routes via `protected_router`; new router must pass `unprotected_routes(app) == []`; sweep replaces `{id}` with `x` -> new DELETE must 404/422 and never act.
- `test_no_leaks.py`: forbidden keys (`"category"`, `save_path`, `content_path`, `/media/`, `magnet:`); add canary test that secrets (`SECRET_KEY`, qbit pass, hash, SID, session cookie) never appear in captured log records.
- Pipeline tests (`test_download_pipeline.py`): cancel Preparing then advance past `METADATA_TIMEOUT` -> list empty; cancel then re-submit within 60 s -> second add; 415 -> `unavailable`.

---

### `frontend/src/App.jsx` (edit, component)

**Analog:** itself lines 61-73 (`view === 'in'` block with `<header class="app-header">` and `<main class="app"><Search /></main>`). Add `const [tab, setTab] = useState('search')`; tablist with `<button role="tab" aria-selected=...>` inside `role="tablist"` (so `getByRole('button', {name:'Search'})` in existing tests is not ambiguous). Keep `<Search />` mounted: wrap in `<section hidden={tab !== 'search'}>`; mount `<Downloads />` only when active (unmount stops polling, D-31). Add `[hidden] { display: none !important; }` to `styles.css`. `logout()` (lines 17-27) calls `clearSavedSearch()` first; keep.

---

### `frontend/src/Downloads.jsx` (component, polling)

**Analog:** `Search.jsx` discipline: `useRef` run id (`if (run !== runId.current) return;`), `setTimeout` chain with constants at top (`const POLL_MS = 700; const JOB_POLL_MS = 2000;`), cleanup in `useEffect` bumping the epoch. Use `api` from `./api.js`, `ApiError` (`status === 0` = unreachable), text from `MSG` only. 5000 ms; visible unless `document.visibilityState === 'hidden'`; `visibilitychange` listener refetches immediately; on error keep items, `stale=true`, show `MSG.downloadServiceDown` as `<p class="banner" role="status">` (same markup as App.jsx lines 78-82), disable Cancel/Remove while stale.

```js
import { useEffect, useRef, useState } from 'preact/hooks';
import { api, ApiError } from './api.js';
import { MSG } from './messages.js';
```

---

### `frontend/src/DownloadRow.jsx` (component, request-response)

**Analog:** `frontend/src/ResultRow.jsx`: lookup tables (`LOCKED_LABEL`, `MESSAGE` keyed by state with `{text, tone}`), `<li class="result">`, `<button class="btn btn-primary" type="button" disabled={...}>`, `<p class={`row-state row-state-${tone}`} role="status">`, spinner `<span class="spinner" aria-hidden="true" />`. Names rendered as text children only (attacker-controlled). Use `<progress max="100" value={n}>` (CSP: no inline style). Inline two-button confirm ("Cancel this download?"), no `<dialog>`. State code -> text map only (no second state table; backend `plain_state` is authoritative).

---

### `frontend/src/messages.js` (edit)

**Analog:** itself. Flat `MSG` object, typographic apostrophe `’`. Add: downloads tab labels, states (Preparing exists as `preparing`; add downloading/ready/stalled/problem), `downloadServiceDown: 'Can’t reach the download service. Retrying…'`, `throttled: 'Too many requests. Wait a moment and try again.'`, `cancelConfirm: 'Cancel this download?'`, `removeFromList`, ETA strings. Existing failure texts (`rejected`, `unsupportedFormat`, `unavailable`, `downloadFailed`) are reused for failed rows.

---

### `frontend/src/Search.jsx` / `ResultRow.jsx` (edit)

429 mapping: add `throttled` to `ResultRow.MESSAGE` (`{text: MSG.throttled, tone:'warn', retry:true}`), add to `RETRYABLE` (Search.jsx line 10) and `ROW_STATES` (line 28). Handle a `cancelled` job status (add to `JOB_STATES` set lines 12-20 or map to retryable). Search-box throttle on `POST /api/search` 429 -> `MSG.throttled`.

---

### `web/Caddyfile` (edit)

**Analog:** itself lines 35-39 (`handle { root * /srv/portal; try_files {path} /index.html; file_server }`). Replace with two blocks exactly as RESEARCH Pattern 9 (`handle /assets/*` with `header { match status 2xx; Cache-Control "public, max-age=31536000, immutable" }` and no `try_files`; fallback `handle` with `header Cache-Control "no-cache"`). Keep global `header` CSP block untouched.

### `docker-compose.yml` (edit)

Add top-level `x-logging: &default-logging {driver: json-file, options: {max-size: "10m", max-file: "5"}}` after `name: flatflix`; `logging: *default-logging` under services `qbittorrent` (line 6), `backend` (44), `web` (64). Not in `docker-compose.admin.yml`. Test with `_load_yaml("docker-compose.yml")` in `infra/tests/test_compose_invariants.py` (loader at ~line 38) asserting each service has `logging.driver == "json-file"` and the two options.

## Shared Patterns

### Protected routes
**Source:** `backend/app/auth.py` lines 33-35 (`protected_router`). **Apply to:** `routers/downloads.py`. Route-enumeration test fails otherwise.

### Readiness gate
**Source:** `Depends(require_ready)` in `routers/download.py` line 36. **Apply to:** `GET/DELETE /api/downloads` (consider; list is needed only when qBittorrent reachable, so 503 `not_ready` vs 502 must map to a plain message).

### Error detail codes
`HTTPException(status_code=N, detail="snake_code")`; frontend `api()` surfaces `ApiError(status, code)`; never show code/status (D-37). Never 401 for qBittorrent failures.

### Client address
`ip = request.client.host if request.client else "unknown"` (routers/auth.py line 27); already the forwarded address via `TrustedProxyHeaders`. Do not re-read `X-Forwarded-For`.

### Logging safety
Log exception class + status only; typed audit helpers; never request body/headers/cookies/settings.

### Frontend CSP and text
No inline styles, all strings in `MSG`, `no-third-party` frontend test and repo-hygiene scanner (`infra/tests/test_repo_hygiene.py`) must keep passing.

### Frontend test harness
**Source:** `frontend/src/__tests__/App.test.jsx` lines 1-37 (`jsonResponse`, `stubApi` with `vi.stubGlobal('fetch', vi.fn(async (path) => ...))`, `afterEach(cleanup; vi.unstubAllGlobals(); sessionStorage.clear())`). Use `vi.useFakeTimers()` for the 5 s poll. jsdom: `visibilityState` is `prerender`, no `showModal`.

## No Analog Found

| File | Role | Data Flow | Reason |
|---|---|---|---|
| `frontend/src/eta.js` | utility | transform | No existing formatter; use RESEARCH Pitfall 13 rules |
| `backend/app/audit.py` redacting `logging.Filter` | utility | event-driven | No existing log filter/redaction; use RESEARCH Pattern 5 (uvicorn handler behavior is ASSUMED, verify in test) |
| Page Visibility handling | hook | event-driven | Not used anywhere yet; use RESEARCH Pattern 6 |

## Metadata

**Analog search scope:** `backend/app`, `backend/tests`, `frontend/src`, `web/`, `docker-compose*.yml`, `infra/tests`
**Files scanned:** about 20 read in full or in part; `git ls-files` confirmed all analogs tracked
**Pattern extraction date:** 2026-10-22
