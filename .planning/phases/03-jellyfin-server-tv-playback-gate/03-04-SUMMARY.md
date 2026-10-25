---
phase: 03-jellyfin-server-tv-playback-gate
plan: 04
subsystem: infra
tags: [jellyfin, ffmpeg, ffprobe, codec-matrix, compat-library, stdlib-scripts, tv-gate]
status: complete

requires:
  - phase: 03-jellyfin-server-tv-playback-gate
    provides: "03-03: scripts/jellyfin_setup.py (ensure_library, library_items, wait_for_scan, CHECK_STEPS), scripts/make_compat_clips.py (fetch_source, ffmpeg, has_encoder), a provisioned Jellyfin"
provides:
  - "scripts/make_compat_clips.py: Row, GROUPS, CATALOGUE (35 rows), clip_path, mux_args, expected_streams, probe, probe_mismatches, na_reason, sidecar_path, TEST_VIDEOS, MANIFEST and the `clips [--only ID ...] [--verify]` subcommand"
  - "jellyfin/scratch/Compat: 24 gating A clips, 4 gating S clips with the S01 sidecar, K01-K03 and R01-R03, all proven with ffprobe (gitignored)"
  - "jellyfin/tv-gate/clips.json manifest: per row id file, n/a reason, note and probed codecs (gitignored)"
  - "scripts/jellyfin_setup.py: admin-only Compat library (homevideos, /scratch/Compat, internet off) in setup and in the libraries check step; compat_gaps and missing_compat_rows"
  - "backend/tests/test_compat_clips_contract.py: 54 pure-function contract tests"
affects: [03-05, 03-06, 03-07, 03-08, phase-05-tv-app]

actuals:
  tokens: 12900
  tasks: 2
  commits: 3
plan_head_before: d6442eb5d903b5316736eebe1cf4d6a53fee98bc
commits: 3
plan_head_after: 94795ea15acf21c5bbda3e4a53de51816c2dde86

tech-stack:
  added: []
  patterns:
    - "Intermediates encoded once (one per video codec, one per audio codec) and muxed by stream copy into 24 rows, so the whole matrix builds in about 5 minutes"
    - "A muxer refusal is data, not a skip: the manifest entry carries `n/a — <reason>` and no half file is left behind"
    - "Every output is written under a .part name and renamed only when complete; the manifest is written to a temp file in the same folder and replaced atomically"
    - "Compat items are matched to files on the row id (first token of the name) because Jellyfin may clean codec words out of a home-video name"

key-files:
  created:
    - backend/tests/test_compat_clips_contract.py
  modified:
    - scripts/make_compat_clips.py
    - scripts/jellyfin_setup.py

key-decisions:
  - "Test videos are held as Source entries in TEST_VIDEOS (keyed by row id) and fetched through one shared _fetch, so Blender and Jellyfin downloads get the same .part, sha256 and rename handling; the Blender-host contract test on SOURCES is untouched"
  - "The Jellyfin test videos carry no audio track: K01-K03 and R03 have audio cell `none`, and the probe check requires no audio stream there; subtitles of download or original rows are not checked for absence because Sintel carries ten tracks"
  - "Row R02 (Big Buck Bunny as downloaded) lists MP3, the first audio track; the AC3 5.1 second track is in the row note"
  - "Each generated row's manifest note records the audio channel layout read from the intermediate (stereo or 5.1), so the DTS channel count is on record"

requirements-completed: [COMPAT-01, COMPAT-02, COMPAT-03]

coverage:
  - id: D1
    description: "The full codec matrix (24 gating A rows, 4 gating S rows, P01 without a file, K01-K03, R01-R03) exists in jellyfin/scratch/Compat and every file's container and codecs are proven with ffprobe"
    requirement: "COMPAT-01"
    verification:
      - kind: other
        ref: "python3 scripts/make_compat_clips.py clips --verify: 35 OK lines, exit 0"
        status: pass
      - kind: unit
        ref: "backend/tests/test_compat_clips_contract.py#test_the_av_group_is_a01_to_a24_in_container_video_audio_order"
        status: pass
    human_judgment: false
  - id: D2
    description: "Audio rows cover AAC, AC3, EAC3 and DTS on every container and video codec (media half of COMPAT-02)"
    requirement: "COMPAT-02"
    verification:
      - kind: other
        ref: "clips --verify OK A01-A24; manifest probed.audio per row"
        status: pass
    human_judgment: true
    rationale: "Whether the TV plays each row, and by which method, is measured in plans 03-06 and 03-08, not here"
  - id: D3
    description: "Subtitle rows S01-S04 (external SRT sidecar, embedded SRT, embedded ASS, MP4 text) exist and are verified; PGS is recorded as a note without a file (media half of COMPAT-03)"
    requirement: "COMPAT-03"
    verification:
      - kind: other
        ref: "clips --verify OK S01-S04 and OK P01 (no file: no PGS encoder in ffmpeg (D-99))"
        status: pass
      - kind: unit
        ref: "backend/tests/test_compat_clips_contract.py#test_the_pgs_row_has_no_file_and_the_decided_note"
        status: pass
    human_judgment: true
    rationale: "Subtitle rendering on the TV is a human observation in plan 03-08"
  - id: D4
    description: "Compat is an admin-only homevideos library with internet metadata off; the household's EnabledFolders stay exactly Movies and TV Series; check still prints 11 OK lines and proves every clip is listed as a Compat item"
    requirement: "COMPAT-01"
    verification:
      - kind: other
        ref: "jellyfin_setup.py check: 11 OK lines incl. household-policy and libraries, after setup rescanned the 34 clips"
        status: pass
      - kind: unit
        ref: "backend/tests/test_compat_clips_contract.py#test_setup_gives_the_household_only_movies_and_tv_series"
        status: pass
    human_judgment: false
  - id: D5
    description: "Every downloaded test video matches the sha256 published on repo.jellyfin.org, is pinned in TEST_VIDEOS, and nothing generated or downloaded is committed"
    requirement: "COMPAT-02"
    verification:
      - kind: unit
        ref: "backend/tests/test_compat_clips_contract.py#test_every_test_video_is_pinned_from_the_jellyfin_repository"
        status: pass
      - kind: unit
        ref: "backend/tests/test_compat_clips_contract.py#test_nothing_the_script_writes_is_inside_the_repository_tree"
        status: pass
    human_judgment: false

duration: 17min
completed: 2026-10-25
---

# Phase 3 Plan 04: Compat codec matrix and admin-only Compat library Summary

`python3 scripts/make_compat_clips.py clips` now builds the whole D-84 codec matrix (24 gating audio/video rows, 4 gating subtitle rows, the PGS note, three 4K rows and three real-release rows) in `jellyfin/scratch/Compat`, `clips --verify` proves all 35 rows with ffprobe, and an admin-only Compat library lists every clip under its row id while the household still sees only Movies and TV Series.

**Started:** 2026-10-25T21:20:27Z | **Completed:** 2026-10-25T21:37Z | **Duration:** ~17 min (the full `clips` run took 4 min 52 s) | **Tasks:** 2 | **Files:** 3 (1 new, 2 modified)

## Accomplishments

- `scripts/make_compat_clips.py clips [--only ID ...] [--verify]`: A01-A24 by stream copy from one H.264 / HEVC 8-bit / HEVC 10-bit video intermediate (Big Buck Bunny, 60 s from second 60) and one AAC / AC3 / EAC3 / DTS audio intermediate (Sintel, same minute, tagged `eng`); S01-S04 from a 12-cue English SRT and ASS; K01-K03 and R03 from pinned Jellyfin test videos; R01 and R02 hardlinked from the Blender sources.
- No row was refused by a muxer: even the MP4 DTS rows (A16, A20, A24, with `-strict -2`) muxed and probe as `dts`, and DTS encoded as 5.1 so the stereo fallback was never used. The `n/a` path is covered by a test and is unused live.
- `jellyfin_setup.py setup` now creates `Compat` (homevideos, `/scratch/Compat`, internet off) and never adds it to the household's folders; the `libraries` check step also demands Compat with internet metadata off and that every `.mkv` and `.mp4` on disk is a Compat item (a FAIL line names row ids only; proved with a fake `Z99` file name: `Compat items missing for Z99`). `CHECK_STEPS` is still the same 11 steps.
- 54 contract tests; full suite `uv run --project backend --frozen pytest backend/tests infra/tests -q` gives `1258 passed, 19 deselected`.
- Tracer feedback gate: the Task 1 verify chain was re-run end to end (pytest, `clips --only A01`, `clips --verify --only A01`, setup, check with 11 OK lines) and passed, so expansion went ahead.

## Task Commits

1. **Task 1 (tracer): clip A01 proven with ffprobe and listed in the admin-only Compat library** - `48b65ea` (feat)
2. **Task 2 RED: failing tests for the full matrix, n/a rows, test videos and manifest** - `a2449f0` (test)
3. **Task 2 GREEN: full matrix generated and proven** - `94795ea` (feat)

## RED and GREEN evidence

**Task 1 RED** (before any new symbol existed): `32 failed, 2 passed in 0.74s` on `backend/tests/test_compat_clips_contract.py` (the two passing tests were the library-option and check-step cases already true after plan 03-03). First GREEN: `101 passed in 0.23s` over the compat and the plan 03-03 contract files. Tracer RED and GREEN share one commit, as in plans 03-02 and 03-03.

**Task 2 RED** (commit `a2449f0`): `15 failed, 39 passed in 0.56s`; every failure is an `AttributeError` or `TypeError` on the planned symbols (`na_reason`, `sidecar_path`, `TEST_VIDEOS`, `srt_text`, `ass_text`, `mux_args(..., subtitle=)`, the DTS `-strict` flag, `build_row`). The manifest merge, the failed-write and the git-ignore tests passed at RED because Task 1 already provided the atomic manifest. `gsd_run check tdd-red-evidence` was not run: pytest text output is not a supported report format and the plan is `type: execute`.

**Task 2 GREEN** (commit `94795ea`): `54 passed in 0.10s`; ruff clean on `backend scripts/make_compat_clips.py scripts/jellyfin_setup.py`; `py_compile` clean.

## Live output (no secret in it)

`clips --only A01` then `clips --verify --only A01` (Task 1):

```
clip A01 A01 MKV H264 AAC.mkv 60.0 MB
OK A01
```

`clips --verify` after the full `clips` run (Task 2, exit 0):

```
OK A01 ... OK A24   (24 lines, every A row)
OK S01
OK S02
OK S03
OK S04
OK P01 (no file: no PGS encoder in ffmpeg (D-99))
OK K01
OK K02
OK K03
OK R01
OK R02
OK R03
```

`setup` (second run, the scan took the 34 clips; about 50 s):

```
OK wizard (unchanged)
OK admin-login
OK server-config (unchanged)
OK household (unchanged)
OK library Movies (unchanged)
OK library TV Series (unchanged)
OK library Compat (unchanged)
OK household-policy (unchanged)
OK household-prefs (unchanged)
OK admin-hidden (unchanged)
OK scan
```

The first Task 1 `setup` printed `OK library Compat (created)`. `check` (11 OK lines, with every clip listed in Compat):

```
OK wizard-complete
OK admin-login
OK public-users
OK admin-hidden
OK household-policy
OK household-prefs
OK libraries
OK bitrate
OK movies-metadata
OK series-metadata
OK metadata-local
```

## The matrix as built

- n/a rows: none. P01 has no file and the note `no PGS encoder in ffmpeg (D-99)`.
- Files in `jellyfin/scratch/Compat`: 24 A, 4 S plus `S01 MKV H264 AAC SRTEXT.en.srt`, K01 `MP4 HDR10`, K02 `MP4 HEVC10`, K03 `MP4 H264`, R01 `MKV H264 AC3 SRT` (Sintel as downloaded), R02 `MP4 H264 MP3` (Big Buck Bunny as downloaded), R03 `MP4 HEVC10`.
- Generated clips are about 60 MB each (8 Mb/s video plus audio); the K files are 147 MB each, R01 is 1180 MB; all hardlinks for the downloaded and original rows.
- Chosen Jellyfin test videos (lowest 4K bitrate listed is 40M; no audio track in any of them) and their pinned sha256, each equal to the `.sha256sum` published next to the file and to the file's recomputed hash:

| Row | File on repo.jellyfin.org/test-videos | sha256 |
|-----|----------------------------------------|--------|
| K01 | `HDR/HDR10/HEVC/Test Jellyfin 4K HEVC HDR10 40M.mp4` (HEVC Main 10, smpte2084) | `da108da499153ae4816b6cd50296a6dc56996ae3d30a08c7a14a1108b25a4221` |
| K02 | `SDR/HEVC 10bit/Test Jellyfin 4K HEVC 10bit 40M.mp4` | `738a7fb8fd951421791286a9609f03b963acd3d424420b3e58edac50ec8cf31c` |
| K03 | `SDR/AVC/Test Jellyfin 4K AVC 40M.mp4` | `247511299989ae9d194c09012f10740f7d074d0fd7768073f2b8f0424c2060df` |
| R03 | `SDR/HEVC 10bit/Test Jellyfin 1080p HEVC 10bit 3M.mp4` | `b4dc866907df217157c53288db95ff22e002ec3e24cd818de6616ff06a1d6cae` |

## Acceptance criteria

All PASS. Task 1: `grep -c CATALOGUE` 5 (needs 2), `grep -c homevideos` 1, `def missing_compat_rows` 1, `ls Compat | grep -c '^A01 '` 1, `git status --porcelain -- jellyfin` empty. Task 2: A rows on disk 24 (24 minus 0 n/a), S01-S04 clips 4 and the S01 sidecar 1, `TEST_VIDEOS` 3 (needs 2), `repo.jellyfin.org` 2 (needs 1), `git status --porcelain -- jellyfin` empty. Plan verification: full pytest `1258 passed, 19 deselected`; `clips --verify` all OK; `check` 11 OK lines.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `ffmpeg()` could not report why a muxer refused**
- **Found during:** Task 1 design (na_reason needs the muxer's stderr)
- **Issue:** the plan 03-03 `ffmpeg(*args, timeout=1800)` let stderr go to the terminal, so a `CalledProcessError` carried no reason.
- **Fix:** one new keyword with a default, `capture_stderr=False`; the signature the other callers use is unchanged.
- **Files modified:** scripts/make_compat_clips.py
- **Commit:** 48b65ea

**2. [Rule 2 - Missing critical] Probe checks for facts the plan only implied**
- **Found during:** Task 1 (`probe_mismatches`)
- **Issue:** the plan names container, codec, pix_fmt and subtitle codec; an HDR10 row that is really SDR, or a 1080p row that is not 1920 wide, would pass unnoticed, and a generated "no subtitles" row with a stray track too.
- **Fix:** `probe_mismatches` also checks width (1920 or 3840), `color_transfer` smpte2084 for HDR10 rows, and absence of subtitle streams on generated rows without subtitles; a missing audio stream is a mismatch.
- **Files modified:** scripts/make_compat_clips.py, backend/tests/test_compat_clips_contract.py
- **Commit:** 48b65ea

**3. [Rule 2 - Missing critical] No half file for a scan to find after a refusal**
- **Found during:** Task 2
- **Issue:** a muxer that fails midway leaves a partial output; Jellyfin's realtime monitor could list it.
- **Fix:** muxing writes `<name>.part`, which is deleted on failure and renamed only when complete; a test asserts the Compat folder is empty after a refusal.
- **Files modified:** scripts/make_compat_clips.py, backend/tests/test_compat_clips_contract.py
- **Commit:** 94795ea

### Plan assumptions that resolved differently

- The plan expected the Jellyfin test videos to give "container and audio filled from ffprobe at generation". They have no audio track at all, so K01-K03 and R03 carry audio `none` in the catalogue (a static, hash-pinned fact) and `clips --verify` requires no audio stream for them. Plan 03-06 should print `none` there, not `not tested`.
- Flagged assumption "MP4 DTS may read n/a" did not materialise: ffmpeg 6.1.1 muxes DTS into MP4 with `-strict -2`, and ffprobe reads `dts` back.

**Total deviations:** 3 auto-fixed (1 blocking, 2 missing critical). **Impact:** none on scope; all strengthen the proof or avoid partial files.

## Issues Encountered

- DTS in MP4 is something a TV browser may well refuse (the muxer accepts it, the player may not). That is exactly what the gate measures in plan 03-08; the manifest records nothing about it beyond the probe.
- The Compat library is scanned only by `setup` (or Jellyfin's realtime monitor). After regenerating clips, run `python3 scripts/jellyfin_setup.py setup` before `check`, or `check` reports the new row ids as missing.
- `ruff check scripts` over the whole folder reports two UP031 findings in `scripts/qbit_login_check.py`. That file is outside this plan and was left alone; the plan's own ruff command is clean.

## Known Stubs

None. P01 has no file on purpose (D-99, the PGS row is `not tested`); the K and R rows are real files, not placeholders.

## Threat Flags

None. New surface (Jellyfin test-video downloads, the Compat library) is in the plan's threat model. T-03-15 mitigated: only repo.jellyfin.org and download.blender.org, each file's sha256 pinned in `TEST_VIDEOS` and checked on every download, host and hash shape asserted by a contract test. T-03-32 mitigated: Compat is not in `LIBRARIES`, the setup test asserts `household_changes` receives exactly the Movies and TV Series ids, `check household-policy` still passes live, and `compat_gaps` requires internet metadata off. T-03-SC: no package added.

## Authentication Gates

None.

## Next Phase Readiness

`CATALOGUE`, `GROUPS`, `clip_path`, `MANIFEST` and `jellyfin_setup.py`'s function signatures are exactly the shapes plan 03-06 (the measuring helper) and plan 03-05 (the corpus libraries) call. Row cells use the UI-SPEC words; for K and R rows the manifest `probed` block is the ffprobe truth. Ready for plan 03-05.

## Self-Check: PASSED

`scripts/make_compat_clips.py`, `scripts/jellyfin_setup.py`, `backend/tests/test_compat_clips_contract.py` and `jellyfin/tv-gate/clips.json` exist; commits `48b65ea`, `a2449f0` and `94795ea` are ancestors of HEAD; `git status --porcelain -- jellyfin` is empty; RED (`test`) and GREEN (`feat`) commits for `03-04` Task 2 are both present.
