---
phase: 03-jellyfin-server-tv-playback-gate
plan: 02
subsystem: infra
tags: [env-config, dev-env, secrets, jellyfin, hygiene-tests]
status: complete

requires:
  - phase: 01-portal
    provides: .env.example template, scripts/dev_env.py, key-match and hygiene tests
provides:
  - .env.example group "Jellyfin (Phase 3)" with JELLYFIN_ADMIN_PASSWORD, JELLYFIN_HOUSEHOLD_PASSWORD, JELLYFIN_MAX_BITRATE_MBPS=60 and an empty TMDB_API_KEY
  - dev_env.py household password rule: 10 characters from a look-alike-free alphabet, typeable with a TV remote
  - key-match test with SCRIPT_KEYS and RESERVED_KEYS, still an exact set comparison
  - secret_like_offenders hygiene helper that accepts a change-me placeholder or an empty value only
affects: [03-03, phase-04-rename, phase-05-tv-app]

actuals:
  tokens: 1656
  tasks: 2
  commits: 3
plan_head_before: 6777052cfb24f3ed61973e17e955056ef9845aa5
commits: 3
plan_head_after: df091a0f98dcbb3e7177ab5aba9518b2f56ca349

tech-stack:
  added: []
  patterns:
    - "Key groups in .env.example are accounted for by name: Settings fields, COMPOSE_LEVEL_KEYS, SCRIPT_KEYS (read by scripts) or RESERVED_KEYS (read by a later phase)"
    - "Hygiene rule extracted into a pure function with teeth cases (secret_like_offenders)"

key-files:
  created: []
  modified:
    - .env.example
    - scripts/dev_env.py
    - backend/tests/test_config.py
    - infra/tests/test_repo_hygiene.py

key-decisions:
  - "Household password is 10 characters from abcdefghjkmnpqrstuvwxyz23456789 (about 49 bits); the admin password stays token_urlsafe(32) (D-94)"
  - "An empty value in a secret-like key is allowed in the template because it holds no secret; any other non-placeholder value is still an offender (D-93)"
  - "Jellyfin keys reach the backend container through env_file; accepted dev risk, allowlist deferred to Phase 5 (D-100)"

patterns-established:
  - "dev_env.py special-cases a key by name before the generic change-me branch"

requirements-completed: [JFIN-01, JFIN-03]

coverage:
  - id: D1
    description: "A missing JELLYFIN_HOUSEHOLD_PASSWORD becomes 10 look-alike-free characters, is never rewritten and never printed"
    requirement: "JFIN-01"
    verification:
      - kind: unit
        ref: "backend/tests/test_config.py#test_dev_env_makes_the_household_password_short_and_readable"
        status: pass
      - kind: unit
        ref: "backend/tests/test_config.py#test_dev_env_never_rewrites_an_existing_household_password"
        status: pass
      - kind: unit
        ref: "backend/tests/test_config.py#test_dev_env_output_names_keys_only_never_the_household_password"
        status: pass
    human_judgment: false
  - id: D2
    description: "The admin gets a 43-character secret that differs from the household one; empty TMDB_API_KEY and JELLYFIN_MAX_BITRATE_MBPS=60 are copied and --check passes"
    requirement: "JFIN-01, JFIN-03"
    verification:
      - kind: unit
        ref: "backend/tests/test_config.py#test_dev_env_gives_the_admin_a_long_secret_that_differs_from_the_household_one"
        status: pass
      - kind: unit
        ref: "backend/tests/test_config.py#test_dev_env_copies_an_empty_tmdb_key_and_the_bitrate_and_check_passes"
        status: pass
    human_judgment: false
  - id: D3
    description: "Every .env.example key is accounted for by an exact set comparison, and every committed secret-like value is a placeholder or empty"
    requirement: "JFIN-01"
    verification:
      - kind: unit
        ref: "backend/tests/test_config.py#test_env_example_keys_match_the_settings_fields_exactly"
        status: pass
      - kind: unit
        ref: "infra/tests/test_repo_hygiene.py#test_secret_like_offenders_accepts_only_a_placeholder_or_an_empty_value"
        status: pass
      - kind: unit
        ref: "infra/tests/test_repo_hygiene.py#test_secret_like_example_values_are_placeholders"
        status: pass
    human_judgment: false
---

# Phase 3 Plan 02: Jellyfin configuration contract Summary

The Jellyfin keys now exist in `.env.example`, and `dev_env.py` generates the household password so it can be typed with a TV remote: 10 characters from a 31-character alphabet with no i, l, o, 0 or 1. The tests keep every key accounted for and every committed secret-like value a placeholder or empty.

**Started:** 2026-10-25T20:54:20Z | **Completed:** 2026-10-25T20:57:31Z | **Duration:** 3 min | **Tasks:** 2 | **Files:** 4

## Accomplishments

- `.env.example` has the group "Jellyfin (Phase 3)": `JELLYFIN_ADMIN_PASSWORD` and `JELLYFIN_HOUSEHOLD_PASSWORD` as change-me placeholders, `JELLYFIN_MAX_BITRATE_MBPS=60`, and an empty opt-in `TMDB_API_KEY`. A comment states that the backend still receives the whole file through env_file (D-100).
- `scripts/dev_env.py` gained `HOUSEHOLD_KEY`, `HOUSEHOLD_ALPHABET`, `HOUSEHOLD_LENGTH` and `make_household_password()`. Output still names keys only.
- `backend/tests/test_config.py` gained `SCRIPT_KEYS` and `RESERVED_KEYS` (still an exact set comparison) and five dev_env tests.
- `infra/tests/test_repo_hygiene.py` gained `secret_like_offenders(lines)` with four teeth cases.
- The local env file (gitignored, mode 600) now holds the four keys; values were checked by shape and never printed.

## Task Commits

1. Task 1 (tracer): `217cd8f` feat(03-02): generate a short readable Jellyfin household password from the template
2. Task 2 RED: `212ffea` test(03-02): add failing tests for the admin password, bitrate and TheMovieDb slot
3. Task 2 GREEN: `df091a0` feat(03-02): add the admin password, bitrate limit and opt-in TheMovieDb slot to the template

## RED and GREEN evidence

**Task 1 (tracer) RED**, `uv run --project backend --frozen pytest backend/tests/test_config.py -q`: `2 failed, 44 passed`.
- `test_env_example_keys_match_the_settings_fields_exactly` failed because `SCRIPT_KEYS` named a key not yet in `.env.example`.
- `test_dev_env_makes_the_household_password_short_and_readable` failed on `assert 43 == 10` (the generic change-me branch gave a 43-character secret).
- Semantic assessment: both failed on the planned assertion for the intended reason. The other two household tests passed at RED because they pin behavior the generic branch already had (existing key kept, key names only in output).
- Tracer feedback gate: the tracer `<verify>` was re-run after GREEN (75 passed, `--check` exit 0, household value 10 characters from the alphabet) and passed, so expansion went ahead. The Task 1 RED was not committed on its own; the plan marks it a tracer, so RED and GREEN went into one commit.
- `dev_env.py` output after GREEN: `added: JELLYFIN_HOUSEHOLD_PASSWORD`.

**Task 2 RED** (commit `212ffea`): `5 failed, 76 passed`.
- The key-match test failed: three `SCRIPT_KEYS` and one `RESERVED_KEYS` key were missing from `.env.example`.
- Four `secret_like_offenders` cases failed with `NameError: name 'secret_like_offenders' is not defined`.
- Semantic assessment: the target tests executed and failed because the planned symbol and keys did not exist. The two new dev_env tests for the admin secret and the empty TMDB key passed at RED because the generic change-me and copy branches already do that. They stay as regression guards for D-94 and D-93.
- `gsd_run check tdd-red-evidence` was not run: the plan is `type: execute` (not `type: tdd`) and the cases are format-agnostic pytest failures captured above.

**Task 2 GREEN** (commit `df091a0`): `uv run --project backend --frozen pytest backend/tests infra/tests -q` gives `1137 passed, 19 deselected`. `dev_env.py` printed `added: JELLYFIN_ADMIN_PASSWORD, JELLYFIN_MAX_BITRATE_MBPS, TMDB_API_KEY`; `--check` exit 0; `stat -c %a .env` prints 600.

## Acceptance criteria

All passed: `JELLYFIN_HOUSEHOLD_PASSWORD=change-me` count 1, `HOUSEHOLD_KEY` count 2, `SCRIPT_KEYS` count 2, `.env` mode 600, `JELLYFIN_ADMIN_PASSWORD=change-me` count 1, `JELLYFIN_MAX_BITRATE_MBPS=60` count 1, `TMDB_API_KEY=` line count 1, `RESERVED_KEYS` count 2, `def secret_like_offenders` count 1.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Lint violation in the new helper**
- **Found during:** Task 2 GREEN
- **Issue:** The first version of `secret_like_offenders` nested two `if` statements, which ruff flags as SIM102.
- **Fix:** Combined them into one condition via a `secret_like` local.
- **Files modified:** infra/tests/test_repo_hygiene.py
- **Commit:** df091a0

**Total deviations:** 1 auto-fixed (1 lint). **Impact:** none on behavior.

## Deferred Issues

`ruff check infra` reports two pre-existing violations in `infra/tests/test_compose_invariants.py` (lines 287 and 289). They are outside this plan's files and outside the plan's ruff scope (`backend scripts/dev_env.py`, which passes). Not touched.

## Known Stubs

None. `TMDB_API_KEY=` is an intentionally empty opt-in slot (D-93); Phase 4 reads it.

## Threat Flags

None. No new endpoint, auth path or file access. T-03-31 mitigated: a test asserts neither generated password is in stdout, the hygiene rule refuses committed non-placeholder secret-like values, and the local env file stays gitignored and mode 600. T-03-06 accepted per D-100.

## Authentication Gates

None.

## Verification

- `uv run --project backend --frozen pytest backend/tests infra/tests -q`: 1137 passed, 19 deselected.
- `dev_env.py --check` on the local env file: exit 0.
- No container was started, stopped or rebuilt. The live proof that the backend still starts with the longer env file is the backend doctor in plan 03-03 Task 1.

## Next

Ready for 03-03 (provisioning script reads `SCRIPT_KEYS`).

## Self-Check: PASSED

All four modified files exist; commits `217cd8f`, `212ffea`, `df091a0` are ancestors of HEAD.
