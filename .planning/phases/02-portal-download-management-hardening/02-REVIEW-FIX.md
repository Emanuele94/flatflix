---
phase: 02-portal-download-management-hardening
fixed_at: 2026-10-22T00:00:00Z
review_path: .planning/phases/02-portal-download-management-hardening/02-REVIEW.md
iteration: 1
findings_in_scope: 4
fixed: 4
skipped: 0
status: all_fixed
---

# Phase 2: Code Review Fix Report

**Fixed at:** 2026-10-22
**Source review:** .planning/phases/02-portal-download-management-hardening/02-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 4 (WR-01..WR-04; IN-01 and IN-02 out of scope)
- Fixed: 4
- Skipped: 0

Each fix has a regression test that was written first and seen to fail before the fix. Fixes were made and committed in the main checkout on `gsd/phase-01-portal-search-start-download` (the caller asked for this; no isolated worktree was created). Only the files of each finding were staged.

## Fixed Issues

### WR-01: "Completed" is judged by `progress` alone

**Files modified:** `backend/app/download/listing.py`, `backend/tests/test_download_listing.py`, `backend/tests/test_downloads_api.py`
**Commit:** 9745bc9
**Status:** fixed: requires human verification (logic change)
**Applied fix:** `cancel_deletes_files` now also requires positive evidence that the torrent never finished: `completion_on` must be unset (missing, empty, 0 or -1). A positive `completion_on` returns False, so `checkingResumeData` with `progress=0` and a past `completion_on` reads as `remove`. A `completion_on` that is not a usable number (garbage, NaN, inf) reads as finished, which keeps the files. New tests cover the verifier's case (also for `checkingDL`, `queuedDL`, `error`; int, float and string values) and the unset-time cases. `CANCEL_TABLE` in `test_downloads_api.py` gave in-progress rows a past `completion_on`, which real qBittorrent never reports for an unfinished torrent, so it now uses -1 unless progress is 1.

### WR-02: Time-of-check/time-of-use gap before `deleteFiles=true`

**Files modified:** `backend/app/download/pipeline.py`, `backend/tests/test_download_cancel.py`
**Commit:** 76c2328
**Status:** fixed: requires human verification (logic change)
**Applied fix:** `cancel()` no longer decides on the first read. After `registry.cancel_for(...)` it re-reads the single torrent (`torrents_info(hashes=...)`) and decides `deletes` on that row; a torrent that is gone gets `deleteFiles=false`. The re-read sits inside the existing `try`, so a failing read starts the sweep (which decides per row) and raises, with no file deletion. Tests: a torrent that finishes while the job is being stopped is deleted with `deleteFiles=false`; a failed re-read deletes nothing and leaves a running sweep. The method docstring was updated.

### WR-03: A failed sweep in `_cancel_job_without_torrent` strands the torrent

**Files modified:** `backend/app/download/pipeline.py`, `backend/tests/test_download_cancel.py`
**Commit:** c64fdc9
**Status:** fixed: requires human verification (error-path behaviour)
**Applied fix:** The background sweep is now started right after `cancel_for`, before the first `_sweep_once`. A `QbitError` from that first lookup is logged (class name only) and the tap still answers 204, because the job is already cancelled and a retry would only get 404. The test makes the first tag lookup fail once, then checks for 204, a cancelled job, and that the late torrent is deleted by the sweep.

### WR-04: `RedactingFilter` skips non-string `record.msg` and short secrets

**Files modified:** `backend/app/audit.py`, `backend/tests/test_audit.py`, `docs/setup.md`
**Commit:** 8e3a5a2
**Applied fix:** (1) A non-string `record.msg` (for example `logger.error(exc)`) now goes through the same handling as an argument: its `str()` is redacted, and the original object is kept when nothing needed redacting. (2) For short secrets, the docs option was taken instead of a new minimum length on `QBITTORRENT_PASS`: a startup failure for an existing 6 or 7 character password (qBittorrent itself allows 6) seemed worse than a documented limit. `docs/setup.md` now says the log filter covers values of 8 or more characters and asks for a qBittorrent password of at least 8 characters. The `MIN_SECRET_LENGTH` comment was extended. Say if you would rather have the hard minimum in `Settings._check_pass`.

## Verification

Run in the main checkout (`/home/emanuele/projects/flatflix`), not in a worktree, after the last commit:

- `uv run --project backend --frozen pytest backend/tests -q`: 655 passed, 7 deselected (integration, opt-in).
- `uv run --project backend --frozen pytest infra/tests -q`: 67 passed.
- `uv run --project backend --frozen ruff check backend`: All checks passed.
- `uv run --project backend --frozen ruff format --check backend`: 54 files already formatted.

Flaky tests seen, not caused by these fixes: in two earlier full-suite runs, `test_rate_limit.py::test_polling_a_job_and_listing_downloads_are_never_limited` and `test_downloads_api.py::test_no_torrent_gives_an_empty_list` failed once each. Both passed when re-run alone and in the final full run. They look timing-sensitive under the full run; I did not investigate further.

---

_Fixed: 2026-10-22_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
