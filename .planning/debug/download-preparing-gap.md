---
status: diagnosed
trigger: "UAT gap G-01-3 (phase 01, test 3): limetorrents result stuck on Preparing; piratebay .webm shown 'This file doesn't contain a video'; reload during Preparing loses row state"
created: 2026-10-22T13:46:18Z
updated: 2026-10-22T13:58:00Z
goal: find_root_cause_only
symptoms_prefilled: true
---

## Current Focus

bug_class: Bohrbug (deterministic) for (a) and (b); (c) is a missing feature (no client persistence), not a fault
hypothesis: CONFIRMED for all three sub-symptoms (see Resolution)
test: done
expecting: n/a
next_action: return ROOT CAUSE FOUND to the caller; fix is planned by plan-phase --gaps

reasoning_checkpoint:
  hypothesis: "(a) pipeline.py:186 adds every non-magnet result with stopped=true; qBittorrent's downloader passes the SAME AddTorrentParams to whatever the plugin prints; limetorrents prints a magnet, so a magnet is added stopped and never fetches metadata, and the job ends UNAVAILABLE after METADATA_TIMEOUT"
  confirming_evidence:
    - "limetorrents.py download_torrent() prints '<magnet> <info_url>' (it scrapes the magnet from the info page)"
    - "qBittorrent 5.2.4 torrentscontroller.cpp addAction: downloadFinished -> addTorrentManager()->addTorrent(torrentFilePath, addTorrentParams) with the captured params (addStopped=true)"
    - "qBittorrent log: 'tears of steel 1080p webm (movie)' added 13:37:08, removed 13:42:08 = exactly 300 s (METADATA_TIMEOUT -> _discard); no 'content removed' line (no metadata, no files)"
    - "live state before removal: stoppedDL, has_metadata=false, files [] (caller's evidence)"
  falsification_test: "If the limetorrents downloader had produced a .torrent file, the torrent would have had metadata at add and a non-empty file list within seconds; it never did"
  fix_rationale: "Always send stopCondition=MetadataReceived and never stopped: qBittorrent itself turns that into stopped=true (libtorrent paused flag) for any torrent that has metadata at add (sessionimpl.cpp:2794-2801, 2920-2921), so the WR-04 property holds for .torrent results AND a downloader-resolved magnet can fetch its metadata"
  blind_spots: "qBittorrent version drift: the MetadataReceived->stopped conversion is verified in 5.2.4 source only (pinned image lscr.io/linuxserver/qbittorrent:5.2.4); plugin-downloader route has no real-engine test yet"
  candidate_causes:
    - "code: pipeline decides stopped/stopCondition from the search URL, not from what the downloader resolves (CONFIRMED)"
    - "config/environment: limetorrents site blocking the info-page fetch -> plugin raises, nothing added (ELIMINATED: torrent was added with a magnet dn name)"
    - "data: the magnet has no seeds so metadata never arrives (ELIMINATED as primary: a stopped torrent never contacts peers at all, so seed count is irrelevant)"
  and_gate: "yes for the user-visible symptom: (1) a plugin whose downloader yields a magnet AND (2) the stopped=true add. Either alone is harmless: magnets from piratebay use stopCondition; .torrent results from torlock are fine stopped"

## Symptoms

expected: Tap Download on a "Tears of Steel" film result -> row shows Preparing then "Started"; file lands in the host Film folder.
actual: |
  (a) limetorrents "tears of steel 1080p webm (movie)": row stuck on "Preparing". qBittorrent: state stoppedDL,
      has_metadata=false, tags fx, fx-pending, fx-job-7569a2009648dd8d, files [].
  (b) piratebay "Tears of Steel (2012) 1080p webm": row shows "This file doesn't contain a video. Try another result."
  (c) page reload during Preparing: the row's status is lost; the backend job keeps running.
errors: none (no stack trace); user-facing messages only
reproduction: phone -> portal -> search "Tears of steel" (Movie) -> tap Download on the limetorrents and piratebay webm results; reload the page while Preparing
started: first real-engine UAT of phase 01 (2026-10-22)

## Eliminated

- hypothesis: "(a) the limetorrents info-page fetch failed (Cloudflare / 'Connection error: Forbidden') so the plugin never produced a link"
  evidence: "qBittorrent log line 564 'Added new torrent. Torrent: \"tears of steel 1080p webm (movie)\"' - a torrent named from the magnet dn was added; the Forbidden lines are for search engines, not this download"
  timestamp: 2026-10-22T13:52:00Z

- hypothesis: "(a) the magnet simply has no peers, so metadata is slow"
  evidence: "state stoppedDL + has_metadata=false: a stopped torrent never announces or connects to peers, so seeds are irrelevant; research Pitfall 1 reproduced the same 'stopped magnet never fetches metadata' (62 s, zero files)"
  timestamp: 2026-10-22T13:52:00Z

- hypothesis: "(a) fix by detecting has_metadata=false after the add and calling torrents/start"
  evidence: "qBittorrent 5.2.4 WebAPI accepts stopCondition only in torrents/add (torrentscontroller.cpp:1096-1144); no endpoint sets it later. Starting a stopped magnet would run it with NO stop condition, so payload starts flowing right after metadata, before the allowlist - violates FILT-02/D-23"
  timestamp: 2026-10-22T13:55:00Z

## Evidence

- timestamp: 2026-10-22T13:46:18Z
  checked: backend/app/download/pipeline.py:178-187 (_add_and_process)
  found: "is_magnet = url.lower().startswith('magnet:') on the SEARCH RESULT url; add_torrent(..., downloader=None if is_magnet else engine, stopped=not is_magnet)"
  implication: every non-magnet result (plugin page URL) is added with stopped=true regardless of what the plugin actually resolves it to

- timestamp: 2026-10-22T13:46:18Z
  checked: backend/app/qbit/client.py:269-314 (add_torrent)
  found: "stopped=True sends form 'stopped=true' and NO stopCondition; stopped=False sends stopCondition=MetadataReceived"
  implication: the stopped path has no metadata fetch; it is only safe when the URL yields a .torrent file (metadata embedded)

- timestamp: 2026-10-22T13:46:18Z
  checked: backend/app/download/allowlist.py:12
  found: "VIDEO_EXTENSIONS = {.mkv, .mp4, .avi, .m4v}; .webm absent; decide() returns accept=False reason='no_video' when no file has an allowed video extension"
  implication: (b) a .webm-only torrent is rejected by design (FILT-02); the pipeline then sets JobState.REJECTED

- timestamp: 2026-10-22T13:48:00Z
  checked: qbittorrent/config/qBittorrent/nova3/engines/limetorrents.py (v4.15) download_torrent()
  found: "fetches the info page and prints `magnet_match.groups()[0] + ' ' + info` - i.e. a MAGNET URI, never a .torrent path. torrentproject.py (v1.92) does the same; torlock.py prints download_file() (a .torrent temp path); piratebay/torrentscsv emit magnets directly in search results"
  implication: for limetorrents (and torrentproject) the downloader route always yields a magnet

- timestamp: 2026-10-22T13:50:00Z
  checked: qBittorrent release-5.2.4 src/base/search/searchdownloadhandler.cpp + src/webui/api/torrentscontroller.cpp:1202-1215
  found: "downloadProcessFinished splits stdout '<path> <url>' and emits parts[0]; addAction's downloader branch connects downloadFinished to `app()->addTorrentManager()->addTorrent(torrentFilePath, addTorrentParams)` with the params captured at request time (addStopped from the `stopped` form field)"
  implication: the magnet printed by limetorrents is added with addStopped=true -> a stopped magnet -> never fetches metadata (Pitfall 1)

- timestamp: 2026-10-22T13:51:00Z
  checked: qbittorrent/config/qBittorrent/logs/qbittorrent.log lines 559-569 (read-only)
  found: "13:37:03 add 'Tears of Steel (2012) 1080p webm' (piratebay) -> 13:37:04 'Torrent stopped' (stop condition fired at metadata) -> 13:37:05 removed + content removed (REJECTED). 13:37:08 add 'tears of steel 1080p webm (movie)' (limetorrents, magnet dn name) -> 13:42:08 removed, no content line"
  implication: (a) ended exactly at METADATA_TIMEOUT=300 s via _discard -> JobState.UNAVAILABLE (fail-closed, as predicted in 01-REVIEW-FIX.md WR-04 last bullet). (b) the magnet path worked; the allowlist rejected it in ~2 s

- timestamp: 2026-10-22T13:52:00Z
  checked: backend logs (docker compose logs backend)
  found: "POST /api/download x2, then 13 polls of GET /api/download/7569a2009648dd8d (2 s interval), then nothing - the reload; no later poll"
  implication: (c) after the reload the client never asks about the job again; the job itself kept running server-side

- timestamp: 2026-10-22T13:53:00Z
  checked: qBittorrent release-5.2.4 src/base/bittorrent/sessionimpl.cpp:2794-2801 and 2920-2921
  found: "addTorrent_impl: `if (hasMetadata) { if (stopCondition == MetadataReceived) { loadTorrentParams.stopped = true; stopCondition = None; } }` and later `if (loadTorrentParams.stopped ...) p.flags |= lt::torrent_flags::paused`"
  implication: stopCondition=MetadataReceived on a torrent that already has metadata (.torrent file) is turned into a paused add BEFORE the libtorrent handle exists - identical to stopped=true. WR-04's open question is answered by source; the WR-04 real-engine evidence test (stoppedDL, 0 bytes) agrees

- timestamp: 2026-10-22T13:54:00Z
  checked: .planning/REQUIREMENTS.md FILT-02 and 01-CONTEXT.md D-23
  found: "FILT-02: 'The backend adds EVERY torrent with stopCondition=MetadataReceived'. D-23: 'adding torrents started with stopCondition=MetadataReceived, not stopped=true'"
  implication: the WR-04 fix (commit 7fa6969) deviates from FILT-02/D-23 for non-magnets; reverting to stopCondition-for-all restores the written requirement

- timestamp: 2026-10-22T13:54:30Z
  checked: backend/tests/fakeqbit.py:320-372, backend/tests/test_download_pipeline.py:517-576
  found: "FakeQbit treats every downloader add as a metadata-complete .torrent (`blocked = is_magnet and stopped` is False for a page URL, metadata always attached) and assumes stopCondition does NOT hold a metadata-complete torrent (contrary to sessionimpl.cpp:2797). Tests assert page_form['stopped']=='true' and 'stopCondition' not in page_form"
  implication: why not caught - the fake cannot model a downloader that resolves to a magnet, and the tests encode the buggy form

- timestamp: 2026-10-22T13:55:30Z
  checked: frontend/src/messages.js:26, ResultRow.jsx MESSAGE.rejected, 01-CONTEXT.md D-13, pipeline.py:258-262, jobs.py JobState
  found: "MSG.rejected = 'This file doesn’t contain a video. Try another result.' is the verbatim D-13 locked text. Backend computes decision.reason='no_video' but only exposes status 'rejected'; there is no distinction between 'no video at all' and 'video in a format we do not accept (.webm)'. No .webm mention anywhere in requirements, CONTEXT, docs or code"
  implication: (b) behaviour matches FILT-02 + D-13 exactly; the wording is misleading for a .webm film (it IS a video). Changing either the allowlist or the text is a spec/decision change (FILT-02, D-13)

- timestamp: 2026-10-22T13:56:00Z
  checked: frontend/src (grep sessionStorage|localStorage|indexedDB|history|location), Search.jsx state
  found: "no client persistence at all. rows, jobs (result_id -> {state, jobId}), q, type and search_id live only in useState/useRef; a reload drops the whole result list, not just the row state"
  implication: (c) restoring only result_id->job_id is not enough: the rows are gone too. Backend still answers GET /api/download/{job_id} (JobRegistry keeps up to 500 jobs) and GET /api/search/{search_id} for result_cache_ttl=900 s

- timestamp: 2026-10-22T13:56:30Z
  checked: 01-CONTEXT.md line 11 and D-11; REQUIREMENTS DOWN-04; ROADMAP Phase 2
  found: "'Out of this phase: download list, cancel ... (Phase 2)'. D-11: 'The final outcome becomes visible in the Phase 2 downloads list.' DOWN-04 (list with state/progress every ~5 s) is Phase 2, Pending"
  implication: a backend 'list active jobs' endpoint / downloads view is Phase 2 scope (DOWN-04); a frontend-only sessionStorage restore of the current search + job map is the in-scope phase-1 fix

## Resolution

root_cause: |
  (a) backend/app/download/pipeline.py:178-187 picks `stopped=not is_magnet` from the SEARCH RESULT URL. For a plugin page URL
      qBittorrent runs the plugin's downloader and adds whatever it prints with the same add params; limetorrents (and
      torrentproject) print a magnet, so a magnet is added fully stopped and can never fetch metadata (Pitfall 1). The job
      waits METADATA_TIMEOUT (300 s), deletes the torrent and ends UNAVAILABLE. Introduced by WR-04 (commit 7fa6969), which
      contradicts FILT-02/D-23; the fake and tests model every downloader result as a metadata-complete .torrent.
  (b) allowlist.py VIDEO_EXTENSIONS has no .webm (FILT-02 lists .mkv .mp4 .avi .m4v), so decide() rejects a .webm-only torrent;
      the UI shows the D-13 text "This file doesn’t contain a video", which is wrong for a .webm film. Behaviour is as
      specified; the gap is spec + wording, not code.
  (c) frontend/src/Search.jsx keeps rows and the job map only in component state; nothing is persisted, so a reload loses the
      result list and every job id while the backend job keeps running. A downloads list is Phase 2 (DOWN-04, D-11).
fix: (diagnose only - not applied)
verification: (diagnose only)
files_changed: []
