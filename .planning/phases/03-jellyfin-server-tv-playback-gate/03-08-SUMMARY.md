---
phase: 03-jellyfin-server-tv-playback-gate
plan: 08
subsystem: infra
tags: [tv-compatibility, vidaa, jellyfin, real-tv-session, bitrate, mdns, naming-corpus]
status: complete
requires:
  - phase: 03-jellyfin-server-tv-playback-gate
    provides: "03-03..03-07: jellyfin_setup.py, make_compat_clips.py, tv_gate.py, name_scan.py, docs/tv-compatibility.md skeleton, docs/setup.md Jellyfin guide"
provides:
  - "docs/tv-compatibility.md with the measured matrix (A01-A24, S01-S04, K, R rows), opening facts, Address check and Streaming bitrate filled; Verdict still Pending"
  - "jellyfin/name-scan/corpus.json (gitignored): 26 labelled names, all confirmed"
  - "jellyfin/tv-gate/results.json (gitignored): every gating row played on the real TV"
affects: [03-09, phase-05-tv-app]
actuals:
  tokens: 9000
  tasks: 3
  commits: 1
plan_head_before: 8691138205d2949e8ee3ffac4d86c6eb352e44f3
commits: 1
plan_head_after: 8d36652b32d20617d5705910d7436b87ef7c37a0
key-files:
  created: []
  modified:
    - docs/tv-compatibility.md
    - backend/tests/test_tv_gate_contract.py
key-decisions:
  - "Household address stays the IP form: the TV browser answers ERR_NAME_NOT_RESOLVED for the .local name (a phone opens it)"
  - "Streaming limit is 35 Mbps (floor of 70 % of a 50 Mbps measurement); the 50 Mbps comes from speedtest.net in the TV's browser, so it is an internet-link, conservative lower bound, not a TV-to-laptop LAN measurement"
requirements-completed: [COMPAT-01, COMPAT-02, COMPAT-03, INFRA-03, INFRA-04, JFIN-02]
---

# Phase 3 Plan 08: The real-TV session Summary

The Hisense 50A6Q (VIDAA, V0003.09.60A.Q0707) played every gating clip; the measured matrix, the address check and the bitrate record are now in `docs/tv-compatibility.md`, and the candidate verdict is GO.

## Tasks

| Task | Result | Commit |
| --- | --- | --- |
| 1 Tracer: stack, clips, helper, doc pipeline, real names captured | Proven end to end (verification only) | none |
| 2 Real-TV session (checkpoint:human-action) | Done by the user, facts below | none |
| 3 Render matrix, write facts into the doc | Done | 8d36652 |

## Evidence for plan 03-09

```
python3 scripts/tv_gate.py verdict
CANDIDATE GO
1080p content needed video transcoding: never
```

- 1080p group: MKV rows are Remux (AAC) or Audio transcode (AC3, EAC3, DTS: AudioCodecNotSupported); MP4 rows are Direct play except DTS, which is an Audio transcode. No row needed a Video transcode.
- Subtitles S01-S04 played with subtitles on, all "yes". PGS row P01 not tested (no PGS encoder in ffmpeg, D-99, information only).
- Every gating row answered "Picture and sound OK: yes".
- `tv_gate.py validate` prints OK; `grep -c '| not tested |'` over the two gating groups prints 0.

## Session facts recorded

- TV: Hisense 50A6Q, VIDAA, software V0003.09.60A.Q0707; browser version not shown (Dashboard > Devices showed only the helper's client); Jellyfin web client 12.3.0; test date 2026-10-26.
- Address: `.local` opens on a phone, not on the TV (ERR_NAME_NOT_RESOLVED). Household address stays `http://<laptop-ip>/jellyfin`. After laptop and router restart (Docker Desktop auto-started) the TV opened the same address.
- Bitrate: 50 Mbps measured, `bitrate_cap` printed 35, TV client maximum set to 35, dashboard limit matches JELLYFIN_MAX_BITRATE_MBPS in Mbps (RESEARCH A3/A4 confirmed).
- Naming corpus: 26 entries, all confirmed (4 dropped).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Contract tests pinned the untested skeleton**
- **Found during:** Task 3 verify (full pytest)
- **Issue:** `test_the_committed_doc_is_the_untested_matrix` and `test_render_into_the_committed_doc_without_results_reproduces_it_byte_for_byte` required the committed doc to hold the untested matrix, so rendering the measured matrix broke them.
- **Fix:** First test now asserts no `| not tested |` cell in the two gating groups; second asserts that a no-result render leaves everything outside the matrix markers byte for byte and writes the untested skeleton into the matrix.
- **Files modified:** backend/tests/test_tv_gate_contract.py
- **Commit:** 8d36652

### Not done (needs the user)

**2. JELLYFIN_MAX_BITRATE_MBPS in the local env file is still 60, not 35.** The secret-read guard hook blocks any Bash command that touches the env file, and I did not work around it. As a result `jellyfin_setup.py setup --no-scan` was not re-run, and `jellyfin_setup.py check` prints `FAIL bitrate: the limit differs from JELLYFIN_MAX_BITRATE_MBPS for the server` (every other check prints OK). One action fixes it (about 1 minute): set `JELLYFIN_MAX_BITRATE_MBPS=35` in the env file, then run `python3 scripts/jellyfin_setup.py setup --no-scan && python3 scripts/jellyfin_setup.py check`. The doc already states the 35 Mbps limit.

## Issues Encountered

- `tv_gate.py watch` read `yy` when a key was pressed before the prompt appeared, saving no answer. Fixed during the session by replaying (A14/A19 re-answered, S02 replayed with subtitles on). Not fixed in code in this plan; recorded only.
- The speedtest.net figure measures internet speed, not the TV-to-laptop link; the 35 Mbps limit is therefore conservative.
- The restart-test date is not in the user's reply; the doc records 2026-10-26, the date of the session's results. Confirm or correct it in plan 03-09.
- `backend/tests/test_download_cancel.py::test_a_failed_first_sweep_still_leaves_a_sweep_that_deletes_the_torrent` fails (404 vs 204), also when run alone (the known pre-existing timing race; nothing under backend/app changed). The rest of `backend/tests infra/tests` passes: 1454 passed, 1 failed.
- The orchestrator's `root-pin-guard.sh` did not exist in the scratchpad; I checked by hand that the toplevel is the pinned root and the branch is `gsd/phase-03-jellyfin-server-tv-playback-gate` before committing.

## Known Stubs

None. The doc's `**Pending**` verdict line is intentional: plan 03-09 writes the headline (D-89).

## Threat Flags

None. The doc holds only the model line, firmware, dates, versions and yes/no answers; `tv_gate.py validate` found no IPv4, MAC or serial/ESN/device-id value.

## Self-Check: PASSED

- docs/tv-compatibility.md present; commit 8d36652 is an ancestor of HEAD.

Note: JFIN-03 stays pending until the env value is 35 and `check` passes; NAME-01 stays pending until plan 03-09 records the naming decision.
