---
phase: 02-portal-download-management-hardening
reviewed: 2026-10-23T00:00:00Z
depth: standard
files_reviewed: 8
files_reviewed_list:
  - backend/app/audit.py
  - backend/app/download/listing.py
  - backend/app/download/pipeline.py
  - backend/tests/test_audit.py
  - backend/tests/test_download_cancel.py
  - backend/tests/test_download_listing.py
  - backend/tests/test_downloads_api.py
  - docs/setup.md
findings:
  critical: 0
  warning: 1
  info: 3
  total: 4
status: issues_found
---

# Phase 2: Code Review Report (incremental re-review of the WR-01..WR-04 fixes)

**Reviewed:** 2026-10-23
**Depth:** standard
**Files Reviewed:** 8 (fix diff `73f5bff..HEAD`, plus `jobs.py`, `qbit/client.py` and the integration test read for context)
**Status:** issues_found

## Summary

WR-01..WR-04 are resolved in code and covered by tests (244 tests in the four touched test files pass). I found no critical issue and no new logic bug in the changed code. Cancel cannot delete the files of a torrent that has finished once, and I found no path where an in-progress cancel fails to remove the torrent.

- **WR-01 resolved.** `cancel_deletes_files` now needs a known in-progress state, `progress < 1` and `completion_on` that is missing, empty or `<= 0`. A positive, non-finite or unparsable `completion_on` reads as finished and keeps the files. NaN is handled correctly: `not nan <= 0` is True, so it returns False. A finished film that reads as `checkingResumeData` with progress 0 now gets `remove`.
- **WR-02 resolved.** `cancel()` re-reads the single torrent after `registry.cancel_for` and decides on that row. The re-read is inside the `try`, so a failed read starts the sweep for a job-tagged torrent, raises, and deletes nothing. A torrent that is gone gets `deleteFiles=false` and an idempotent delete. The window is now one HTTP round trip.
- **WR-03 resolved.** The sweep is spawned before the first `_sweep_once`, and a `QbitError` there is logged and swallowed, so the tap answers 204 and a retry is not needed. Race check: the foreground sweep and the background sweep's first round can run at the same time. At worst they both `delete` the same hash, which qBittorrent treats as a no-op, so this is harmless.
- **WR-04 resolved.** A non-string `record.msg` is redacted through `_arg`, and the original object is kept when nothing needs redacting. The short-secret gap is documented in `docs/setup.md` and next to `MIN_SECRET_LENGTH` instead of being enforced. That is an acceptable choice and I did not re-raise it.

The one new concern is that the WR-01 guard relies on a qBittorrent behaviour that no test checks against the real engine (WR-05).

## Warnings

### WR-05: The "never completed" signal (`completion_on <= 0`) is never checked against the real qBittorrent, so a different sentinel would silently turn every cancel into a "remove"

**File:** `backend/app/download/listing.py:101-110`, `backend/tests/integration/test_real_downloads.py:89`, `backend/tests/integration/test_real_downloads.py:113-133`
**Issue:** `cancel_deletes_files` now treats any positive `completion_on` as "this film finished". That is right if qBittorrent 5.2.4 reports -1 or 0 until the first completion. The comment and `fakeqbit.py` say it does, but the fake was written from the same assumption. Some older qBittorrent builds are reported to answer a large positive value (for example `4294967295`) for a torrent that never completed. If the pinned image did that, every in-progress download would read as finished: the button would say "Remove" and a cancel would leave the partial files behind (a data-hygiene failure, not data loss). The unit tests cannot catch this. The integration test only asserts `isinstance(row["completion_on"], int)`. Its cancel test checks that the torrent disappears, not that the list said `cancel` or that the files went (the torrent is still downloading from a Blender open-movie magnet, so it is a real unfinished one).
**Fix:** Pin the assumption in the opt-in real-engine suite, in `test_a_film_torrent_is_listed_with_the_fields_the_mapper_reads` and the cancel test:
```python
assert row["completion_on"] <= 0          # never completed: no finish time yet
...
assert item["action"] == "cancel"         # an unfinished torrent is offered "cancel"
```
Run the suite once against the pinned `5.2.4` image. If it fails, switch to a signal the engine documents, for example `amount_left > 0` together with `progress < 1`.

## Info

### IN-01: `SlidingWindowThrottle._attempts` never evicts addresses that do not come back

**File:** `backend/app/throttle.py:44-70`
**Issue:** Stale per-address deques are removed only when that same address calls `try_acquire` again. The search and download throttles have no global ceiling (D-38), so the dict holds every address ever seen until restart. The population is limited to authenticated clients on a household LAN, so this is minor. A client that rotates IPv6 source addresses grows the dict slowly. Not in the fix scope, unchanged.
**Fix:** Sweep expired keys in `try_acquire` when `len(self._attempts)` passes a threshold, or key IPv6 clients by /64.

### IN-02: Client-address helper duplicated in five places

**File:** `backend/app/routers/downloads.py:32`, `backend/app/routers/search.py:76`, `backend/app/routers/download.py:43`, `backend/app/routers/auth.py:30`, `backend/app/routers/auth.py:60`
**Issue:** `request.client.host if request.client else "unknown"` is written inline three times and as a `client_ip()` helper twice. The IP is the throttle key and the audit field, so the keying rule should live in one function. Not in the fix scope, unchanged (line numbers corrected from the prior review).
**Fix:** Put `client_ip(request)` in one module (for example `app/auth.py`) and import it in every router.

### IN-03: The cancel sweep decides on files from a list read, with no re-read before the delete

**File:** `backend/app/download/pipeline.py:424-432`
**Issue:** `_sweep_once` calls `cancel_deletes_files(row)` on the rows from `torrents_info(tag=...)` and deletes each row without a fresh read. This is the same time-of-check/time-of-use shape that WR-02 closed in `cancel()`. In practice the window is small and the torrents it sees are stopped or at the start of a download (a cancelled job's torrent was added with `stopCondition=MetadataReceived`). The one path where a torrent can be close to done is the sweep started after a failed re-read in `cancel()`, and it retries every `POLL_SECONDS`. I could not build a realistic loss scenario, so this is a consistency note, not a defect.
**Fix:** If you want it closed, re-read per hash before the delete, as `cancel()` does:
```python
fresh = await self._qbit.torrents_info(hashes=str(row["hash"]))
if not fresh:
    continue
await self._discard(str(row["hash"]), None, delete_files=cancel_deletes_files(fresh[0]))
```

---

_Reviewed: 2026-10-23_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
