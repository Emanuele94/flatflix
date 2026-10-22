# API Coverage — qBittorrent Web API v2

> Full coverage by default. Opt-outs are explicit, reasoned decisions.
> Source of truth for INTEGRATE rows: `backend/app/qbit/client.py` and `backend/app/qbit/bootstrap.py`.
> The browser never calls this API; the backend is the only client (SEC-01..04).

| capability | decision | reason |
|---|---|---|
| auth/login (session cookie, re-login on 403) | INTEGRATE | |
| auth/logout | OPT-OUT | backend keeps one long-lived session; re-login on 403 covers expiry |
| app/webapiVersion | INTEGRATE | |
| app/preferences + app/setPreferences (exclusion list, bootstrap) | INTEGRATE | |
| app/version, buildInfo, shutdown, defaultSavePath | OPT-OUT | not needed; save paths come from categories and are never exposed |
| search/start, status, results, stop, delete | INTEGRATE | |
| search/plugins, installPlugin | INTEGRATE | |
| search/uninstallPlugin, enablePlugin, updatePlugins | OPT-OUT | plugin management is an admin task via the admin WebUI, not the household portal |
| torrents/add (stopCondition=MetadataReceived) | INTEGRATE | |
| torrents/files + torrents/filePrio (allowlist filtering) | INTEGRATE | |
| torrents/start | INTEGRATE | |
| torrents/delete (with files, on reject) | INTEGRATE | |
| torrents/info (job polling) | INTEGRATE | |
| torrents/categories, createCategory, editCategory (Film, SerieTV) | INTEGRATE | |
| torrents tags (removeTags, deleteTags for fx-pending) | INTEGRATE | |
| torrents/stop, recheck, reannounce, setLocation, rename*, setShareLimits, setDownloadLimit, setUploadLimit, topPrio and other per-torrent controls | OPT-OUT | not needed yet — a downloads list with controls is Phase 2 (DOWN-04, D-11) |
| torrents/properties, trackers, webseeds, pieceStates, pieceHashes | OPT-OUT | not needed; the portal shows only a plain status |
| sync/maindata, sync/torrentPeers | OPT-OUT | not needed; per-job polling of torrents/info is enough for Phase 1 |
| transfer/* (global speed limits, ban peers, transfer info) | OPT-OUT | explicitly out of scope; global limits are admin settings in the admin WebUI |
| log/main, log/peers | OPT-OUT | explicitly out of scope; logs stay with the admin |
| rss/* | OPT-OUT | explicitly out of scope; the portal is search-and-start only |
