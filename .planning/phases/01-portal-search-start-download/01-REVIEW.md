---
phase: 01-portal-search-start-download
reviewed: 2026-10-22T00:00:00Z
depth: standard
files_reviewed: 15
files_reviewed_list:
  - backend/app/download/allowlist.py
  - backend/app/download/jobs.py
  - backend/app/download/pipeline.py
  - backend/app/qbit/client.py
  - backend/tests/fakeqbit.py
  - backend/tests/integration/test_real_qbit.py
  - backend/tests/test_allowlist.py
  - backend/tests/test_download_pipeline.py
  - frontend/src/App.jsx
  - frontend/src/ResultRow.jsx
  - frontend/src/Search.jsx
  - frontend/src/__tests__/App.test.jsx
  - frontend/src/__tests__/ResultRow.test.jsx
  - frontend/src/__tests__/Search.test.jsx
  - frontend/src/messages.js
findings:
  critical: 0
  warning: 3
  info: 3
  total: 6
status: issues_found
---

# Phase 1: Code Review Report (incremental, gap plans 01-14, 01-15, 01-16)

**Reviewed:** 2026-10-22
**Depth:** standard
**Files Reviewed:** 15
**Status:** issues_found

## Summary

Scope: the diff since 949a0cf. That covers the stop-condition add on every route (01-14), the sessionStorage reload persistence (01-15) and the `unsupported` status for non-allowlisted video formats (01-16). Ruff passes on `backend/app` and `backend/tests`.

The changes are mostly sound. I traced these and found no defects:
- The `stopped` parameter was removed cleanly: no caller or test still passes it.
- `UNSUPPORTED` is correctly absent from `ACTIVE_STATES`, so a rejected job is not deduplicated.
- The router returns `job.state.value` unchanged, so the new status reaches the frontend with no further mapping.
- The generation counter stops a late write from bringing back a cleared search.
- Saved data is treated as untrusted, and no credentials, URLs or hashes are persisted.

No blockers. The three warnings are:
- A mixed-format torrent can start with only a small extra.
- The core safety claim (no payload before the allowlist) is proven only by an opt-in test.
- A stale saved search can fail on every reload.

## Warnings

### WR-01: A torrent whose main video is outside the allowlist is "Started" if it holds any small allowed video

**File:** `backend/app/download/allowlist.py:115-126`
**Issue:** `largest` and the 10% sample ratio are computed over allowed videos only. The new `OTHER_VIDEO_EXTENSIONS` branch is reached only when `main_videos` is empty. A torrent with a 20 GB `Movie.m2ts` (or `.mov`/`.webm`) plus a 100 MB `Trailer.mp4` therefore gets `accept=True`. The pipeline keeps and downloads only the trailer and reports `started`, so the user sees "Started ✓" for a download that is not the film. The new `test_a_mixed_mkv_and_webm_torrent_keeps_only_the_mkv` only covers equal sizes and does not catch this.
**Fix:** Compute `largest` over `VIDEO_EXTENSIONS | OTHER_VIDEO_EXTENSIONS` for the sample ratio. When the largest non-sample video is not an allowed format and no allowed video reaches 10% of it, reject with `video_format`.
```python
all_videos = [f for f in files if final_extension(f.name) in VIDEO_EXTENSIONS | OTHER_VIDEO_EXTENSIONS]
largest = max((f.size for f in all_videos if not is_sample_name(f.name)), default=0)
main_videos = {f.index for f in videos if not is_sample_name(f.name) and f.size * 10 >= largest}
```
Add a test with a large `.m2ts` and a small `.mp4`.

### WR-02: The "no payload before the allowlist" guarantee is proven only by the fake and an opt-in test

**File:** `backend/app/download/pipeline.py:183-188`, `backend/app/qbit/client.py:275-297`, `backend/tests/fakeqbit.py:~340-352`
**Issue:** D-23 now rests on `stopCondition=MetadataReceived` for every route. For a torrent whose metadata exists at add, that depends on a reading of qBittorrent 5.2.4 source (`sessionimpl.cpp:2794-2801`), cited by line number. The `torrent.downloaded == 0` assertions in `test_no_route_downloads_a_payload_byte_before_the_allowlist` and the related tests are tautological: the fake sets `downloaded = 1` only when it models the torrent as running, and the fake was written to implement that assumption. The real-engine tests need `QBIT_TEST_URL` and `-m integration`, and the plugin test skips when no Blender result is found. A qBittorrent image bump can silently break the guarantee. For the magnet route there is also a short window between the metadata arriving and the engine applying the stop. `_wait_for_files` returns as soon as the file list is non-empty, and nothing checks `downloaded` afterwards.
**Fix:** Add a cheap runtime check in `_process`. After the priorities are verified and before `start`, read `torrents_info(hashes=...)` and, if `downloaded > 0` or the state is a running one, handle it deliberately. Either delete as `failed` (strict) or at least log a warning. Pin the qBittorrent image tag in a test that asserts the integration guard's version. Drop the line-number citations in comments, because they will rot.

### WR-03: A restored search that the backend no longer knows keeps a stale saved record and an error on every reload

**File:** `frontend/src/Search.jsx:244-247`, `frontend/src/Search.jsx:374-376`
**Issue:** Searches live in backend memory. After a backend restart or a search TTL expiry, restoring an unfinished record (`done: false`) calls `poll`, which gets 404 and goes to `fail()`. That sets `searching=false` and shows the generic "search failed" message. The saved record is never cleared or marked done, so it stays in storage. Every reload shows the saved rows plus the error. Tapping Download on those rows gets 410 and ends in `expired`. This is harmless but confusing for non-technical users. Restoring a `done: true` record whose search expired is fine, because it makes no search call.
**Fix:** In the poll `catch`, when the error is `ApiError` with status 404 and the search is a restored one, mark the saved record `done: true` (keep the rows) and call `persist()`. Alternatively show `MSG.searchExpired` and clear the record.
```js
} catch (err) {
  if (err instanceof ApiError && err.status === 404 && saved.current !== null) {
    saved.current = { ...saved.current, done: true };
    persist();
  }
  fail(run, err);
}
```

## Info

### IN-01: Saved `result_id` is validated by a regex that coerces non-strings

**File:** `frontend/src/Search.jsx:70` (`validRow`)
**Issue:** `ID.test(r.result_id)` coerces its argument to a string, so an array such as `['0123456789abcdef']` passes. `pickRow` then drops it as non-primitive and the row is rendered with an undefined `result_id`, so its key and its job lookup are `undefined`. Only reachable by editing one's own sessionStorage, so the impact is negligible.
**Fix:** Add `typeof r.result_id === 'string' &&` to `validRow`.

### IN-02: `.ts` in `OTHER_VIDEO_EXTENSIONS` also matches non-video files

**File:** `backend/app/download/allowlist.py:19-34`
**Issue:** `.ts` is also TypeScript and Qt translation source. A torrent holding such files and no video is reported as "This video format isn't supported" instead of "This file doesn't contain a video". It is rejected either way, so this is wording only. The reverse is also true: `.vob` and `.mpg` in a DVD rip get the unsupported wording, which is fine.
**Fix:** Optional. Drop `.ts`, or treat it as video only when its size is above a floor (for example 50 MB).

### IN-03: Test name is over the 100-column limit

**File:** `backend/tests/integration/test_real_qbit.py:220`
**Issue:** `test_a_metadata_complete_torrent_added_with_the_stop_condition_holds_still_until_the_pipeline_starts_it` is 114 columns. Ruff does not flag it, because E501 is not selected, but it breaks the project's declared `line-length = 100`.
**Fix:** Shorten it, for example `test_a_metadata_complete_torrent_holds_still_under_the_stop_condition`.

---

_Reviewed: 2026-10-22_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
