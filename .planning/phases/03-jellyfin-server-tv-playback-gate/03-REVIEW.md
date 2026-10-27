---
phase: 03-jellyfin-server-tv-playback-gate
reviewed: 2026-10-27T00:00:00Z
depth: standard
files_reviewed: 24
files_reviewed_list:
  - .env.example
  - .gitignore
  - docker-compose.yml
  - web/Caddyfile
  - scripts/init-host-dirs.sh
  - scripts/dev_env.py
  - scripts/jellyfin_setup.py
  - scripts/make_compat_clips.py
  - scripts/name_scan.py
  - scripts/name_scan_sample.json
  - scripts/tv_gate.py
  - backend/tests/test_compat_clips_contract.py
  - backend/tests/test_config.py
  - backend/tests/test_jellyfin_setup_contract.py
  - backend/tests/test_name_scan_contract.py
  - backend/tests/test_tv_gate_contract.py
  - infra/tests/test_caddyfile.py
  - infra/tests/test_compose_invariants.py
  - infra/tests/test_docs_contract.py
  - infra/tests/test_repo_hygiene.py
  - docs/setup.md
  - docs/tv-compatibility.md
  - docs/naming-scan.md
  - docs/ports-and-media.md
findings:
  critical: 0
  warning: 8
  info: 7
  total: 15
status: issues_found
---

# Phase 3: Code Review Report

**Reviewed:** 2026-10-27
**Depth:** standard
**Files Reviewed:** 24
**Status:** issues_found

## Summary

Reviewed the Jellyfin service, Caddy route, host-folder script, the four helper scripts and the docs. The compose hardening (read-only root, cap_drop, no published port, no env_file) and the Caddy CSP split hold up. No secret is printed or put in a URL. No injection path was found: ffmpeg runs by argument list, clip paths pass through `safe_component` plus an `_inside` check, and sources are sha256-pinned.

The defects cluster in the two interactive and stateful tools (`tv_gate.py watch`, `name_scan.py report/run`), where a normal operator action can silently lose recorded data. There is also one wrong command in the docs. No BLOCKER was proven, so `critical` is 0.

No structural (fallow) findings or external reviewer evidence were provided.

## Warnings

### WR-01: `watch` prompt takes type-ahead as the answer; `yy` saves no answer, silently (known issue, confirmed)

**File:** `scripts/tv_gate.py:812-818` (called from `record_play`, line 833-834)
**Issue:** `ask_ok()` calls `input()` on a stdin that has been buffering keystrokes the whole time the poll loop ran. The prompt reads the whole buffered line, so anything typed before the prompt appears becomes the answer. `yy`, `y ` or `yes!` fail the exact-match `dict.get(answer)` and return `None`. The row is then stored with `ok: null`, with no message. Because `verdict_of` treats a missing answer on a gating row as `INCOMPLETE`, the operator only finds out at the end, after replaying the clip. A typo such as `yse` is also treated as "skip". The prompt text says "Enter to skip", but an unrecognised input is not the same as an Enter.
**Fix:**
```python
import sys, termios

def _drain_stdin() -> None:
    if sys.stdin.isatty():
        termios.tcflush(sys.stdin, termios.TCIFLUSH)

def ask_ok() -> str | None:
    _drain_stdin()                      # discard keystrokes typed during playback
    while True:
        try:
            raw = input("Picture and sound OK? [y/n, Enter to skip] ").strip().lower()
        except EOFError:
            return None
        if raw == "":
            return None
        if raw in ANSWERS:
            return ANSWERS[raw]
        print("  type y, n, or just Enter to skip")
```
Print the recorded answer (`recorded: yes`) so a mis-key is visible.

### WR-02: Ctrl-C at the prompt discards the play being answered

**File:** `scripts/tv_gate.py:865-872`
**Issue:** The module docstring says "Ctrl-C saves and exits 0". But `tracker.observe()` has already removed the finished entries from `tracker.active`. If Ctrl-C arrives while `input()` is waiting inside `record_play`, `KeyboardInterrupt` unwinds out of the `for entry in finished` loop before `store.add`. The `except KeyboardInterrupt` branch only calls `tracker.finish_all()`, which sees the still-active plays, not the popped ones. The play being answered is lost, and so are any other entries later in `finished`. The `return 1` path at lines 855-857 (Jellyfin stops answering) also drops every in-progress play without saving it.
**Fix:** Make recording interrupt-safe. Store the entry before asking, then update the answer:
```python
finalize(entry, ...); store.add(entry["row"], entry); store.save()
if prompt:
    try:
        entry["ok"] = ask_ok()
    except KeyboardInterrupt:
        entry["ok"] = None
        raise
    finally:
        store.save()   # entry is the same dict object only if add() stores it, not a clean_entry copy
```
Note that `ResultStore.add` stores `clean_entry(entry)`, a copy, so keep a reference to the stored dict and mutate that one. In the `return 1` branch, call `tracker.finish_all()` and `record_play(..., prompt=False)` before returning.

### WR-03: A corrupt `results.json` is silently treated as empty and then overwritten

**File:** `scripts/tv_gate.py:314-317`
**Issue:** `except (FileNotFoundError, ValueError): raw = {}` swallows a JSON syntax error. The next `store.save()` (any recorded play, or `forget`) atomically replaces the file with only the new data. All earlier real-TV results are gone. A hand edit that leaves a trailing comma is enough to trigger this. These results come from a physical TV session, so they are costly to collect again. The same silent-empty behaviour feeds `render`, `verdict` and `forget`, so `verdict` would also report INCOMPLETE with no hint why.
**Fix:** Only `FileNotFoundError` means "start empty". On `ValueError`, raise `Fail("results", f"{path.name} is not valid JSON; fix or move it")`, or move the bad file to `results.json.bad` before starting fresh.

### WR-04: `name_scan.py report` can overwrite the committed real result and decision; a sample `run` clobbers real results

**File:** `scripts/name_scan.py:772-775`, `898-909`, `548-556`
**Issue:** Three things combine.
1. `cmd_run` always writes `RESULTS`, even for the synthetic sample, so a sample run after the real run replaces the real `results.json`.
2. `cmd_report` then sets `real = None` ("the last run was the synthetic sample") and renders "Not run yet." for the real section.
3. With no `--decision`, `render_report` writes `PENDING_DECISION` over the Decision section.

The default `report --out` is the committed `docs/naming-scan.md`. That file currently holds the real counts (20/26) and the NAME-01 decision. Running `run` on the sample and then `report`, which is exactly the documented flow, wipes both from the working tree and loses the per-name evidence in `jellyfin/name-scan/results.json`.
**Fix:** Write the sample run only to `SAMPLE_RESULTS` (and `TABLE`), and keep `RESULTS` real-only. Make `report` keep the existing Decision section when `--decision` is not given, by parsing it back from `args.out`. Refuse to replace a real section with "Not run yet." when the file already has one.

### WR-05: Troubleshooting row tells the admin to restart a service that does not exist

**File:** `docs/setup.md` (Troubleshooting table row "Jellyfin page is blank or has no styles")
**Issue:** The fix ends with `docker compose up -d --wait caddy`. The compose service is named `web` (`docker-compose.yml:168`). The command fails with "no such service: caddy", so the documented recovery for a bad CSP header does not work for a non-technical admin.
**Fix:** Change it to `docker compose up -d --build --wait web`. `infra/tests/test_docs_contract.py` should assert that every `docker compose ... <service>` named in the docs is a real service.

### WR-06: A long single-file torrent name loses its extension and aborts the whole scan

**File:** `scripts/name_scan.py:180-191` (and `safe_component`, 168-177)
**Issue:** For a name ending in a video extension, `layout()` returns `safe_component(name)` with no `reserve`. `safe_component` cuts at 200 UTF-8 bytes. A scene-style name of 201 to 255 bytes ending `.mkv` loses its extension. ffmpeg then cannot pick an output format from the file name and exits non-zero. `build_raw` turns that into `Fail("ffmpeg", "a clip could not be written")`, so one long real name aborts `run` for the whole corpus. The same applies to `inner`. The folder case already reserves 4 bytes.
**Fix:** Split the suffix before truncating:
```python
if name.lower().endswith(VIDEO_EXTS):
    stem, ext = os.path.splitext(name)
    return Path(root) / (safe_component(stem, reserve=len(ext.encode())) + ext)
```
Do the same for `inner`.

### WR-07: `jellyfin/config` (database, password hashes, access tokens) is created group-writable and world-readable

**File:** `scripts/init-host-dirs.sh:59-64` (dirs at 38-39)
**Issue:** Every directory gets `0775`; only `rejected` gets `0700`. `jellyfin/config` holds `jellyfin.db` with user password hashes and API/access tokens, including the admin's. `.gitignore` itself calls it "database, tokens". Jellyfin runs as `PUID` and creates files with the default umask, so any other local user on the Ubuntu Server host (or any WSL user) can read them. The same applies to `jellyfin/config/config` and `jellyfin/cache`.
**Fix:** Treat `jellyfin/config` like `rejected`:
```bash
case "$d" in
  "$DATA_ROOT/rejected"|jellyfin/config|jellyfin/config/config) $SUDO chmod 0700 "$d" ;;
  *) $SUDO chmod 0775 "$d" ;;
esac
```
`tv_gate.py` and `jellyfin_setup.py` read `jellyfin/config/log` and `jellyfin/config/metadata` as the same user as `PUID`, so `0700` keeps them working. If the repo owner differs from `PUID`, document that.

### WR-08: Jellyfin is served from the portal's origin with `script-src 'unsafe-inline'`

**File:** `web/Caddyfile:43-46`
**Issue:** `/jellyfin/*` shares an origin with the portal (D-04). Its CSP allows inline script, and jellyfin-web renders TheMovieDb text (titles, plots) and file names derived from torrent names. An XSS in Jellyfin therefore runs on the portal's origin, where `connect-src 'self'` and the portal CSP do not apply. It can call `/api/*` with the household's session cookie (SameSite does not stop same-origin requests) and queue downloads, read the downloads list, and so on. This is an inherent cost of the single-origin choice, and the `'unsafe-inline'` loosening is documented. The consequence for the portal session is not written down anywhere.
**Fix:** Record this risk next to the CSP. Optionally set the portal session cookie `Path=/api` so Jellyfin script cannot send it, or serve Jellyfin from a second port or hostname. If kept as is, add a regression test that no `Set-Cookie` from the portal is scoped to `/jellyfin`.

## Info

### IN-01: Dead `HEALTHCHECK_URL` environment variable

**File:** `docker-compose.yml:139-140`
**Issue:** The comment says the image's own healthcheck reads this. The service defines its own `healthcheck.test` at line 159, which replaces the image's healthcheck, so the variable is never read.
**Fix:** Remove it, or drop the compose healthcheck and rely on the image's.

### IN-02: `read_env_value` and `read_env_optional` are unused in `jellyfin_setup.py`

**File:** `scripts/jellyfin_setup.py:180-192`
**Issue:** No caller exists in `jellyfin_setup.py`, `tv_gate.py`, `name_scan.py` or the tests (`smoke.py` has its own copies). Extra blank lines at 617-620.
**Fix:** Delete both functions and the stray blank lines.

### IN-03: `_load()` helper duplicated, and shared modules loaded several times

**File:** `scripts/tv_gate.py:68-74`, `scripts/name_scan.py:70-76`
**Issue:** Identical helpers. Each script loads its own copy of `jellyfin_setup` and `make_compat_clips` under a different module name, so `Fail` classes differ between scripts. Catching one script's `Fail` in another would silently miss.
**Fix:** Put `_load` in one place, or make `scripts/` importable and use plain imports.

### IN-04: Smaller robustness gaps in `jellyfin_setup.py`

**File:** `scripts/jellyfin_setup.py:116-149, 924-929, 953-960`
**Issue:**
- `bitrate_cap(float("inf"))` raises `OverflowError`, which `cmd_cap` does not catch (it only catches `ValueError`), so `cap --mbps inf` prints a traceback.
- `urllib.request.build_opener` honours `http_proxy`. With a proxy set and no `no_proxy` entry for the host, the admin and household passwords and the tokens go to that proxy. The compose healthcheck already uses `--noproxy` for the same reason.
- `http.client.IncompleteRead` and `BadStatusLine` are not `OSError`, so they escape `main` as tracebacks.
- Disk-full or permission errors raised while saving results elsewhere are reported as `FAIL connect: OSError`, which is misleading.

**Fix:** Catch `(ValueError, OverflowError)` in `cmd_cap`. Build the opener with `urllib.request.ProxyHandler({})`. Catch `http.client.HTTPException` in `main`.

### IN-05: Admin tokens are created on every run and never revoked

**File:** `scripts/tv_gate.py:640-644`, `scripts/jellyfin_setup.py:275-286`
**Issue:** `watch`, `selftest`, `setup` and `check` each sign in as admin and never call `/Sessions/Logout`. Valid admin tokens accumulate in Jellyfin's device list until the config is reset.
**Fix:** Log out in a `finally` at the end of each command, or reuse one device token.

### IN-06: Caddy details

**File:** `web/Caddyfile:22, 59-63`
**Issue:** `redir /jellyfin /jellyfin/ 308` drops any query string. The site-level `header` block (nosniff, no-referrer, X-Frame-Options) does not apply inside `handle_errors`, so the "Jellyfin is not available" response and all other error responses go out without these headers. The plain-text reply is also served with an inferred content type.
**Fix:** Keep the redirect query by redirecting to `/jellyfin/?{query}` only when a query is present (or accept the loss, since the entry URL has none). Repeat the three headers, and `Content-Type text/plain`, inside `handle_errors`.

### IN-07: Other low-risk observations

**File:** `scripts/init-host-dirs.sh:71-85`, `.env.example:~108-112`, `scripts/tv_gate.py:144`
**Issue:**
- The script prints `network.xml kept` whenever the file exists. If Jellyfin ever started with an empty BaseUrl (for example, it ran before this script was updated), `/jellyfin` stays broken and the script says nothing. It could grep the file for `<BaseUrl>/jellyfin</BaseUrl>` and warn.
- The Jellyfin admin password is visible inside the backend container through `env_file`. It is documented as accepted (D-100), but the backend sits on the `edge` network next to Caddy, which proxies `/jellyfin`, so the credential is reachable from the exposed process.
- The `IPV4` privacy regex also matches any four-part dotted version, for example `10.11.0.1`, so `validate` would reject a Jellyfin version string in that shape.

**Fix:** Warn on a wrong BaseUrl. Consider a separate env file for the script-only keys. Narrow the `IPV4` check to octets 0-255 and let versions through when the line starts with `Jellyfin version tested:`.

---

_Reviewed: 2026-10-27_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
