---
phase: 02-portal-download-management-hardening
reviewed: 2026-10-22T00:00:00Z
depth: standard
files_reviewed: 43
files_reviewed_list:
  - .env.example
  - backend/app/audit.py
  - backend/app/auth.py
  - backend/app/config.py
  - backend/app/content_type.py
  - backend/app/download/allowlist.py
  - backend/app/download/jobs.py
  - backend/app/download/listing.py
  - backend/app/download/pipeline.py
  - backend/app/main.py
  - backend/app/routers/auth.py
  - backend/app/routers/download.py
  - backend/app/routers/downloads.py
  - backend/app/routers/search.py
  - backend/app/throttle.py
  - backend/tests/fakeqbit.py
  - backend/tests/integration/test_real_downloads.py
  - backend/tests/test_allowlist.py
  - backend/tests/test_audit.py
  - backend/tests/test_download_cancel.py
  - backend/tests/test_download_listing.py
  - backend/tests/test_download_pipeline.py
  - backend/tests/test_downloads_api.py
  - backend/tests/test_no_leaks.py
  - backend/tests/test_rate_limit.py
  - docker-compose.yml
  - docs/setup.md
  - frontend/src/App.jsx
  - frontend/src/DownloadRow.jsx
  - frontend/src/Downloads.jsx
  - frontend/src/ResultRow.jsx
  - frontend/src/Search.jsx
  - frontend/src/__tests__/App.test.jsx
  - frontend/src/__tests__/DownloadRow.test.jsx
  - frontend/src/__tests__/Downloads.test.jsx
  - frontend/src/__tests__/ResultRow.test.jsx
  - frontend/src/__tests__/Search.test.jsx
  - frontend/src/__tests__/eta.test.js
  - frontend/src/eta.js
  - frontend/src/messages.js
  - frontend/src/styles.css
  - infra/tests/test_compose_invariants.py
  - scripts/smoke.py
  - web/Caddyfile
findings:
  critical: 0
  warning: 4
  info: 2
  total: 6
status: issues_found
---

# Phase 2: Code Review Report

**Reviewed:** 2026-10-22
**Depth:** standard
**Files Reviewed:** 43
**Status:** issues_found

## Summary

The phase is in good shape on the four focus areas. Backend (699) and infra tests pass, and `caddy validate` accepts the new Caddyfile.

- **No credential or path reaches the browser.** `build_items` emits a fixed seven-key dict: an HMAC id, name, type, state, progress, eta and action. `qbit_failure` logs only the class name and status, and the 502 `detail` is a fixed code. The DELETE route takes only a 16-hex opaque id, re-reads the torrent and re-checks its category server-side.
- **Rate-limit keying is sound.** The key is `request.client.host`, which `TrustedProxyHeaders` rewrites only for a trusted peer and from the right-most `X-Forwarded-For` entry. Caddy overwrites that header with `{remote_host}`. Slots are taken after the session, readiness and body checks, so anonymous or malformed requests never use one.
- **Redaction** is installed on the root and uvicorn handlers, keeps `record.args` structure, and covers exception text.
- **The cancel path** deletes files only when `cancel_deletes_files(row)` says so, and that is computed server-side.

The concerns are about how well the "never delete a completed film" guard holds up (WR-01, WR-02), an error path that strands a cancelled job's torrent (WR-03), and gaps in the redaction filter (WR-04).

## Warnings

### WR-01: "Completed" is judged by `progress` alone, so a finished film in a checking state can be offered "Cancel" and have its files deleted

**File:** `backend/app/download/listing.py:90-103`, `backend/app/download/listing.py:25-48`
**Issue:** `cancel_deletes_files` returns True for any state in `IN_PROGRESS_RAW_STATES` with `progress < 1`. That set includes `checkingResumeData`, `checkingDL`, `queuedDL`, `error` and `missingFiles`. qBittorrent reports a torrent that is checking, or has not loaded its resume data yet, with a progress that is not its final one. For `checkingResumeData` it is typically 0 right after a restart. A film that completed days ago can therefore read as `state=checkingResumeData, progress=0`. It then gets `action="cancel"`, and a tap on "Yes, cancel" sends `torrents/delete?deleteFiles=true`. This is the invariant the phase must never break, and the guard is a single heuristic. I did not reproduce this against the real engine (the integration suite has no such case), so it depends on qBittorrent's reporting during checks.
**Fix:** Require positive evidence that the torrent never finished before deleting files. qBittorrent reports `completion_on` as -1 until the torrent completes, and `amount_left` as the unwanted-excluded remainder.
```python
def cancel_deletes_files(row: dict) -> bool:
    if str(row.get("state") or "") not in IN_PROGRESS_RAW_STATES:
        return False
    try:
        if float(row.get("completion_on") or -1) > 0:   # it has finished at least once
            return False
        progress = float(row.get("progress") or 0)
    except (TypeError, ValueError):
        return False
    return math.isfinite(progress) and progress < 1
```
Add a listing test with `state="checkingResumeData", progress=0, completion_on=<past>` that expects `action == "remove"`.

### WR-02: Time-of-check/time-of-use gap between reading the row and `torrents/delete?deleteFiles=true`

**File:** `backend/app/download/pipeline.py:362-387`
**Issue:** `cancel()` reads `rows`, computes `deletes = cancel_deletes_files(row)`, then awaits `registry.cancel_for(...)`. That call cancels the job task and awaits it, so it can take noticeable time while a plugin request or qBittorrent call unwinds. Only then does it call `_discard(..., delete_files=deletes)`. A torrent at 99.x% can finish in that gap, and the delete still runs with `deleteFiles=true`. The docs and D-33 promise that a download that finished a second earlier keeps its film, but the decision is made before the slow step and not re-checked.
**Fix:** Re-read the single torrent right before the delete and decide on that row.
```python
job = await self._registry.cancel_for(...)
fresh = await self._qbit.torrents_info(hashes=torrent_hash)
deletes = cancel_deletes_files(fresh[0]) if fresh else False
await self._discard(torrent_hash, job_tag, delete_files=deletes)
```
This still leaves a few milliseconds of risk, but qBittorrent state is then at most one round trip old.

### WR-03: A failed sweep in `_cancel_job_without_torrent` leaves a cancelled job's torrent stranded, hidden, and possibly resumed

**File:** `backend/app/download/pipeline.py:391-407`
**Issue:** The method cancels the job first (`cancel_for`, state becomes `CANCELLED`), then runs `await self._sweep_once(job_tag)`, and starts the background sweep only after that returns. If `_sweep_once` raises `QbitError` (qBittorrent hiccup, for example `torrents_info` or `delete`), the error propagates to the route as a 502 and `_start_sweep` is never reached. The result:
- The job is now `CANCELLED`, so a retry tap gets 404 (`job.state is not PREPARING`).
- Its torrent keeps `fx-pending` and `fx-job-<id>`, and `build_items` hides it because its job is cancelled.
- Nothing will ever delete it. If the backend restarts within `METADATA_TIMEOUT`, `reconcile` finds the pending torrent with an unknown job and runs it through the allowlist and starts it. That is a download the household cancelled.

The sibling path in `cancel()` handles this correctly (it starts the sweep on `QbitError` before re-raising), so this is an inconsistency.
**Fix:**
```python
await self._registry.cancel_for(job_id=job_id)
job_tag = TAG_JOB_PREFIX + job_id
self._start_sweep(job, job_tag, job.created_at + self._settings.metadata_timeout)
await self._sweep_once(job_tag)   # a failure now only means the sweep retries
return CancelOutcome("cancel", job.name, True)
```
Start the sweep first, and treat a failing first sweep as non-fatal (log and return the outcome), or re-raise only after the sweep is running.

### WR-04: `RedactingFilter` skips non-string `record.msg` and short secrets, though its docstring and docs promise "never written"

**File:** `backend/app/audit.py:26-27`, `backend/app/audit.py:151-153`
**Issue:**
1. `filter()` redacts `record.msg` only when it is a `str`. A call like `logger.error(exc)` or `logger.warning(some_object)` formats `str(record.msg)` later, with no redaction. `_arg` handles non-str args but `msg` gets no equivalent.
2. Secrets shorter than `MIN_SECRET_LENGTH = 8` are skipped. `Settings` enforces no minimum length on `QBITTORRENT_PASS`, so a short qBittorrent password would never be redacted, while `docs/setup.md` states the qBittorrent credentials "are never written".

Nothing in the current code logs these values (the review found no such call), so this is defence in depth that has holes.
**Fix:** For the first, treat `msg` like an argument: `record.msg = self._arg(record.msg) if not isinstance(record.msg, str) else self.redact(record.msg)`. For the second, enforce a minimum length on `QBITTORRENT_PASS` in `Settings._check_pass`, or reword the docs to say passwords under 8 characters are not filtered from log text.

## Info

### IN-01: `SlidingWindowThrottle._attempts` never evicts addresses that do not come back

**File:** `backend/app/throttle.py:105-129`
**Issue:** Stale per-address deques are removed only when that same address calls `try_acquire` again. The search and download throttles have no global ceiling (D-38), so the dict holds every address that was ever seen until restart. The login throttle is bounded by its global ceiling, but the other two are not. The population is limited to authenticated clients on a household LAN, so this is minor. A client that rotates IPv6 source addresses grows the dict slowly.
**Fix:** Sweep expired keys in `try_acquire`, for example by dropping entries whose last timestamp is `<= cutoff` when `len(self._attempts)` passes a threshold, or key IPv6 clients by /64.

### IN-02: Client-address helper duplicated in five places

**File:** `backend/app/routers/downloads.py:31`, `backend/app/routers/search.py:285`, `backend/app/routers/download.py:121`, `backend/app/routers/auth.py:179`, `backend/app/routers/auth.py:209`
**Issue:** `request.client.host if request.client else "unknown"` is written inline three times and as `client_ip()` twice. The IP is the throttle key and the audit field, so the keying rule should live in one function. A later change (for example IPv6 /64 grouping from IN-01) would otherwise need five edits, and one missed edit would give the audit log and the limiter different keys.
**Fix:** Put `client_ip(request)` in `app/netutil.py` or `app/auth.py` and import it in every router.

---

_Reviewed: 2026-10-22_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
