# API Coverage — Jellyfin REST API 12.3 (stock server)

> Full coverage by default. Opt-outs are explicit, reasoned decisions.
> Source of truth for INTEGRATE rows: `scripts/jellyfin_setup.py` (plans 03-03 and 03-04), `scripts/tv_gate.py` (plan 03-06) and `scripts/name_scan.py` (plan 03-05).
> Every call goes through Caddy at `/jellyfin` (D-82); no client calls port 8096. Jellyfin itself talks to TheMovieDb; this phase writes no code against TheMovieDb.

| capability | decision | reason |
|---|---|---|
| Startup wizard (Configuration, User, RemoteAccess, Complete) | INTEGRATE | |
| System/Info/Public (wizard state, version) | INTEGRATE | |
| System/Configuration get and update (server name, language, bitrate limit) | INTEGRATE | |
| Users/AuthenticateByName | INTEGRATE | |
| Users list, Users/Public, Users/New, Users/{id} | INTEGRATE | |
| Users/{id}/Policy (hidden admin, household permissions, folders, bitrate) | INTEGRATE | |
| Users/{id}/Password (reset the household password from .env) | INTEGRATE | |
| Users/Configuration (audio and subtitle language, Smart mode) | INTEGRATE | |
| Library/VirtualFolders get and create (all five libraries) | INTEGRATE | |
| Library/Refresh | INTEGRATE | |
| ScheduledTasks list (RefreshLibrary state for the scan wait) | INTEGRATE | |
| Items query (provider ids, plot, cast, images, path, episode numbers) | INTEGRATE | |
| Sessions list (play method, TranscodingInfo, TranscodeReasons) | INTEGRATE | |
| Items/{id}/PlaybackInfo (helper self-test profiles) | INTEGRATE | |
| HLS master, variant and segment requests (self-test remux and transcode jobs) | INTEGRATE | |
| Videos/{id}/stream static (self-test direct play) | INTEGRATE | |
| Sessions/Playing and Sessions/Playing/Stopped (self-test reports) | INTEGRATE | |
| Videos/ActiveEncodings delete (self-test cleanup) | INTEGRATE | |
| Playback/BitrateTest (LAN throughput for the bitrate limit) | INTEGRATE | |
| ApiKey create, list, revoke | OPT-OUT | not needed: scripts sign in per run and keep no stored key (ASVS V3) |
| QuickConnect endpoints | OPT-OUT | not needed: Quick Connect is used through the stock web UI only, never scripted |
| Plugins and Packages (install, configure, repositories) | OPT-OUT | explicitly out of scope: stock TheMovieDb and OMDb providers only |
| Branding (custom CSS, login disclaimer, splash) | OPT-OUT | explicitly out of scope: UI-SPEC decides no custom branding |
| DisplayPreferences, UserViews, Resume, NextUp, Latest, Suggestions | OPT-OUT | not needed yet: the Phase 5 TV app (TV-01..TV-03) |
| Search, Filters, Genres, Persons, Studios, Years, Movies recommendations | OPT-OUT | not needed yet: the Phase 5 TV app |
| Image download, upload and remote image search | OPT-OUT | not needed: artwork comes from automatic scans; posters for the TV app are Phase 5 |
| ItemUpdate, per-item ItemRefresh, ItemLookup and remote search | OPT-OUT | not needed: metadata comes from library scans only |
| Library item delete, Collections, Playlists | OPT-OUT | explicitly out of scope: the household cannot delete media or manage collections |
| LiveTv, Channels, music and audio endpoints, Lyrics | OPT-OUT | explicitly out of scope: films and series only |
| SyncPlay, TimeSync | OPT-OUT | explicitly out of scope: single household, no group playback |
| Trickplay, MediaSegments, VideoAttachments | OPT-OUT | not needed: trickplay and chapter image extraction are off |
| Remote subtitle search and download | OPT-OUT | not needed yet: automatic subtitles are SUBT-01 (v2) |
| Session remote-control commands (play, command, message) | OPT-OUT | explicitly out of scope: remote control of other sessions is off for the household |
| Devices list and options | OPT-OUT | not needed: the helper stores no device data (D-89) |
| ActivityLog, ClientLog, Environment, Backup and Restore, Localization | OPT-OUT | not needed: the admin uses the dashboard UI; paths are fixed |
| Users delete and rename | OPT-OUT | not needed: two fixed accounts (admin, household) |
| Playstate progress and watched marks | OPT-OUT | not needed yet: Continue watching and watched marks are PLAY-03 (Phase 5) |
| TheMovieDb API called directly by the portal backend | OPT-OUT | not needed yet: allowed with an opt-in key (D-93); Phase 4 decides from the NAME-01 result |
