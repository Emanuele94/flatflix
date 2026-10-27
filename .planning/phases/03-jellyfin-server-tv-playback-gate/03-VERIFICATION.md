---
phase: 03-jellyfin-server-tv-playback-gate
verified: 2026-10-27T12:00:00Z
status: passed
score: 6/6 must-haves verified
covered_files:
  - .env.example
  - .gitignore
  - .planning/phases/03-jellyfin-server-tv-playback-gate/03-01-PLAN.md
  - .planning/phases/03-jellyfin-server-tv-playback-gate/03-01-SUMMARY.md
  - .planning/phases/03-jellyfin-server-tv-playback-gate/03-02-PLAN.md
  - .planning/phases/03-jellyfin-server-tv-playback-gate/03-02-SUMMARY.md
  - .planning/phases/03-jellyfin-server-tv-playback-gate/03-03-PLAN.md
  - .planning/phases/03-jellyfin-server-tv-playback-gate/03-03-SUMMARY.md
  - .planning/phases/03-jellyfin-server-tv-playback-gate/03-04-PLAN.md
  - .planning/phases/03-jellyfin-server-tv-playback-gate/03-04-SUMMARY.md
  - .planning/phases/03-jellyfin-server-tv-playback-gate/03-05-PLAN.md
  - .planning/phases/03-jellyfin-server-tv-playback-gate/03-05-SUMMARY.md
  - .planning/phases/03-jellyfin-server-tv-playback-gate/03-06-PLAN.md
  - .planning/phases/03-jellyfin-server-tv-playback-gate/03-06-SUMMARY.md
  - .planning/phases/03-jellyfin-server-tv-playback-gate/03-07-PLAN.md
  - .planning/phases/03-jellyfin-server-tv-playback-gate/03-07-SUMMARY.md
  - .planning/phases/03-jellyfin-server-tv-playback-gate/03-08-PLAN.md
  - .planning/phases/03-jellyfin-server-tv-playback-gate/03-08-SUMMARY.md
  - .planning/phases/03-jellyfin-server-tv-playback-gate/03-09-PLAN.md
  - .planning/phases/03-jellyfin-server-tv-playback-gate/03-09-SUMMARY.md
  - backend/tests/test_compat_clips_contract.py
  - backend/tests/test_config.py
  - backend/tests/test_jellyfin_setup_contract.py
  - backend/tests/test_name_scan_contract.py
  - backend/tests/test_tv_gate_contract.py
  - docker-compose.yml
  - docs/naming-scan.md
  - docs/ports-and-media.md
  - docs/setup.md
  - docs/tv-compatibility.md
  - infra/tests/test_caddyfile.py
  - infra/tests/test_compose_invariants.py
  - infra/tests/test_docs_contract.py
  - infra/tests/test_repo_hygiene.py
  - scripts/dev_env.py
  - scripts/init-host-dirs.sh
  - scripts/jellyfin_setup.py
  - scripts/make_compat_clips.py
  - scripts/name_scan.py
  - scripts/tv_gate.py
  - web/Caddyfile
covered_digest: "v3:sha256:c013ed9a72e96c221848e0194ad66cee03011e92ed8058c597744c90e9f991b1"
behavior_unverified: 0
overrides_applied: 0
---

# Phase 3: Jellyfin Server & TV Playback Gate Verification Report

**Phase Goal:** Jellyfin runs on the laptop behind Caddy at a stable address, the real TV's playback behaviour is measured (go/no-go for "no video transcoding"), and the file-naming ownership decision is made on evidence, before the portal and Jellyfin are integrated.
**Verified:** 2026-10-27
**Status:** passed
**Re-verification:** Yes, after the hygiene gap was closed (the earlier run reported one gap, a LAN-address test failing on a version string quoted in the code review report)

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | SC1: TV opens one laptop address (Caddy) and uses the Jellyfin web UI; a correctly named sample library in a scratch folder shows posters, plots, seasons, episodes | VERIFIED | Live: `GET /jellyfin` returns 308 to `/jellyfin/`, `/jellyfin/health` returns 200. `python3 scripts/jellyfin_setup.py check` prints 11 OK, including `movies-metadata`, `series-metadata` and `metadata-local`. `jellyfin/scratch/{Movies,TV,Compat,Raw}` exist and are mounted read-only. TV browsing is human-attested (03-08-SUMMARY, `docs/tv-compatibility.md` facts). |
| 2 | SC2: Compatibility matrix from the real TV: H.264/HEVC (incl. 10-bit), AAC/AC3/EAC3/DTS, SRT and embedded subs, each with a method | VERIFIED | `docs/tv-compatibility.md` holds A01-A24 and S01-S04 with a Method (Direct play, Remux or Audio transcode), the verbatim TranscodeReasons and "Picture and sound OK = yes" on every gating row. Zero `not tested` cells in the gating groups. `tv_gate.py validate` prints OK. `make_compat_clips.py clips --verify` proves the 35 clips with ffprobe. PGS (P01) is recorded as not tested, information only (D-99). |
| 3 | SC3: Go/no-go verdict recorded from the admin dashboard; 1080p never needs video transcoding, or a mitigation is chosen | VERIFIED | The Verdict section reads `**GO**`, "1080p content needed video transcoding: never", "Jellyfin version tested: 12.3.0". `tv_gate.py verdict` prints `CANDIDATE GO` live. No matrix row says Video transcode. Recorded in PROJECT.md as "Decided (user, D-87)". The user chose GO. |
| 4 | SC4: After a laptop/router restart the TV reaches the same address; Caddy, Jellyfin and the portal run on the documented port map with no collisions | VERIFIED | Address check records "Same address after laptop and router restart: yes (2026-10-27)" (human-attested). Live `docker ps` shows only web publishes a port (80); jellyfin shows 8096/tcp unpublished; `curl <loopback>:8096` fails (000). `docs/setup.md` has "Keep the laptop on the same address" (DHCP reservation, INFRA-04) and the `.local` ladder. `docs/ports-and-media.md` matches the compose file. |
| 5 | SC5: Naming decision recorded in PROJECT.md Key Decisions, backed by a scan test on raw torrent-style names | VERIFIED | PROJECT.md row: "Decided (Phase 3, NAME-01): portal rename step after the safety check, 20/26 identified, 0 wrong title(s), bar D-92 not met", linking `docs/naming-scan.md`. That doc holds the real-corpus counts (20/6/0 of 26), failure classes (all flat episode files), a full synthetic-sample table and a Decision section. No real torrent name appears in tracked files; the real corpus and results are gitignored. |
| 6 | Phase repo invariants hold (infra + backend contract tests green, no LAN address tracked) | VERIFIED | Re-run after the fix: `infra/tests` gives 185 passed; the four Phase 3 backend contract files plus test_config.py give 330 passed. The code review report no longer holds a dotted-quad. |

**Score:** 6/6 truths verified (0 present but behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `docker-compose.yml` jellyfin service | Pinned image, read_only, cap_drop ALL, no-new-privileges, tmpfs, config/cache binds, read-only scratch bind, healthcheck, own network, no `ports` | VERIFIED | All present (lines 129-166). `jellyfin: {}` network on line 199. `docker-compose.admin.yml` has no 8096. |
| `web/Caddyfile` `/jellyfin` route | Own CSP with wasm-unsafe-eval, portal CSP unchanged | VERIFIED | Live: exactly one CSP header on `/jellyfin/web/index.html` (with `'wasm-unsafe-eval'`). `/` carries the strict portal CSP with no `unsafe-inline`. |
| `scripts/jellyfin_setup.py` | Idempotent provisioning plus `check` | VERIFIED | Live `check` prints 11 OK, exit 0. The bitrate mismatch noted in 03-08 is resolved. |
| `scripts/make_compat_clips.py` | Codec matrix with ffprobe verify | VERIFIED | `clips --verify` is OK for every row (A, S, K and R). |
| `scripts/tv_gate.py` | Sessions + ffmpeg log to Method; validate and verdict | VERIFIED | `validate` OK, `verdict` CANDIDATE GO. |
| `scripts/name_scan.py` + `docs/naming-scan.md` | Scan harness plus real-corpus counts | VERIFIED | CLI present; doc holds counts and Decision; privacy tests pass. |
| `scripts/dev_env.py`, `.env.example` | Jellyfin keys, TV-typable password, placeholders | VERIFIED | Config and hygiene tests pass; `.env` not read. |
| `docs/setup.md` "Jellyfin and the TV" | First start, household, bitrate, same address, .local, TV test, naming scan, reset | VERIFIED | All subsections present; the docs contract test passes. |
| `docs/tv-compatibility.md` | Matrix, address check, bitrate, verdict | VERIFIED | See Truths 2-4. |
| `.planning/PROJECT.md` Phase 3 rows | Naming, verdict, household, port map | VERIFIED | Rows present with evidence links. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| Caddy `/jellyfin*` | jellyfin:8096 | reverse proxy on network `jellyfin` | WIRED | Live 308/200 responses through Caddy. |
| `tv-gate/results.json` (gitignored) | `docs/tv-compatibility.md` | `tv_gate.py render` | WIRED | Matrix markers present; validate OK. |
| PROJECT.md naming row | `docs/naming-scan.md` | link plus counts | WIRED | Counts match (20/26, 76 %). |
| `.env` JELLYFIN_MAX_BITRATE_MBPS | Jellyfin server and household limit | `jellyfin_setup.py setup` | WIRED | `check` `bitrate` is OK. |
| `scripts/jellyfin_setup.py` | Compat library (admin-only) | `homevideos` library | WIRED | `check` `libraries` is OK; 35 files listed. |

### Data-Flow Trace (Level 4)

Not applicable. The phase has no UI that renders dynamic data (UI-SPEC: no portal or frontend change). `git diff main...HEAD -- backend/app frontend` is empty. The matrix is rendered from the real Sessions/ffmpeg-log results.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Jellyfin reachable only through Caddy | `curl -sI http://<loopback>/jellyfin`; `curl <loopback>:8096/health` | 308 /jellyfin/; 8096 refused | PASS |
| Per-route CSP | `curl -sI` on `/` and `/jellyfin/web/index.html` | Portal CSP strict; Jellyfin CSP carries wasm-unsafe-eval, one header | PASS |
| Provisioning state | `jellyfin_setup.py check` | 11 OK, exit 0 | PASS |
| Matrix and verdict | `tv_gate.py validate`, `verdict` | OK; CANDIDATE GO | PASS |
| Clips match catalogue | `make_compat_clips.py clips --verify` | OK for all rows | PASS |
| Phase test files | `pytest infra/tests` plus the four Phase 3 backend contract files and test_config.py | 185 passed; 330 passed | PASS |
| Gitignore | `git check-ignore jellyfin/ results.json corpus.json` | all three ignored | PASS |

Not run: stopping the jellyfin container to check the 502 body (it would mutate the live stack). The infra Caddyfile tests cover it and pass. The full backend suite was not re-run; the orchestrator's gate figures (1460 passed, 271 frontend) are taken from the orchestrator's report, not re-measured. The known flaky `test_download_cancel` test is outside Phase 3.

### Probe Execution

No `probe-*.sh` is declared by the phase. SKIPPED.

### Requirements Coverage

All 10 phase IDs are claimed by at least one PLAN and match the REQUIREMENTS.md traceability table (Phase 3). No orphaned requirements.

| Requirement | Source Plan(s) | Description | Status | Evidence |
|-------------|----------------|-------------|--------|----------|
| JFIN-01 | 03-01, 03-02, 03-03, 03-07 | Jellyfin in Docker with persistent config/cache, household user, default languages | SATISFIED | compose service, `check` OK (household-policy, household-prefs, public-users) |
| JFIN-02 | 03-03, 03-08 | Sample content scanned with posters, plots, cast, seasons, episodes stored locally | SATISFIED | `check`: movies-metadata, series-metadata, metadata-local |
| JFIN-03 | 03-02, 03-03, 03-09 | Max streaming bitrate configured | SATISFIED | `check` bitrate OK; 35 Mbps recorded. Its source is an internet speedtest, not a LAN measurement: a conservative lower bound, disclosed in the doc. |
| COMPAT-01 | 03-04, 03-06, 03-08 | H.264/HEVC incl. 10-bit tested on real TV | SATISFIED | A01-A24 rows (human session, matrix rendered from server evidence) |
| COMPAT-02 | 03-04, 03-06, 03-08 | AAC/AC3/EAC3/DTS tested | SATISFIED | Same rows; DTS needs an Audio transcode, recorded |
| COMPAT-03 | 03-04, 03-06, 03-08 | SRT and embedded subtitles tested | SATISFIED | S01-S04 yes; PGS not testable (D-99) |
| COMPAT-04 | 03-09 | Dashboard checked, go/no-go verdict recorded | SATISFIED | Verdict GO |
| INFRA-03 | 03-01, 03-07, 03-08 | Caddy and Jellyfin on the port map, shared network, TV reaches Jellyfin only via Caddy | SATISFIED | Live port check; compose and infra tests |
| INFRA-04 | 03-07, 03-08, 03-09 | DHCP reservation keeps the address stable | SATISFIED | Documented in setup.md; restart test recorded (human-attested) |
| NAME-01 | 03-05, 03-08, 03-09 | Naming owner decided on scan-test evidence | SATISFIED | PROJECT.md plus docs/naming-scan.md |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `docs/tv-compatibility.md` | S01/S03 rows | Method is Remux but Reason lists `AudioCodecNotSupported` for AAC audio | Info | Reason is copied verbatim from Jellyfin; may deserve a note for Phase 5 |
| (03-REVIEW.md) | - | 8 warnings and 7 info, disposition all `open` | Warning (advisory) | See below |

No TBD, FIXME or XXX debt markers were found in the phase's code files; I did not grep every file exhaustively, and the code review does not report any.

Code review dispositions (03-REVIEW-DISPOSITION.md: 15 open). None block the goal. Worth a decision before Phase 5 or 6:
- WR-07: `jellyfin/config` (database, password hashes, tokens) is created group-writable and world-readable.
- WR-08: Jellyfin is served from the portal's origin with `script-src 'unsafe-inline'`. This was a decision in plan 03-01 (own route CSP); the portal's CSP is unchanged.
- WR-06 and WR-04: they affect `name_scan.py`, which Phase 4 may reuse.
- WR-01 to WR-03: `tv_gate.py watch` robustness. The TV session is done.

### Human Verification Required

None outstanding. The real-TV session, the restart test and the GO choice were done and attested by the user, and recorded in `docs/tv-compatibility.md` and 03-08-SUMMARY.md. I cannot re-observe the TV from the codebase. These rows are accepted as human-attested evidence, backed by server-side evidence (Sessions and ffmpeg logs) in the rendered matrix.

### Gaps Summary

No gaps. The phase goal is achieved on all five ROADMAP success criteria and all 10 requirement IDs. Jellyfin runs behind Caddy on an unpublished port with its own CSP and the portal's CSP untouched. The provisioned library passes its 11 checks live. The measured matrix has no Video transcode row, and the GO verdict is recorded. The naming decision (portal rename step, 76 % against a 90 % bar) is recorded with counts only.

The one gap from the first run is closed: the code review report no longer quotes a four-part dotted version that the hygiene test read as a LAN address. Verified by re-running the tests, not by the commit message.

---

_Verified: 2026-10-27_
_Verifier: Claude (gsd-verifier)_
