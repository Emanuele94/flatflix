# Phase 3: Jellyfin Server & TV Playback Gate - Pattern Map

**Mapped:** 2026-10-25
**Files analyzed:** 17 new/modified
**Analogs found:** 15 / 17 (all analog paths verified git-tracked via `git ls-files`)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `docker-compose.yml` (add `jellyfin` service, `jellyfin` network, web `networks`) | config | request-response | `docker-compose.yml` `sandbox` + `qbittorrent` services | exact |
| `web/Caddyfile` (replace `/jellyfin/*` stub, scope CSP, `handle_errors`) | config | request-response | `web/Caddyfile` itself (`/api/*`, `/assets/*` blocks) | exact |
| `scripts/init-host-dirs.sh` (jellyfin dirs + seeded `network.xml`) | utility | file-I/O | `scripts/init-host-dirs.sh` itself | exact |
| `.env.example` (household password, `TMDB_API_KEY`, Jellyfin admin keys) | config | - | `.env.example` itself | exact |
| `scripts/dev_env.py` (short readable household password rule) | utility | transform | `scripts/dev_env.py` (`make_dev_login_hash`, placeholder rule) | exact |
| `.gitignore` (`jellyfin/`, `corpus.json`) | config | - | `.gitignore` itself | exact |
| `scripts/jellyfin_setup.py` | utility (provisioning) | request-response | `scripts/smoke.py` (Probe, Fail, env readers, argparse main) | role-match |
| `scripts/make_compat_clips.py` | utility | batch / file-I/O | `scripts/make_probe_fixtures.py` | exact |
| `scripts/tv_gate.py` | utility (poller) | event-driven (polling) | `scripts/smoke.py` (`follow_to_ready` poll loop) | role-match |
| `scripts/name_scan.py` | utility | batch | `scripts/smoke.py` (`search_flow`) + `make_probe_fixtures.py` (clips) | role-match |
| `backend/tests/test_jellyfin_scripts_contract.py` | test | transform | `backend/tests/test_smoke_contract.py` | exact |
| `infra/tests/test_compose_invariants.py` (modify) | test | - | itself (`check_sandbox`, `test_qbittorrent_and_web_share_no_network`) | exact |
| `infra/tests/test_caddyfile.py` (new) | test | - | `test_compose_invariants.py` `_caddy_handle_blocks` tests | role-match |
| `infra/tests/test_docs_contract.py` (new) | test | - | `infra/tests/test_repo_hygiene.py` (text scans over tracked files) | role-match |
| `backend/app/tools/doctor.py` (optional Jellyfin reachability check) | utility | request-response | `doctor.py` `sandbox_checks` / `collect` | role-match |
| `docs/ports-and-media.md`, `docs/setup.md` (modify) | doc | - | existing sections in each | exact |
| `docs/tv-compatibility.md` | doc | - | none (format defined by UI-SPEC) | no analog |

## Pattern Assignments

### `docker-compose.yml` jellyfin service (config, request-response)

**Analog:** the `sandbox` service (hardening) and `qbittorrent` service (bind mounts, healthcheck), `docker-compose.yml`.

**Hardening block to copy** (sandbox, lines 90-97):
```yaml
    read_only: true
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
    pids_limit: 64
    mem_limit: 768m
    tmpfs:
      - /run/fx:size=16m,mode=0700,uid=10002,gid=10002
      - /tmp:size=8m
```
Jellyfin uses `pids_limit: 512`, `tmpfs: ["/tmp:size=64m"]`, no `mem_limit` unless planner decides (RESEARCH Pattern 1).

**Run-as-owner + bind pattern** (backend line 49, qbittorrent lines 28-32):
```yaml
    user: "${PUID:-1000}:${PGID:-1000}"
    volumes:
      - type: bind
        source: ${DATA_ROOT:-./data}
        target: /data
        bind:
          create_host_path: false
```
Use this long syntax for `./jellyfin/config`, `./jellyfin/cache`, and `./jellyfin/scratch` (add `read_only: true`, as sandbox lines 105-110).

**Healthcheck, restart, logging** (sandbox lines 112-123):
```yaml
    healthcheck:
      test: [...]
      interval: 15s
      timeout: 5s
      retries: 6
      start_period: 10s
    restart: unless-stopped
    logging: *default-logging
```
Jellyfin: `start_period: 60s`, CMD-SHELL curl on `http://localhost:8096/jellyfin/health` (RESEARCH Pattern 1). Pin image `jellyfin/jellyfin:12.3.20261023-013714`.

**Network wiring** (lines 144-153): add `jellyfin: {}` (not internal, TMDb egress, comment style as `qbit`). Change `web` to `networks: [edge, jellyfin]`. Do NOT add `web depends_on jellyfin` (web already depends only on backend, lines 133-135).

**Do not copy:** sandbox `devices`, `group_add`, fixed uid 10002, `env_file`.

---

### `web/Caddyfile` (config, request-response)

**Analog:** `web/Caddyfile` itself.

**Replace the stub** (lines 30-33):
```caddy
	# Reserved: replaced by the Jellyfin reverse proxy in Phase 3.
	handle /jellyfin/* {
		respond "Not available yet" 404
	}
```
**Move the CSP out of the site-level `header`** (line 15) into `header @notjellyfin Content-Security-Policy "<same string>"` (RESEARCH Pitfall 1; byte-for-byte same value). Keep the other four headers (lines 11-14) site-level. Use the exact Caddyfile in RESEARCH Pattern 3 (verified), tab indentation as existing file.

**Keep `/api/*` block untouched** (lines 18-23, the `header_up X-Forwarded-For {remote_host}` line is asserted by `test_caddy_sets_forwarded_for_from_the_address_it_saw`).

**Placement constraint:** `handle_errors` must go before the final catch-all `handle {` (Pitfall 12), or tighten the helper regex.

---

### `scripts/init-host-dirs.sh` (utility, file-I/O)

**Analog:** itself.

**Dir list pattern** (lines 25-36): append `"jellyfin/config/config"`, `"jellyfin/cache"`, `"jellyfin/scratch/Movies"`, `"jellyfin/scratch/TV"`, `"jellyfin/scratch/Compat"`, `"jellyfin/scratch/Raw"`, `"jellyfin/tv-gate"` to `dirs=(...)`; the loop (lines 43-56) handles mkdir/chown/chmod with `$SUDO`.

**Env lookup helper** (lines 12-18): reuse `get KEY default`; never source `.env`.

**New block (after the loop, before the KVM check at line 58):** write `jellyfin/config/config/network.xml` only if absent, owned `PUID:PGID` (content in RESEARCH Pattern 2). Follow the `owner=$(stat ...)`/`$SUDO chown` idiom of lines 45-48. Keep `set -euo pipefail` and the `OK`/`FAIL` echo style (lines 58-67).

---

### `.env.example` + `scripts/dev_env.py` (config / utility)

**Analog:** `.env.example` (commented groups, `change-me-...` placeholders) and `scripts/dev_env.py`.

**Placeholder rule** (`dev_env.py` lines 86-89):
```python
        if key == HASH_KEY and value.startswith(PLACEHOLDER_PREFIX):
            value = make_dev_login_hash()
        elif value.startswith(PLACEHOLDER_PREFIX):
            value = secrets.token_urlsafe(32)
```
Add a branch for the household password key: short readable random value (RESEARCH Pitfall 10), e.g. `elif key == HOUSEHOLD_KEY ...`. Admin password keeps the generic 43-char `token_urlsafe(32)` path. `TMDB_API_KEY=` stays empty (copied as-is, template value does not start with `change-me`). Add a comment block per `.env.example` style. Note D-100: admin password visible in backend env is accepted.

**Credential file pattern** (lines 56-61, `os.open(..., O_EXCL, 0o600)`) if a password file is needed.

---

### `scripts/jellyfin_setup.py` (utility, request-response, idempotent)

**Analog:** `scripts/smoke.py`.

**Imports + constants** (lines 68-85): `from __future__ import annotations`, stdlib only (`argparse`, `json`, `sys`, `time`, `urllib.error`, `urllib.request`, `pathlib.Path`), `ROOT`, `ENV_FILE`, `TIMEOUT`.

**Fail/step_ok/expect** (lines 106-111, 187-193):
```python
class Fail(Exception):
    def __init__(self, step: str, reason: str) -> None:
        super().__init__(f"{step}: {reason}")
        self.step = step
        self.reason = reason

def expect(step: str, status: int, wanted: int) -> None:
    if status != wanted:
        raise Fail(step, f"expected HTTP {wanted}, got {status}")

def step_ok(step: str) -> None:
    print(f"OK {step}")
```

**HTTP client** (lines 113-148): `Probe` with `NoRedirect` handler, returns `(status, headers, body)`, catches `HTTPError` for status. Copy and swap the cookie jar for an `Authorization: MediaBrowser Token="..."` header (RESEARCH Pattern 4; `X-Emby-Token` returns 401 on 12.3).

**Env reading** (lines 151-178): `read_env_value` / `read_env_optional` by key lookup, never sourcing. Reuse verbatim; household/admin passwords come from here, never printed.

**main/exit-code shape** (lines 744-795): argparse subcommands (`setup`, `--check`), `except Fail` prints `FAIL step: reason` and returns 1, `except (URLError, OSError)` prints `FAIL connect: <TypeName>`. Idempotency gate: `GET /System/Info/Public` `StartupWizardCompleted`. `--check` asserts `GET /Users/Public == ["household"]`. Base default `http://127.0.0.1/jellyfin` (Caddy only, D-82).

**Leak discipline** (smoke `leak_markers`/`report_leaks`, lines 687-741): never print passwords or tokens.

---

### `scripts/make_compat_clips.py` (utility, batch/file-I/O)

**Analog:** `scripts/make_probe_fixtures.py` (exact role and flow).

**ffmpeg runner** (lines 29-38):
```python
def _ffmpeg(*args: str) -> None:
    exe = shutil.which("ffmpeg")
    if exe is None:
        raise MissingFfmpeg("host ffmpeg missing")
    subprocess.run(
        [exe, "-v", "error", "-y", *args],
        check=True, stdin=subprocess.DEVNULL, timeout=300,
    )
```
**Encoder capability probe** (lines 41-53, `_has("encoders", name)`): reuse to skip/flag missing `libx265`, `dca`, `eac3`. Raise `MissingFfmpeg`, return exit 3 (lines 129-140). Print file names and sizes only. Timeout must be raised for x265 10-bit (RESEARCH: ~12 s per 5 s clip; 60 s clips need a larger `timeout`).

**Differences:** row-ID file prefix (`A01...`), `-strict -2` for DTS, `-tag:v hvc1`, `-metadata:s:a:0 language=eng`, argument lists only (command shapes in RESEARCH Pattern 6). Output to `jellyfin/scratch/Compat/`, chmod 0644 / 0755 as lines 106, 123-125. PGS row is "not tested" (D-99): no clip.

---

### `scripts/tv_gate.py` (utility, polling)

**Analog:** `scripts/smoke.py` `follow_to_ready` (lines 610-642) for the poll loop, `fetch_items` (574-586) for shape-checked GET.

**Poll loop pattern:**
```python
    began = time.monotonic()
    seen: list[str] = []
    while True:
        items = fetch_items(probe)
        ...
        if time.monotonic() - began > ready_timeout:
            raise Fail("handoff", f"not ready after {int(ready_timeout)} s (last state {state})")
        time.sleep(HANDOFF_POLL_SECONDS)
```
Differences: poll at <= 1 s, keep last non-null `TranscodingInfo` per play session, read `jellyfin/config/log/FFmpeg.<Type>-*.log` filenames, pure classifier function `method(play_method, transcoding_info, ffmpeg_log_type)` (RESEARCH "Classifier") so it is unit-testable. Output `jellyfin/tv-gate/results.json` (gitignored); never record serial, device ID or ESN (D-89).

---

### `scripts/name_scan.py` (utility, batch)

**Analog:** `scripts/smoke.py` `search_flow` (293-339) to capture names via `/api/search`; `make_probe_fixtures.py` `_ffmpeg` for 1-second clips (`color` lavfi, 160x90). Reuse Probe/Fail/step_ok. Scan wait protocol per Pitfall 5 (`Key == "RefreshLibrary"`). Pure functions for `classify(truth, item)` -> `identified|unidentified|wrong title` and the D-92 bar (>= 90 %, zero wrong) so contract tests can exercise them. `corpus.json` is gitignored (D-101); commit a synthetic sample only.

---

### `backend/tests/test_jellyfin_scripts_contract.py` (test, transform)

**Analog:** `backend/tests/test_smoke_contract.py` (exact).

**Load-by-path fixture** (lines 7-22):
```python
SMOKE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "smoke.py"

@pytest.fixture(scope="module")
def smoke() -> ModuleType:
    spec = importlib.util.spec_from_file_location("flatflix_smoke", SMOKE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
```
Repeat per script (`jellyfin_setup`, `tv_gate`, `name_scan`, `make_compat_clips`). Test only pure parts: classifier, scan verdict, `read_env_*` via `monkeypatch.setattr(smoke, "read_env_optional", lambda key: value)` (lines 89), `pytest.mark.parametrize` tables (lines 82-85), `pytest.raises(mod.Fail)` with `caught.value.step`.

---

### `infra/tests/test_compose_invariants.py` (modify) and new `infra/tests/test_caddyfile.py`

**Analog:** `test_compose_invariants.py` itself.

**Must change:** `test_qbittorrent_and_web_share_no_network` (lines 200-205): `web` becomes `{"edge", "jellyfin"}`; add `_networks(services["jellyfin"]) == {"jellyfin"}` and "only web and jellyfin on `jellyfin`" (copy the shape of `test_the_sandbox_network_is_internal_and_shared_with_the_backend_only`, line 499).

**New Jellyfin hardening checker** (copy `check_sandbox` lines 372-428 returning a violations list, `_mutated` helper line 435 and parametrized "weakened entry is caught" at 494): assert `read_only`, `cap_drop == ["ALL"]`, no-new-privileges, `user` is `${PUID:-1000}:${PGID:-1000}`, no `ports`/`env_file`/`privileged`, scratch mount `read_only`, `create_host_path: false`, rotated logging, healthcheck, image pinned with exact tag.

**Already covers automatically:** `test_only_web_publishes_a_port` (173), `test_images_are_pinned...` (277; extend the endswith check), `test_every_service_rotates_its_logs` (355).

**Caddyfile tests** (analog `_caddy_handle_blocks`, lines 312-328; fix `startswith("handle")` to `re.match(r"handle(\s|\{)", stripped)` per Pitfall 12 so `handle_errors` is not a handle block): assert exactly one CSP-setting `header @notjellyfin`, the Jellyfin block contains `'wasm-unsafe-eval'` and `reverse_proxy jellyfin:8096`, the `redir /jellyfin /jellyfin/ 308` line, the 502 sentence, and that the catch-all (`blocks[-1]`, line 345) is still `handle {` (existing test lines 342-348).

---

### `infra/tests/test_docs_contract.py` (new, test)

**Analog:** `infra/tests/test_repo_hygiene.py` (ROOT discovery via `git rev-parse`, lines 24-31; `_git(...)` helper lines 15-21; text scanning of tracked files). Assert `docs/tv-compatibility.md` carries no serial / device ID / ESN markers and no dotted-quad LAN IPs (reuse `find_lan_ips`, line ~53; write addresses as `<laptop-ip>`), and that PROJECT.md links the doc. Check `.gitignore` covers `jellyfin/`.

---

### `backend/app/tools/doctor.py` (optional modify: Jellyfin reachability)

**Analog:** `doctor.py` `sandbox_checks` (line 147) / `Check = tuple[bool, str]` (line 47) / `line()` (50) / `run()` (346-366: append checks into the loop). Note backend is not on the `jellyfin` network (CONTEXT: backend need not reach it); if added, it must be a host-side script check or the planner must add the network. Prefer leaving doctor unchanged and putting the check in `jellyfin_setup.py --check`. Test analog: `backend/tests/test_doctor_sandbox.py` (Settings builder lines 26-40, names/counts only in output).

---

### `docs/ports-and-media.md`, `docs/setup.md` (modify)

**Analog:** existing tables/sections. Port map row (line 17): replace "reserved for Phase 3" text on both the `web` row (line 12) and the Jellyfin row (line 17: `| Jellyfin | 8096 | reserved for Phase 3 | ...`). Networks list (lines 47-60): add a `jellyfin` bullet in the same style ("web and jellyfin only, not internal because of TMDb egress"). `docs/setup.md`: add "## Jellyfin and the TV" near "Phone access" (line 114) or after "Safety check" (313); include DHCP reservation, mDNS ladder, Docker Desktop sign-in start (Pitfall 11).

---

## Shared Patterns

### Standard-library-only scripts with Fail/OK output
**Source:** `scripts/smoke.py` lines 68-111, 187-193, 744-795
**Apply to:** `jellyfin_setup.py`, `tv_gate.py`, `name_scan.py`, `make_compat_clips.py`
`OK <step>` lines, `FAIL <step>: <reason>` and exit 1, `FAIL connect: <ExcName>` on `URLError/OSError`, exit 2 for SKIP, secrets never printed, ffmpeg via argument lists with no shell.

### Env reading without sourcing
**Source:** `scripts/smoke.py` `read_env_value` / `read_env_optional` (lines 151-178); `scripts/init-host-dirs.sh` `get()` (lines 12-18)
**Apply to:** every new script that needs `.env` values.

### Pinned images, non-published ports, hardened container
**Source:** `docker-compose.yml` sandbox (lines 84-123) + `infra/tests/test_compose_invariants.py` `check_sandbox` (372-428)
**Apply to:** jellyfin service and its invariant test.

### Public-repo hygiene
**Source:** `infra/tests/test_repo_hygiene.py`
**Apply to:** all new docs and scripts: no LAN IPs (write `<laptop-ip>`), no secrets, no TV serial/device ID/ESN, generated media and `jellyfin/` never committed, real captured torrent names gitignored (D-101).

### Idempotent host setup
**Source:** `scripts/init-host-dirs.sh` (mkdir/chown/chmod loop, create-if-absent)
**Apply to:** `network.xml` seed and dirs.

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `docs/tv-compatibility.md` | doc | - | No existing matrix/verdict doc; use the template defined in 03-UI-SPEC.md (matrix rows, `## Address check`, verdict) |
| mDNS/avahi config (doc-only in `docs/setup.md`) | config | - | No host-networking config exists in the repo; use RESEARCH "mDNS and the stable address" and avahi snippet |

## Metadata

**Analog search scope:** repo root, `scripts/`, `web/`, `infra/tests/`, `backend/tests/`, `backend/app/tools/`, `docs/`
**Files scanned:** about 100 tracked files listed; 12 read
**Tracked-source gate:** all analog paths appear in `git ls-files`; no `.gsd/capabilities` mirror paths used
**Pattern extraction date:** 2026-10-25
