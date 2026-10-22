---
status: diagnosed
trigger: "UAT gap G-01-2 (phase 01, test 2): .webm-only Tears of Steel result shows 'Download failed. Try again.' instead of 'This video format isn't supported. Try another result.' (G-01-1 withdrawn by the coordinator: the same .webm tap; test 1 recorded as pass)"
created: 2026-10-22T15:30:00Z
updated: 2026-10-22T15:36:00Z
goal: find_root_cause_only
symptoms_prefilled: true
---

## Current Focus

bug_class: Bohrbug (deterministic) at the version-skew level; not a pipeline or UI-source defect
hypothesis: CONFIRMED (inference from request logs, see Evidence) - the phone page ran the pre-01-16 JavaScript, which maps the new backend status "unsupported" to "failed"
test: done
expecting: n/a
next_action: return ROOT CAUSE FOUND to the caller; user re-test needs a freshly loaded page (the 15:28:23 load already has the new bundle)

reasoning_checkpoint:
  hypothesis: "The backend answers {status: unsupported} correctly (live-engine repro, HTTP level). The served bundle maps it to the unsupported message. The phone, however, was running JS loaded before the 14:55 rebuild: pre-01-16 Search.jsx has JOB_STATES without 'unsupported', and applyJob turns any unknown status into 'failed' -> MSG.downloadFailed 'Download failed. Try again.'"
  confirming_evidence:
    - "POST /api/download for the piratebay webm result returns 200 {status: unsupported} from the running backend code (in-process ASGI repro against the real qBittorrent)"
    - "git show 9396400:frontend/src/Search.jsx (last pre-01-15 version) has JOB_STATES = started, preparing, rejected, unavailable, duplicate, failed and `JOB_STATES.has(res.status) ? res.status : 'failed'`"
    - "backend log 14:55:16 -> 15:28:23: login (15:19:50), search, 2 downloads and a second search + download all happened with NO page-load signature (GET /api/session + GET /api/health via Caddy); the first such pair is 15:28:23. A fresh page load always makes both calls (App.jsx), so the phone page predates the 14:55 rebuild"
  falsification_test: "Reload the phone page (new index.html and bundle, GET /api/session + /api/health appear in the log) and tap the webm result again: if it still says 'Download failed' the hypothesis is wrong and the cause is in the live bundle/backend path"
  fix_rationale: "n/a (diagnose only)"
  blind_spots: "I cannot see the phone's JS directly; the stale-page conclusion rests on the absence of page-load requests in the backend log and on the exact message match. The test 1 result (Belli Ciao reaches Started) is consistent with both old and new bundles"
  candidate_causes:
    - "environment (client cache / long-lived tab): phone page loaded before the rebuild (CONFIRMED by inference)"
    - "code (backend decide/pipeline maps the webm torrent to failed): ELIMINATED, repro gives unsupported"
    - "code (served frontend bundle maps unsupported to failed): ELIMINATED, bundle has the mapping and tests cover it"
    - "data (torrent carries other files that take another path): ELIMINATED, one file only"
  and_gate: "yes: (1) a status the old client does not know (backend 01-16) AND (2) a client still on the old bundle. Either alone is harmless. Contributing amplifier: Caddy sends no Cache-Control, and the client maps every unknown status to the generic failure"

## Symptoms

expected: .webm-only Tears of Steel result -> "This video format isn't supported. Try another result." (button disabled)
actual: row ends with "Download failed. Try again." (user, phone, UAT test 2; test 1 was the same tap)
errors: none shown beyond the UI message
reproduction: UAT tests 1-2 in .planning/phases/01-portal-search-start-download/01-UAT.md
started: first phone UAT after gap closure plans 01-14/15/16 and the 14:55 stack rebuild

## Eliminated

- hypothesis: running containers serve stale 01-16 code (backend)
  evidence: container created 14:55:10Z (after commit 164f965 at 14:54:46Z); grep inside the running backend shows video_format, JobState.UNSUPPORTED, stopCondition
  timestamp: 2026-10-22T15:29:00Z
- hypothesis: running web container serves a stale frontend bundle
  evidence: curl http://127.0.0.1/assets/index-D0xfx9Od.js contains the unsupportedFormat message, the unsupported row mapping and 'unsupported' in JOB_STATES
  timestamp: 2026-10-22T15:29:00Z
- hypothesis: metadata never arrives / timeout (generic failure after 300 s)
  evidence: both POST /api/download answered within about 3 s of the add (15:20:16, 15:20:25); qBittorrent log shows stopped at metadata then removed + content removed within 1-3 s
  timestamp: 2026-10-22T15:29:30Z
- hypothesis: the torrent carries other files (.mp4/.srt/sample) that send it down another path
  evidence: real file list read from qBittorrent: exactly one file, idx 0, 571346576 bytes, 'tears_of_steel_1080p.webm', for both the piratebay and the limetorrents result; decide() -> accept False, reason video_format
  timestamp: 2026-10-22T15:31:00Z
- hypothesis: the pipeline raises or maps the job to failed before decide()
  evidence: job.state after the run is 'unsupported' (task done in about 3 s); no 'download job ... failed/crashed' lines in backend logs
  timestamp: 2026-10-22T15:31:00Z
- hypothesis: the new frontend source maps 'unsupported' to the failed message
  evidence: Search.jsx JOB_STATES includes 'unsupported'; ResultRow MESSAGE.unsupported = MSG.unsupportedFormat; Search.test.jsx lines 394, 469, 720 feed {status: unsupported} through the POST and poll paths
  timestamp: 2026-10-22T15:32:00Z

## Evidence

- timestamp: 2026-10-22T15:28:00Z
  checked: backend logs with timestamps (docker compose logs -t backend)
  found: POST /api/download 15:20:16.49 and 15:20:25.78, both 200, no GET /api/download/<id> polls at all, no WARNING/ERROR about a failed or crashed job
  implication: the job was already terminal when the POST answered (the POST waits up to 15 s); the client never polled, so the status in the POST body alone decided the row text

- timestamp: 2026-10-22T15:28:30Z
  checked: qbittorrent.log 15:20
  found: 15:20:13 add "Tears of Steel (2012) 1080p webm" -> 15:20:15 stopped -> 15:20:16 removed + content removed; 15:20:22 add "tears of steel 1080p webm (movie)" (limetorrents) -> 15:20:24 stopped -> 15:20:25 removed + content removed. Non-webm 15:26:46 "Belli Ciao" -> stopped -> resumed 15:26:51 (works)
  implication: both webm taps went add -> metadata stop -> decide() -> _discard; the start path is fine

- timestamp: 2026-10-22T15:31:00Z
  checked: live repro, scratchpad repro_pipeline.py run inside the backend container (real DownloadPipeline, real qBittorrent, spy on decide)
  found: piratebay "Tears of Steel (2012) 1080p webm" and limetorrents "tears of steel 1080p webm (movie)" both list one file tears_of_steel_1080p.webm (571346576 B); DECISION accept=False reason=video_format; job.state = unsupported for both
  implication: the backend is correct and the torrent is webm-only

- timestamp: 2026-10-22T15:33:00Z
  checked: live repro, scratchpad repro_http.py (in-process FastAPI app, real routers/pipeline/qBittorrent, auth dependency overridden, no bootstrap/reconcile)
  found: POST /api/download -> 200 {"status": "unsupported", "job_id": "..."} for both webm results
  implication: the wire answer is already the new status; only the client decides the wording

- timestamp: 2026-10-22T15:34:00Z
  checked: git show 9396400:frontend/src/Search.jsx (pre-01-15/16 frontend) lines 12-13, 86-87
  found: JOB_STATES lacks 'unsupported'; applyJob: `res && JOB_STATES.has(res.status) ? res.status : 'failed'`; 'failed' is a retryable row with MSG.downloadFailed
  implication: the old client shows exactly the reported text, with a still-enabled button, for the new backend status

- timestamp: 2026-10-22T15:35:00Z
  checked: backend log page-load signature (App.jsx calls GET /api/session and GET /api/health on mount; all browser traffic arrives from the Caddy address <caddy-container-ip>)
  found: after the backend start at 14:55:16 the only GET /api/session lines are 14:55:38 (orchestrator smoke, 401/200/401 on one connection, no health) and 15:28:23 (with GET /api/health, a real page load). One lone GET /api/health at 15:02:18. Yet POST /api/login 15:19:50, search 15:20:05, downloads 15:20:16 and 15:20:25, and search + download 15:26:40/51 happened
  implication: the phone page that did the UAT taps was loaded before 14:55:16 (the earlier UAT round), i.e. it ran the pre-01-15/16 bundle; the rebuild replaced the backend and the served bundle under a page that stayed open. Old hashed assets no longer exist: Caddy's try_files fallback answers any missing /assets path with index.html (verified: a made-up asset name returns 200 text/html, 390 B)

- timestamp: 2026-10-22T15:35:30Z
  checked: web/Caddyfile and live response headers
  found: no Cache-Control on index.html or /assets/*; only ETag and Last-Modified (index.html Last-Modified 14:55:05 GMT). No service worker
  implication: browsers may serve a cached index.html heuristically (10 % of its age) and keep a long-lived tab's JS indefinitely; nothing tells a phone browser to revalidate the shell after a redeploy

- timestamp: 2026-10-22T15:36:00Z
  checked: cleanup
  found: all repro torrents were deleted by the pipeline (qBittorrent log: removed + content removed); doctor --torrents lists only "Belli Ciao" (user's, downloading) and "Sintel" (pre-existing). Admin overlay never used; compose stack untouched. Scratch scripts live in the session scratchpad only
  implication: nothing to restore

## Resolution

root_cause: |
  Client/server version skew, not a pipeline defect. Plan 01-16 added a new backend status "unsupported". The running backend and
  the served bundle both handle it correctly (POST /api/download -> {"status":"unsupported"}; the new frontend maps it to
  "This video format isn't supported..."). The phone page that did the UAT taps was loaded BEFORE the 14:55 rebuild (no
  GET /api/session + /api/health page-load pair in the backend log between 14:55:16 and 15:28:23, although login, search and downloads
  happened), so it ran the pre-01-16 bundle. That bundle's JOB_STATES has no 'unsupported', and applyJob maps every unknown status to
  'failed', so the row showed the retryable "Download failed. Try again." for both .webm taps. The torrent is .webm-only (one file,
  tears_of_steel_1080p.webm), so decide() correctly returns video_format. G-01-1 was the same tap (withdrawn).
  Amplifiers: web/Caddyfile sets no Cache-Control (nothing forces a phone to revalidate the shell after a redeploy), and the client
  falls back to the generic failed message for any status it does not know.
fix: (diagnose only - not applied)
verification: (diagnose only) re-test on a freshly loaded phone page; expect the format message and a disabled button
files_changed: []
