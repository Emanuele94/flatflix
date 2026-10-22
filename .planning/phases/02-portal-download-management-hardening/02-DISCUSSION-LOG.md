# Phase 2: Portal Download Management & Hardening - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-10-22
**Phase:** 02-portal-download-management-hardening
**Areas discussed:** Downloads list, Cancel rules, Throttle & logs, Phase 1 leftovers

---

## Downloads list

| Option | Description | Selected |
|--------|-------------|----------|
| Portal-started only | Only `fx`-tagged torrents | |
| All Film + SerieTV | Everything in the two categories | ✓ |

| Option | Description | Selected |
|--------|-------------|----------|
| Two tabs: Search \| Downloads | Tab bar under the header | ✓ |
| Below the search | One long page | |
| You decide | | |

| Option | Description | Selected |
|--------|-------------|----------|
| Name, type, bar, plain state + ETA | | ✓ |
| Minimal | No ETA | |
| Detailed | Speed, size, seeders | |

| Option | Description | Selected |
|--------|-------------|----------|
| 7 days after completion | Env-configurable, file stays | ✓ |
| Forever | | |
| Until seeding stops | | |

| Option | Description | Selected |
|--------|-------------|----------|
| Failed attempts shown 24 h | In memory | ✓ |
| Not shown | | |

| Option | Description | Selected |
|--------|-------------|----------|
| Active first, then newest | | ✓ |
| Newest first | | |

| Option | Description | Selected |
|--------|-------------|----------|
| Poll only while tab visible | | ✓ |
| Always while logged in | | |

---

## Cancel rules

| Option | Description | Selected |
|--------|-------------|----------|
| In progress: delete torrent + partial files, one confirm | | ✓ |
| In progress: remove torrent, keep files | | |

| Option | Description | Selected |
|--------|-------------|----------|
| Completed: "Remove from list" only, file kept | | ✓ |
| Completed: delete the film too | | |
| Completed: nothing | | |

| Option | Description | Selected |
|--------|-------------|----------|
| Admin-added torrents: same rules | | ✓ |
| Admin-added torrents: read-only | | |

---

## Throttle & logs

| Option | Description | Selected |
|--------|-------------|----------|
| Generous: search 10/min, download 20/min | | ✓ |
| Strict: 5/min each | | |

| Option | Description | Selected |
|--------|-------------|----------|
| Plain wait message | | ✓ |
| Message with countdown | | |

| Option | Description | Selected |
|--------|-------------|----------|
| stdout only + Docker rotation | | ✓ |
| Also a file on a volume (30 days) | | |

| Option | Description | Selected |
|--------|-------------|----------|
| Log search text + torrent names + IP | | ✓ |
| No search text | | |

---

## Phase 1 leftovers

| Option | Description | Selected |
|--------|-------------|----------|
| Fold cache fix (no-cache index.html) | | ✓ |
| Later | | |

| Option | Description | Selected |
|--------|-------------|----------|
| Fold WR-01, treat as unsupported | | ✓ |
| Later | | |

| Option | Description | Selected |
|--------|-------------|----------|
| Outage: keep last list greyed + banner, auto-retry | | ✓ |
| Outage: replace list with message | | |

---

## Claude's Discretion

- qBittorrent state → plain state mapping, ETA wording, list API shape, throttle keying, log format, visual design.

## Deferred Ideas

- Deleting a completed film from the phone.
- Verifying / rejected-by-probe states (Phase 2.1).
