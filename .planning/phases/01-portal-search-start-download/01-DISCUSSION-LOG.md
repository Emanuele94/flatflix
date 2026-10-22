# Phase 1: Portal Search & Start Download - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-10-21
**Phase:** 01-portal-search-start-download
**Areas discussed:** Stack backend + frontend, Search and results, Torrent acceptance flow, Login and access

---

## Stack backend + frontend

| Option | Description | Selected |
|--------|-------------|----------|
| FastAPI (Python) | Little code, Pydantic validation, httpx async; Python reused for Phase 2.1 scripts | ✓ |
| Node (Fastify/Hono) | TypeScript everywhere | |
| You decide | | |

| Option | Description | Selected |
|--------|-------------|----------|
| Preact + Vite SPA | Same stack as TV app, live results | ✓ |
| Server-rendered + htmx | Minimal JS, no build | |
| You decide | | |

| Option | Description | Selected |
|--------|-------------|----------|
| Backend serves static files | One app container, Caddy in Phase 3 | |
| Separate frontend container | As in doc compose example | |
| Caddy already in Phase 1 | Caddy in front from the start | ✓ |

| Option | Description | Selected |
|--------|-------------|----------|
| Caddy serves static build | `/` = SPA, `/api/*` → FastAPI | ✓ |
| Caddy only proxies to FastAPI | FastAPI serves SPA and API | |

| Option | Description | Selected |
|--------|-------------|----------|
| 80 | Short URL, needs WSL2 port forward | ✓ |
| 8080 | Avoids conflicts on 80 | |
| You decide | | |

| Option | Description | Selected |
|--------|-------------|----------|
| One Caddy, different paths | e.g. `/portale` and `/tv` on same port | ✓ |
| One Caddy, different ports | Separate origins | |
| Decide in Phase 3 | | |

**User's choice:** FastAPI, Preact + Vite, Caddy in Phase 1 serving the static build on port 80, one Caddy with paths for portal and TV.

---

## Search and results

| Option | Description | Selected |
|--------|-------------|----------|
| Fill in live | First results ~2 s, list grows and re-sorts | ✓ |
| Live, stable order | Append, sort at end | |
| Single list at end | Violates SRCH-03 | |

| Option | Description | Selected |
|--------|-------------|----------|
| Hide 0 seeders | | (free text) |
| Show all | | |
| Hide 0 + cap 50 | | |

**Notes (free text):** "We should definitely hide 0 seeders, but let's find a sweet spot that lets us find safe files with enough seeders to allow the download" (translated from Italian).

| Option | Description | Selected |
|--------|-------------|----------|
| Configurable, default 5 | Env `MIN_SEEDERS=5` | ✓ |
| Fixed 1 | | |
| Fixed 10 | | |

| Option (multi-select) | Description | Selected |
|--------|-------------|----------|
| Hide too-small films | e.g. film < 500 MB | ✓ |
| Trusted search plugins only | Admin enables only reliable plugins | ✓ |
| Hide suspicious names | `.exe`, `password`, `codec` | ✓ |
| Highlight 1080p/4K | Quality badge from name | ✓ |

| Option | Description | Selected |
|--------|-------------|----------|
| Name + size + seeders prominent | Leechers/source small | ✓ |
| All fields equal | | |

| Option | Description | Selected |
|--------|-------------|----------|
| Stay on results, button → "Started ✓" | | ✓ |
| Confirmation screen | | |

---

## Torrent acceptance flow

| Option | Description | Selected |
|--------|-------------|----------|
| Short wait, then hand-off | Spinner ~15 s, then "In preparazione", backend continues | ✓ |
| Always wait for outcome | Can block minutes | |
| Immediately "Started" | Rejection never seen in Phase 1 | |

| Option | Description | Selected |
|--------|-------------|----------|
| Configurable, default 5 min | Env `METADATA_TIMEOUT` | ✓ |
| 2 minutes | | |
| Never | | |

| Option | Description | Selected |
|--------|-------------|----------|
| "This file doesn’t contain a video. Try another result." | | ✓ |
| With short reason | | |

| Option | Description | Selected |
|--------|-------------|----------|
| All allowed videos, exclude samples | | ✓ |
| All allowed videos (pure allowlist) | | |

---

## Login and access

| Option | Description | Selected |
|--------|-------------|----------|
| One shared account | | ✓ |
| Multiple users from env | | |

| Option | Description | Selected |
|--------|-------------|----------|
| 30 days, persistent cookie | | ✓ |
| 7 days | | |
| Until browser close | | |

| Option | Description | Selected |
|--------|-------------|----------|
| Hash (bcrypt/argon2) | `APP_PASS_HASH` | ✓ |
| Plaintext | | |

| Option | Description | Selected |
|--------|-------------|----------|
| Basic limit in Phase 1 | 5 failures / 15 min per IP | ✓ |
| All in Phase 2 | | |

---

## Claude's Discretion

- Exact Caddy paths, live-result transport (polling vs SSE), suspicious-name list, sample heuristic, series size threshold, visual design, media folder layout details.

## Deferred Ideas

None.
