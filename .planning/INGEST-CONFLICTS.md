## Conflict Detection Report

### BLOCKERS (0)

(none)

### WARNINGS (3)

[WARNING] Naming convention gap: torrent downloads will not match Jellyfin's required layout
  Found: /home/emanuele/projects/flatflix/home-theater.md requires "Titolo (Anno)/Titolo (Anno).mkv" for films and "Serie/Season 01/Serie S01E01.mkv" for series, "to be respected for the scan to work". /home/emanuele/projects/flatflix/qbit-wrapper.md saves torrents as-is into /media/Film and /media/SerieTV (sections 5.2 and 6), with no renaming or organizing step, and lists "Replace Sonarr/Radarr or other library managers" as a non-goal. Season/episode search and Jellyfin integration appear only under "Future extensions" (section 14).
  Impact: Torrent names are arbitrary (release-group names, flat files, varied folder structures), so Jellyfin will mis-identify or skip many downloads. Neither doc owns the rename/organize step, so the non-technical household user would see missing or wrong titles in the TV app.
  → Decide who enforces the layout: add a post-download rename/move step in the qbit backend, accept a different tool (e.g. a library manager, currently a non-goal), or relax the Jellyfin requirement. Record it as a decision before roadmapping.

[WARNING] Shared media folders are not wired consistently between the two docs
  Found: /home/emanuele/projects/flatflix/qbit-wrapper.md uses host paths /media/Film and /media/SerieTV (qBittorrent writes there, final save path, no separate incomplete folder specified). /home/emanuele/projects/flatflix/home-theater.md only says Jellyfin has "volumes for config, cache and media folder" with no host path, no library-per-folder definition, and no read-only/permission detail.
  Impact: Jellyfin may mount a different path, miss one of the two folders, or lack read permission on files written by the qBittorrent container. Jellyfin may also scan partially downloaded files in the final folder, and nothing triggers a library rescan when a download completes.
  → Specify in one place the host paths, Jellyfin mounts (read-only is enough) and the two Jellyfin libraries (Film, SerieTV), user/permission alignment between containers, and whether to use an incomplete-downloads folder and a scan trigger or schedule.

[WARNING] Port 8080 is used by both the qbit portal frontend and the qBittorrent WebUI; Caddy port is undefined
  Found: /home/emanuele/projects/flatflix/qbit-wrapper.md compose example publishes frontend as "8080:80" (host port 8080) and sets WEBUI_PORT=8080 for qBittorrent (backend reaches it at http://qbittorrent:8080). /home/emanuele/projects/flatflix/home-theater.md puts Caddy in front of the TV frontend and Jellyfin (admin on 8096) and uses "http://<ip-laptop>:<porta>" with no port number.
  Impact: As written the qbit compose example has no host collision (qBittorrent's 8080 is container-internal and unpublished), but the duplicated number is easy to misread. It collides as soon as the qBittorrent WebUI is published on the host (needed for the manual category setup the doc allows) or host networking is used. Caddy's host port is unassigned and may also clash with 8080 on the same laptop, and the doc does not say whether the two compose stacks share a Docker network or one reverse proxy.
  → Assign a port map for the whole laptop (Caddy, qbit portal frontend, qBittorrent WebUI if published, Jellyfin 8096). Consider changing qBittorrent WEBUI_PORT to a distinct value (and updating QBITTORRENT_URL) and decide whether Caddy fronts the qbit portal too.

### INFO (4)

[INFO] No ADRs, PRDs or locked decisions in the ingest set
  Note: Both docs (/home/emanuele/projects/flatflix/home-theater.md, /home/emanuele/projects/flatflix/qbit-wrapper.md) are classified SPEC with locked: false. Precedence rules (ADR > SPEC > PRD > DOC) were not exercised; no LOCKED-vs-LOCKED, no cross-precedence override, no auto-resolution occurred. No cross_refs, so no cycles.

[INFO] Classification confidence is low for home-theater.md
  Note: /home/emanuele/projects/flatflix/home-theater.md is SPEC with low confidence (mixed SPEC/PRD/DOC signals, no ADR signals); /home/emanuele/projects/flatflix/qbit-wrapper.md is SPEC with medium confidence. Neither is UNKNOWN, so no re-tag blocker was raised. Requirement lists, risks, phases and open decisions were preserved in constraints.md and context.md rather than requirements.md. Re-tag via --manifest if PRD treatment is preferred.

[INFO] External access scope differs between the two docs
  Note: /home/emanuele/projects/flatflix/home-theater.md puts access from outside the home out of scope (open decision on VPN). /home/emanuele/projects/flatflix/qbit-wrapper.md includes an HTTPS reverse proxy for "secure external access" and makes HTTPS mandatory only if reachable from outside. Not a contradiction for a LAN-only deployment; relevant if either part is later exposed.

[INFO] Open decisions inside home-theater.md are unresolved, not conflicts
  Note: /home/emanuele/projects/flatflix/home-theater.md lists five unchecked open decisions (Preact vs SolidJS, final server hardware, single vs separate Jellyfin users, default audio/subtitle language, external access). Recorded in context.md; the Preact + Vite choice is "proposed", not locked. Backend stack in qbit-wrapper.md is also undecided ("FastAPI/Node").
