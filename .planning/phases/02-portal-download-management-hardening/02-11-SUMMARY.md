---
phase: 02-portal-download-management-hardening
plan: 11
subsystem: testing
tags: [integration, qbittorrent, smoke, docs, audit, rate-limits]
status: complete

requires:
  - phase: 02-portal-download-management-hardening
    provides: "Downloads list and DELETE route (02-04, 02-07), audit and redaction (02-09), Downloads tab cancel and remove (02-10), cache headers (02-03), rate limits (02-05)"
provides:
  - "Opt-in real-engine tests of the list fields, cancel, and the Film/SerieTV-only boundary"
  - "scripts/smoke.py downloads subcommand and a list check inside all"
  - "docs/setup.md admin guide: Downloads list, Rate limits, Logs and audit trail, Phones and new versions, one troubleshooting row"
affects: [phase-02-verification]

actuals:
  tokens: 4200
  tasks: 2
  commits: 2

commits: 2
plan_head_before: 5a4f7b837754056368a2c2f5489cffcb210ad751
plan_head_after: b371f242533e01678e9788db0d35bacda9c488e5

tech-stack:
  added: []
  patterns:
    - "Real-engine tests add only synthetic random-hash torrents and delete only their own hash in a finally; the test category is removed only if the test created it"
    - "Live probes print counts and never a name; the shared leak scan ends every subcommand"

key-files:
  created:
    - backend/tests/integration/test_real_downloads.py
  modified:
    - scripts/smoke.py
    - docs/setup.md

key-decisions:
  - "The list test asserts exactly one item with the synthetic torrent's id, not exactly one item overall, because the household's own downloads may be listed too"

requirements-completed: [DOWN-04, DOWN-05, DOWN-06, SEC-05, SEC-06]

coverage:
  - id: D1
    description: "Against real qBittorrent 5.2.4 a synthetic Film torrent appears in GET /api/downloads with the expected opaque id, a plain state and integer progress, and the raw row holds the fields the mapper reads with the expected types"
    requirement: "DOWN-04"
    verification:
      - kind: integration
        ref: "backend/tests/integration/test_real_downloads.py#test_a_film_torrent_is_listed_with_the_fields_the_mapper_reads"
        status: pass
    human_judgment: false
  - id: D2
    description: "DELETE /api/downloads/{id} of an in-progress torrent answers 204 and the torrent is gone from qBittorrent; a second DELETE answers 404; a torrent in another category is never listed and its id answers 404"
    requirement: "DOWN-05"
    verification:
      - kind: integration
        ref: "backend/tests/integration/test_real_downloads.py#test_an_in_progress_torrent_is_cancelled_through_the_portal"
        status: pass
      - kind: integration
        ref: "backend/tests/integration/test_real_downloads.py#test_a_torrent_outside_film_and_serietv_is_never_listed_or_cancelled"
        status: pass
    human_judgment: false
  - id: D3
    description: "smoke.py downloads checks the live list through Caddy (shape, 16-hex ids, states, progress 0-100, actions), prints only counts, and all requires at least one item after its download step"
    requirement: "DOWN-04"
    verification:
      - kind: command
        ref: "python3 scripts/smoke.py --base http://127.0.0.1 downloads"
        status: pass
      - kind: command
        ref: "python3 scripts/smoke.py --base http://127.0.0.1 all"
        status: pass
    human_judgment: false
  - id: D4
    description: "The phase gate on the rebuilt stack: backend, infra and frontend suites, stack up, doctor, smoke all/cache/downloads with OK no-leaks"
    requirement: "SEC-05"
    verification:
      - kind: command
        ref: "uv run --project backend --frozen pytest backend/tests infra/tests -q (699 passed); npm --prefix frontend test (241 passed); doctor (0 FAIL); smoke all, cache, downloads (OK no-leaks)"
        status: pass
    human_judgment: false
  - id: D5
    description: "docs/setup.md tells the admin how the list, cancel and remove, rate limits, audit log and phone updates behave, with no private address or secret"
    requirement: "SEC-06"
    verification:
      - kind: unit
        ref: "infra/tests/test_repo_hygiene.py (67 infra tests passed after the docs change)"
        status: pass
    human_judgment: false
  - id: D6
    description: "Household phone check (follow with progress and time left, cancel and see it gone in qBittorrent, outage banner clears itself, plain-reload redeploy, rate-limit message, audit lines carry the phone address and no password) plus the two visual backstops: 200-character name at 320 px, and bar colours and Preparing animation on iOS Safari and Android Chrome"
    requirement: "DOWN-06"
    verification:
      - kind: manual
        ref: "Task 2 human-check, steps 1-8, collected into the phase UAT at end of phase"
        status: untested
    human_judgment: true
    rationale: "Needs a real phone on the LAN and real browsers; the executor cannot establish it. Not invented here."
---

# Phase 2 Plan 11: Phase close - real-engine tests, live list probe and admin guide Summary

**Opt-in real-qBittorrent tests of the downloads list and cancel, a `smoke.py downloads` probe through Caddy, and admin-guide sections for the list, rate limits, audit trail and phone updates; the full phase gate is green on a rebuilt stack.**

## Performance

- **Duration:** about 7 min
- **Tasks:** 2 (1 tracer, 1 auto)
- **Files:** 1 created, 2 modified

## Accomplishments

- `backend/tests/integration/test_real_downloads.py`: three tests on synthetic random-hash torrents. They pin the raw `torrents/info` field types the mapper reads, the opaque id and plain state in `GET /api/downloads`, the 204 / gone / 404 cancel sequence, and that a torrent in a non-Film/SerieTV category is never listed or cancelled. Each test deletes only its own hash in `finally`; the test category is removed only if the test created it.
- `scripts/smoke.py`: `run_downloads` and the `downloads` subcommand check status 200, an object with the single key `items`, exact seven item keys, 16-hex ids, known states, integer progress 0-100, action cancel/remove/null, and print `OK downloads-list (<n> items)` with a count only. `all` runs the same check after its download step and requires at least one item.
- `docs/setup.md`: sections Downloads list, Rate limits (with the household-wide shared-address caveat), Logs and audit trail (read, filter, rotation, one example line per kind, what the log contains, what is never written), Phones and new versions, plus the Troubleshooting row for the outage banner.

## Gate results (rebuilt stack, admin override then base stack)

- Backend and infra suites: 699 passed, 7 deselected (the integration tests). Frontend: 241 passed.
- Integration run against real qBittorrent 5.2.4 (`QBIT_TEST_URL=http://127.0.0.1:8088`): `7 passed in 16.93s`; the three new tests passed, not skipped.
- Without `QBIT_TEST_URL`: `7 skipped` (`QBIT_TEST_URL is not set`), so the guard stays opt-in.
- Doctor: 0 FAIL lines. Smoke `all`, `cache`, `downloads`: only OK lines, each ends `OK no-leaks`; `all` and `downloads` print `OK downloads-list (2 items)`.
- `git diff --exit-code -- backend/uv.lock frontend/package-lock.json`: clean.
- Extra check: none of `QBITTORRENT_PASS`, `SECRET_KEY`, `APP_PASS_HASH` or the portal password appears in `docker compose logs backend` (14 audit lines at the time).

## Deviations from Plan

None - plan executed exactly as written. The only judgement call: the list test asserts that exactly one item has the synthetic torrent's id rather than that the list holds exactly one item, so it also passes when the household has real downloads (the plan's "exactly one item" wording would fail on a stack with real downloads).

## Pending human check (end of phase)

`workflow.human_verify_mode` is `end-of-phase`, so the phone check of Task 2 (steps 1-8 and both backstops, recorded per browser) is for the phase UAT and has not been run. Two things to watch when the admin runs it:

- On this WSL2 dev host the audit lines show the Docker gateway address (`172.19.0.1`), not the caller's address. Step 8 ("lines carry the phone's address") will therefore show the gateway here; it is the documented household-wide caveat, and the Ubuntu Server box is where real addresses should appear.
- Deferred real-phone checks from 02-06 and 02-10 (48 px buttons, side-by-side confirm at 320 px, focus ring and tap feel) are covered by the same pass.

## Known Stubs

None.

## Threat Flags

None. The only new surface is the opt-in test file (synthetic torrents only) and docs using documentation-range addresses.

## Issues Encountered

None.

## Self-Check: PASSED

- backend/tests/integration/test_real_downloads.py: found
- scripts/smoke.py (`def run_downloads`): found
- docs/setup.md (four headings, one each): found
- Commits e8009ae and b371f24: found on the branch
