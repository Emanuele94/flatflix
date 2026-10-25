# Phase 3: Jellyfin Server & TV Playback Gate - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-10-25
**Phase:** 03-jellyfin-server-tv-playback-gate
**Areas discussed:** Jellyfin address, Codec test media, Naming decision, User/language/bitrate, Jellyfin image, TV test session, Sample library, Matrix location

---

## Jellyfin address

| Question | Options | Selected |
|----------|---------|----------|
| Path on the Caddy origin | /jellyfin subpath; own Caddy port; you decide | /jellyfin subpath |
| TV address | Fixed IP; IP + .local name; router DNS name | Other: "if mDNS is usable I would prefer that, we need to try on my TV" (photo of TV info: firmware V0003.09.60A.Q0707) |
| Admin UI | Via Caddy only; also 127.0.0.1:8096 | Via Caddy only |
| Test host | Dev laptop; wait for prod box | Dev laptop |

**Notes:** Serial, device ID and Netflix ESN visible in the photo are not recorded (public repo).

## Codec test media

| Question | Options | Selected |
|----------|---------|----------|
| Sample source | ffmpeg from Blender; public test sets; both | Both |
| Resolutions | 1080p gate + 4K info; 1080p only | 1080p gate + 4K info |
| PGS subtitles | Test, don't gate; gate on them; skip | Test, don't gate |
| Mitigation lean | Decide on evidence; audio transcode OK + stick; stronger hardware | Decide on evidence |

## Naming decision

| Question | Options | Selected |
|----------|---------|----------|
| Lean | Portal rename step; relaxed; external manager; no lean | Portal rename step |
| Test names | Real result names; hand-written; both | Real result names |
| Relaxed threshold | All right; ≥90 % rest flagged; you decide | ≥90 %, rest flagged |
| TMDB lookup | Allowed opt-in key; offline only; decide after test | Allowed, opt-in key |

## User, language, bitrate

| Question | Options | Selected |
|----------|---------|----------|
| Household user | Shared + password; shared, no password | Shared user + password |
| Audio | Italian else original; original; English else original | English, else original |
| Subtitles | Smart Italian; Smart English; off | Smart, English |
| TV network | Ethernet; Wi-Fi; not sure | Ethernet |

## Extra areas

| Question | Options | Selected |
|----------|---------|----------|
| Jellyfin image | linuxserver; official; you decide | You decide |
| TV test session | Helper script; manual checklist | Helper script |
| Series sample | CC series on TMDB; Blender as episodes; you decide | CC series |
| Matrix location | Committed doc; .planning only | Committed doc |

## Claude's Discretion

- Jellyfin image (pinned either way), mDNS name and mechanism, bitrate cap value, clip list, compose network placement, 4K rows.

## Deferred Ideas

None.
