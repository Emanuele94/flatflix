#!/usr/bin/env python3
"""Provision and check the Jellyfin server through Caddy (standard library only).

Usage:
    python3 scripts/jellyfin_setup.py setup [--base URL] [--no-scan]
    python3 scripts/jellyfin_setup.py check [--base URL]
    python3 scripts/jellyfin_setup.py measure [--base URL] [--runs 3] [--size-mb 50]
    python3 scripts/jellyfin_setup.py cap --mbps N

`setup` is idempotent: every step reads the current state and posts only what differs, and prints
`OK <step> (created|changed|unchanged)`. A second run prints only `unchanged` lines. It runs the
first-run wizard (server name Flatflix, English UI and metadata, the admin account), makes the
shared household account (English audio, Smart English subtitles, two libraries only, no admin
powers), the hidden admin, the Movies and TV Series libraries over /scratch/Movies and
/scratch/TV, the bitrate limit and a library scan. Start Jellyfin
and run `setup --no-scan` on the same command line: until the wizard is complete anyone on the LAN
can open it (RESEARCH Pitfall 9). Running two setups at once is unsupported.

`check` writes nothing. It prints one `OK <step>` or `FAIL <step>: <reason>` line per step in the
fixed CHECK_STEPS order, collects every failure and exits 1 when there is any.

`measure` signs in as household and downloads the server's bitrate test file a few times; run it
from another wired computer on the LAN against http://<laptop-ip>/jellyfin (this file is
self-contained). It prints each run, the median and the cap that follows (floor of 70 percent of
the median, clamped to 20-80 Mbps, D-96). `cap --mbps N` prints the same cap for a link speed read
from the TV's network screen, with no network.

Rules (D-82): every request goes through Caddy at DEFAULT_BASE, never to Jellyfin's own port.
Jellyfin 12.3 accepts only `Authorization: MediaBrowser ... Token="..."`. The env file is read by
key lookup (never sourced). A password, an access token or a URL carrying one is never printed,
written or put in a URL. Failures print `FAIL <step>: <reason>`; a network error prints
`FAIL connect: <ExceptionName>`. Exit 1 on any failure.

Keys read from the env file: JELLYFIN_ADMIN_PASSWORD, JELLYFIN_HOUSEHOLD_PASSWORD and
JELLYFIN_MAX_BITRATE_MBPS.
"""

from __future__ import annotations

import argparse
import getpass
import json
import math
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
JELLYFIN_DIR = ROOT / "jellyfin"

DEFAULT_BASE = "http://127.0.0.1/jellyfin"
ADMIN_USER = "admin"
HOUSEHOLD_USER = "household"
SERVER_NAME = "Flatflix"
CLIENT = "flatflix-setup"
TIMEOUT = 30

ADMIN_KEY = "JELLYFIN_ADMIN_PASSWORD"
HOUSEHOLD_KEY = "JELLYFIN_HOUSEHOLD_PASSWORD"
BITRATE_KEY = "JELLYFIN_MAX_BITRATE_MBPS"

MOVIES_LIBRARY = "Movies"
MOVIES_PATH = "/scratch/Movies"
TV_LIBRARY = "TV Series"
TV_PATH = "/scratch/TV"
LIBRARIES = (
    (MOVIES_LIBRARY, "movies", MOVIES_PATH),
    (TV_LIBRARY, "tvshows", TV_PATH),
)
MOVIE_TITLES = (("Big Buck Bunny", 2008), ("Sintel", 2010), ("Tears of Steel", 2012))
SERIES_TITLE = "Pioneer One"
SERIES_EPISODES = (1, 2, 3)

MIN_MBPS = 20
MAX_MBPS = 80
MAX_TEST_MB = 60  # the server refuses very large bitrate-test sizes


class Fail(Exception):
    def __init__(self, step: str, reason: str) -> None:
        super().__init__(f"{step}: {reason}")
        self.step = step
        self.reason = reason


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return None


def auth_header(token: str | None) -> str:
    parts = f'MediaBrowser Client="{CLIENT}", Device="{CLIENT}", DeviceId="{CLIENT}", Version="1.0"'
    if token:
        parts += f', Token="{token}"'
    return parts


class Api:
    """Tiny Jellyfin client: JSON in and out, the token only in the Authorization header."""

    def __init__(self, base: str, token: str | None = None) -> None:
        self.base = base.rstrip("/")
        self.token = token
        self.opener = urllib.request.build_opener(NoRedirect())

    def request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, object] | None = None,
        body: object | None = None,
    ) -> tuple[int, object]:
        url = self.base + path
        if query:
            url += "?" + urllib.parse.urlencode(query, quote_via=urllib.parse.quote)
        headers = {"Authorization": auth_header(self.token), "Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with self.opener.open(req, timeout=TIMEOUT) as resp:
                status, kind, payload = resp.status, resp.headers.get("Content-Type", ""), resp.read()
        except urllib.error.HTTPError as exc:
            status, kind, payload = exc.code, exc.headers.get("Content-Type", ""), exc.read()
        if payload and "json" in kind.lower():
            try:
                return status, json.loads(payload)
            except ValueError:
                pass
        return status, payload

    def call(
        self,
        step: str,
        method: str,
        path: str,
        *,
        query: dict[str, object] | None = None,
        body: object | None = None,
        wanted: tuple[int, ...] = (200, 204),
    ) -> object:
        status, payload = self.request(method, path, query=query, body=body)
        if status not in wanted:
            raise Fail(step, f"expected HTTP {' or '.join(map(str, wanted))}, got {status}")
        return payload


def _lookup_env(key: str) -> str | None:
    if not ENV_FILE.exists():
        return None
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        if name.strip() == key:
            return value.strip().strip("'\"")
    return None


def read_env_value(key: str) -> str:
    """Look up KEY in the local env file without sourcing it; strips optional quotes."""
    if not ENV_FILE.exists():
        raise Fail("setup", "local env file missing: run scripts/dev_env.py")
    value = _lookup_env(key)
    if value is None:
        raise Fail("setup", f"{key} missing from the local env file: run scripts/dev_env.py")
    return value


def read_env_optional(key: str) -> str | None:
    """Like read_env_value, but a missing file or key is None."""
    return _lookup_env(key)


def _password(key: str) -> str:
    value = _lookup_env(key)
    if value is None or value == "" or value.startswith("change-me"):
        raise Fail("config", f"{key} is empty, missing or still the template placeholder")
    return value


def passwords() -> tuple[str, str]:
    """The admin and household passwords; both must be set and they must differ."""
    admin, household = _password(ADMIN_KEY), _password(HOUSEHOLD_KEY)
    if admin == household:
        raise Fail("config", f"{ADMIN_KEY} and {HOUSEHOLD_KEY} must be two different passwords")
    return admin, household


def step_ok(step: str, outcome: str | None = None) -> None:
    print(f"OK {step}" if outcome is None else f"OK {step} ({outcome})")


# --- bitrate (JFIN-03, D-96) ----------------------------------------------------------


def bitrate_cap(measured_mbps: float) -> int:
    """Floor of 70 percent of a measured speed in whole Mbps, clamped to 20-80 (RESEARCH Pitfall 6)."""
    if measured_mbps <= 0:
        raise ValueError("a measured speed must be above zero")
    return max(MIN_MBPS, min(MAX_MBPS, math.floor(measured_mbps * 7 / 10)))


def bitrate_bps(raw: str) -> int:
    """JELLYFIN_MAX_BITRATE_MBPS (a whole number, 20-80) as bits per second, the API's unit (A3)."""
    text = raw.strip()
    if not (text.isascii() and text.isdigit()) or not MIN_MBPS <= int(text) <= MAX_MBPS:
        raise Fail(
            "config", f"{BITRATE_KEY} must be a whole number from {MIN_MBPS} to {MAX_MBPS}"
        )
    return int(text) * 1_000_000


def configured_bps() -> int:
    return bitrate_bps(_lookup_env(BITRATE_KEY) or "")


# --- wizard and sign-in ---------------------------------------------------------------


def wizard_completed(api: Api) -> bool:
    info = api.call("wizard", "GET", "/System/Info/Public")
    if not isinstance(info, dict):
        raise Fail("wizard", "unexpected answer from /System/Info/Public")
    return bool(info.get("StartupWizardCompleted"))


def run_wizard(api: Api, admin_password: str) -> bool:
    """First-run wizard in the order verified in RESEARCH Pattern 4; True when it ran."""
    if wizard_completed(api):
        return False
    api.call(
        "wizard",
        "POST",
        "/Startup/Configuration",
        body={
            "ServerName": SERVER_NAME,
            "UICulture": "en-US",
            "MetadataCountryCode": "US",
            "PreferredMetadataLanguage": "en",
        },
    )
    api.call("wizard", "GET", "/Startup/User")  # must be read before it is written
    api.call(
        "wizard",
        "POST",
        "/Startup/User",
        body={"Name": ADMIN_USER, "Password": admin_password},
    )
    api.call("wizard", "POST", "/Startup/RemoteAccess", body={"EnableRemoteAccess": True})
    api.call("wizard", "POST", "/Startup/Complete")
    return True


def login(api: Api, user: str, password: str, *, step: str = "login") -> tuple[str, str]:
    """Sign in by name; returns (access token, user id)."""
    status, payload = api.request(
        "POST", "/Users/AuthenticateByName", body={"Username": user, "Pw": password}
    )
    if status != 200 or not isinstance(payload, dict):
        raise Fail(step, f"expected HTTP 200, got {status}")
    token = payload.get("AccessToken")
    user_id = (payload.get("User") or {}).get("Id")
    if not token or not user_id:
        raise Fail(step, "the answer has no access token")
    return str(token), str(user_id)


RESET_HINT = (
    "the admin password in the env file does not open Jellyfin; someone else may have completed "
    "the first-run wizard: see docs/setup.md, Reset Jellyfin"
)


def admin_api(base: str) -> tuple[Api, str]:
    """Run the wizard when it is open, then sign in as admin; returns (client, admin user id)."""
    admin_password, _ = passwords()
    anonymous = Api(base)
    ran = run_wizard(anonymous, admin_password)
    attempts = 3 if ran else 1
    for attempt in range(attempts):
        try:
            token, user_id = login(anonymous, ADMIN_USER, admin_password, step="admin-login")
        except Fail:
            if attempt + 1 < attempts:
                time.sleep(1.0 + attempt)  # Jellyfin needs a moment after the wizard
                continue
            raise Fail(
                "admin-login",
                "sign-in right after the wizard failed" if ran else RESET_HINT,
            ) from None
        return Api(base, token), user_id
    raise Fail("admin-login", RESET_HINT)  # not reached; keeps the return type honest


# --- users ----------------------------------------------------------------------------


def find_user(api: Api, name: str) -> dict | None:
    users = api.call("users", "GET", "/Users")
    if not isinstance(users, list):
        raise Fail("users", "unexpected answer from /Users")
    return next((u for u in users if u.get("Name") == name), None)


def password_works(base: str, name: str, password: str) -> bool:
    status, _ = Api(base).request(
        "POST", "/Users/AuthenticateByName", body={"Username": name, "Pw": password}
    )
    return status == 200


def ensure_user(api: Api, name: str, password: str) -> tuple[str, str]:
    """Create the user or check its password; returns (user id, created|unchanged|password reset)."""
    existing = find_user(api, name)
    if existing is None:
        made = api.call(
            "household", "POST", "/Users/New", body={"Name": name, "Password": password}
        )
        if not isinstance(made, dict) or not made.get("Id"):
            raise Fail("household", "the new user has no id")
        return str(made["Id"]), "created"
    user_id = str(existing["Id"])
    if password_works(api.base, name, password):
        return user_id, "unchanged"
    # An admin can clear a password and then set a new one without knowing the old one.
    api.call(
        "household", "POST", f"/Users/{user_id}/Password", body={"ResetPassword": True}
    )
    api.call(
        "household",
        "POST",
        f"/Users/{user_id}/Password",
        body={"CurrentPw": "", "NewPw": password},
    )
    return user_id, "password reset"


def get_user(api: Api, user_id: str) -> dict:
    user = api.call("users", "GET", f"/Users/{user_id}")
    if not isinstance(user, dict):
        raise Fail("users", "unexpected answer from /Users/{id}")
    return user


def _guid(value: object) -> str:
    return str(value).replace("-", "").lower()


def same_value(have: object, want: object) -> bool:
    """Equality that ignores list order and the dashes of an id (Jellyfin writes ids both ways)."""
    if isinstance(have, list) and isinstance(want, list):
        return sorted(map(_guid, have)) == sorted(map(_guid, want))
    return have == want


def apply_policy(api: Api, user_id: str, changes: dict) -> bool:
    """Read-modify-write of the full Policy; posts only when a key differs."""
    policy = dict(get_user(api, user_id).get("Policy") or {})
    if all(same_value(policy.get(key), value) for key, value in changes.items()):
        return False
    policy.update(changes)
    api.call("policy", "POST", f"/Users/{user_id}/Policy", body=policy)
    return True


def household_changes(folder_ids: list[str], bps: int) -> dict:
    """What the household policy must say (D-94, D-98); transcoding stays on during the gate."""
    return {
        "IsAdministrator": False,
        "IsHidden": False,
        "IsDisabled": False,
        "EnableContentDeletion": False,
        "EnableContentDeletionFromFolders": [],
        "EnableRemoteControlOfOtherUsers": False,
        "EnableCollectionManagement": False,
        "EnableVideoPlaybackTranscoding": True,
        "EnableAllFolders": False,
        "EnabledFolders": list(folder_ids),
        "RemoteClientBitrateLimit": bps,
    }


def household_policy(policy: dict, folder_ids: list[str], bps: int) -> dict:
    """A new policy with the household rules applied; every other key is kept."""
    return {**policy, **household_changes(folder_ids, bps)}


def policy_gaps(policy: dict, folder_ids: list[str], bps: int) -> list[str]:
    """Names of the policy keys that differ from the household rules."""
    return [
        key
        for key, want in household_changes(folder_ids, bps).items()
        if not same_value(policy.get(key), want)
    ]


def user_prefs(config: dict) -> dict:
    """English audio when the file has it, else its default track; Smart English subtitles (D-95)."""
    return {
        **config,
        "AudioLanguagePreference": "eng",
        "PlayDefaultAudioTrack": False,
        "SubtitleLanguagePreference": "eng",
        "SubtitleMode": "Smart",
    }


def prefs_gaps(config: dict) -> list[str]:
    wanted = user_prefs({})
    return [key for key, want in wanted.items() if config.get(key) != want]


def apply_prefs(api: Api, user_id: str) -> bool:
    config = dict(get_user(api, user_id).get("Configuration") or {})
    if not prefs_gaps(config):
        return False
    api.call(
        "household-prefs",
        "POST",
        "/Users/Configuration",
        query={"userId": user_id},
        body=user_prefs(config),
    )
    return True


def public_users_ok(names: list[str]) -> bool:
    return len(names) == 1 and set(names) == {HOUSEHOLD_USER}


# --- libraries ------------------------------------------------------------------------


def library_options(internet: bool) -> dict:
    return {
        "EnableRealtimeMonitor": True,
        "SaveLocalMetadata": False,
        "EnableInternetProviders": internet,
        "PreferredMetadataLanguage": "en",
        "MetadataCountryCode": "US",
        "EnableTrickplayImageExtraction": False,
        "EnableChapterImageExtraction": False,
    }


def virtual_folders(api: Api) -> list[dict]:
    folders = api.call("libraries", "GET", "/Library/VirtualFolders")
    if not isinstance(folders, list):
        raise Fail("libraries", "unexpected answer from /Library/VirtualFolders")
    return folders


def find_library(api: Api, name: str) -> dict | None:
    return next((f for f in virtual_folders(api) if f.get("Name") == name), None)


def library_gaps(folders: list[dict]) -> list[str]:
    """What is wrong with the two household libraries; Jellyfin's list order never matters."""
    by_name = {str(f.get("Name")): f for f in folders}
    gaps: list[str] = []
    for name, kind, path in LIBRARIES:
        found = by_name.get(name)
        if found is None:
            gaps.append(f"{name} library is missing")
            continue
        options = found.get("LibraryOptions") or {}
        if found.get("CollectionType") != kind:
            gaps.append(f"{name} has the wrong type")
        elif list(found.get("Locations") or []) != [path]:
            gaps.append(f"{name} has the wrong folder")
        elif options.get("SaveLocalMetadata") is not False or not options.get(
            "EnableRealtimeMonitor"
        ):
            gaps.append(f"{name} options differ")
    return gaps


def ensure_library(
    api: Api, name: str, collection_type: str, path: str, *, internet: bool
) -> str:
    """Create the library when absent; returns its ItemId. A library over another path is an error."""
    existing = find_library(api, name)
    if existing is not None:
        if list(existing.get("Locations") or []) != [path]:
            raise Fail("library", f"{name} already exists over a different folder; not repointed")
        return str(existing["ItemId"])
    api.call(
        "library",
        "POST",
        "/Library/VirtualFolders",
        query={
            "name": name,
            "collectionType": collection_type,
            "paths": path,
            "refreshLibrary": "false",
        },
        body={"LibraryOptions": library_options(internet)},
    )
    made = find_library(api, name)
    if made is None:
        raise Fail("library", f"{name} was not created")
    return str(made["ItemId"])


def library_items(
    api: Api, user_id: str, parent_id: str | None, types: str, fields: str
) -> list[dict]:
    query: dict[str, object] = {
        "userId": user_id,
        "Recursive": "true",
        "IncludeItemTypes": types,
        "Fields": fields,
    }
    if parent_id:
        query["ParentId"] = parent_id
    result = api.call("items", "GET", "/Items", query=query)
    if not isinstance(result, dict):
        raise Fail("items", "unexpected answer from /Items")
    return list(result.get("Items") or [])


def item_count(api: Api, user_id: str) -> tuple[int, int]:
    """Items of type Movie, Series, Episode and Video, and how many lack provider ids."""
    items = library_items(api, user_id, None, "Movie,Series,Episode,Video", "ProviderIds")
    return len(items), sum(1 for item in items if not item.get("ProviderIds"))


# --- scan -----------------------------------------------------------------------------


def scan_settled(
    samples: list[tuple[str, int, int]], start_count: int = 0, *, finished_seen: bool = False
) -> bool:
    """RESEARCH Pitfall 5: the library scan was seen running (or items appeared, or it was seen
    to finish), it is Idle now, and the last two samples agree on the counts."""
    if len(samples) < 2:
        return False
    seen = finished_seen or any(
        state == "Running" or count > start_count for state, count, _ in samples
    )
    last, before = samples[-1], samples[-2]
    return seen and last[0] == "Idle" and last[1:] == before[1:]


def _refresh_task(api: Api) -> dict:
    tasks = api.call("scan", "GET", "/ScheduledTasks")
    task = next((t for t in tasks if isinstance(t, dict) and t.get("Key") == "RefreshLibrary"), None)
    if task is None:
        raise Fail("scan", "the RefreshLibrary task was not found")
    return task


def _task_end(task: dict) -> object:
    return (task.get("LastExecutionResult") or {}).get("EndTimeUtc")


def wait_for_scan(api: Api, user_id: str, *, timeout: float = 1800, poll: float = 5.0) -> None:
    """Start a library scan and wait until it has really finished (RESEARCH Pitfall 5)."""
    ended_before = _task_end(_refresh_task(api))
    start_count, _ = item_count(api, user_id)
    api.call("scan", "POST", "/Library/Refresh")
    samples: list[tuple[str, int, int]] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        task = _refresh_task(api)
        count, lacking = item_count(api, user_id)
        samples.append((str(task.get("State")), count, lacking))
        finished = _task_end(task) != ended_before
        if scan_settled(samples, start_count, finished_seen=finished):
            return
        time.sleep(poll)
    raise Fail("scan", f"not settled after {int(timeout)} s")




# --- setup ----------------------------------------------------------------------------


def apply_server_config(api: Api, bps: int) -> bool:
    config = api.call("server-config", "GET", "/System/Configuration")
    if not isinstance(config, dict):
        raise Fail("server-config", "unexpected answer from /System/Configuration")
    wanted = {
        "ServerName": SERVER_NAME,
        "UICulture": "en-US",
        "PreferredMetadataLanguage": "en",
        "MetadataCountryCode": "US",
        "RemoteClientBitrateLimit": bps,
    }
    if all(config.get(key) == value for key, value in wanted.items()):
        return False
    api.call("server-config", "POST", "/System/Configuration", body={**config, **wanted})
    return True


def changed_or_not(changed: bool) -> str:
    return "changed" if changed else "unchanged"


def cmd_setup(args: argparse.Namespace) -> int:
    _, household_password = passwords()
    bps = configured_bps()  # every config problem stops here, before the first request
    was_open = not wizard_completed(Api(args.base))
    api, admin_id = admin_api(args.base)
    step_ok("wizard", "created" if was_open else "unchanged")
    step_ok("admin-login")

    step_ok("server-config", changed_or_not(apply_server_config(api, bps)))

    household_id, outcome = ensure_user(api, HOUSEHOLD_USER, household_password)
    step_ok("household", outcome)

    folder_ids: list[str] = []
    for name, kind, path in LIBRARIES:
        existed = find_library(api, name) is not None
        folder_ids.append(ensure_library(api, name, kind, path, internet=True))
        step_ok(f"library {name}", "unchanged" if existed else "created")

    changes = household_changes(folder_ids, bps)
    step_ok("household-policy", changed_or_not(apply_policy(api, household_id, changes)))
    step_ok("household-prefs", changed_or_not(apply_prefs(api, household_id)))
    step_ok("admin-hidden", changed_or_not(apply_policy(api, admin_id, {"IsHidden": True})))

    if not args.no_scan:
        wait_for_scan(api, admin_id)
        step_ok("scan")
    return 0


# --- check ----------------------------------------------------------------------------


class CheckState:
    def __init__(self, base: str) -> None:
        self.base = base
        self.api: Api | None = None
        self.admin_id = ""

    def admin(self) -> Api:
        if self.api is None:
            raise Fail("admin-login", "skipped: the admin sign-in did not work")
        return self.api

    def library_id(self, name: str, step: str) -> str:
        found = find_library(self.admin(), name)
        if found is None:
            raise Fail(step, f"library {name} is missing")
        return str(found["ItemId"])

    def user(self, name: str, step: str) -> dict:
        found = find_user(self.admin(), name)
        if found is None:
            raise Fail(step, f"user {name} is missing")
        return get_user(self.admin(), str(found["Id"]))


def check_wizard_complete(state: CheckState) -> None:
    if not wizard_completed(Api(state.base)):
        raise Fail("wizard-complete", "the first-run wizard is still open")


def check_admin_login(state: CheckState) -> None:
    admin_password, _ = passwords()
    token, state.admin_id = login(Api(state.base), ADMIN_USER, admin_password, step="admin-login")
    state.api = Api(state.base, token)


def check_public_users(state: CheckState) -> None:
    status, payload = Api(state.base).request("GET", "/Users/Public")
    if status != 200 or not isinstance(payload, list):
        raise Fail("public-users", f"expected HTTP 200 with a list, got {status}")
    names = [str(user.get("Name")) for user in payload if isinstance(user, dict)]
    if not names:
        raise Fail("public-users", "no user is shown on the login screen")
    if not public_users_ok(names):
        raise Fail("public-users", f"the login screen must show only {HOUSEHOLD_USER}")


def check_admin_hidden(state: CheckState) -> None:
    admin = state.user(ADMIN_USER, "admin-hidden")
    if not (admin.get("Policy") or {}).get("IsHidden"):
        raise Fail("admin-hidden", "the admin is shown on the login screen")


def check_household_policy(state: CheckState) -> None:
    household = state.user(HOUSEHOLD_USER, "household-policy")
    ids = [state.library_id(name, "household-policy") for name, _, _ in LIBRARIES]
    gaps = policy_gaps(household.get("Policy") or {}, ids, configured_bps())
    if gaps:
        raise Fail("household-policy", "differs: " + ", ".join(gaps))


def check_household_prefs(state: CheckState) -> None:
    household = state.user(HOUSEHOLD_USER, "household-prefs")
    gaps = prefs_gaps(household.get("Configuration") or {})
    if gaps:
        raise Fail("household-prefs", "differs: " + ", ".join(gaps))


def check_libraries(state: CheckState) -> None:
    gaps = library_gaps(virtual_folders(state.admin()))
    if gaps:
        raise Fail("libraries", "; ".join(gaps))


def check_bitrate(state: CheckState) -> None:
    bps = configured_bps()
    config = state.admin().call("bitrate", "GET", "/System/Configuration")
    household = state.user(HOUSEHOLD_USER, "bitrate")
    wrong = []
    if not isinstance(config, dict) or config.get("RemoteClientBitrateLimit") != bps:
        wrong.append("server")
    if (household.get("Policy") or {}).get("RemoteClientBitrateLimit") != bps:
        wrong.append("household")
    if wrong:
        raise Fail("bitrate", f"the limit differs from {BITRATE_KEY} for the " + " and ".join(wrong))


def _gaps(checks: tuple[tuple[str, object], ...]) -> str:
    return ", ".join(field for field, ok in checks if not ok)


def check_movies_metadata(state: CheckState) -> None:
    movies = state.library_id(MOVIES_LIBRARY, "movies-metadata")
    items = library_items(
        state.admin(), state.admin_id, movies, "Movie", "ProviderIds,Overview,People"
    )
    problems: list[str] = []
    for title, year in MOVIE_TITLES:
        found = next(
            (i for i in items if i.get("Name") == title and i.get("ProductionYear") == year),
            None,
        )
        if found is None:
            problems.append(f"{title} ({year}) not in the library")
            continue
        gaps = _gaps(
            (
                ("TheMovieDb id", (found.get("ProviderIds") or {}).get("Tmdb")),
                ("plot", (found.get("Overview") or "").strip()),
                ("poster", (found.get("ImageTags") or {}).get("Primary")),
                ("cast", found.get("People")),
            ),
        )
        if gaps:
            problems.append(f"{title} ({year}) lacks {gaps}")
    if problems:
        raise Fail("movies-metadata", "; ".join(problems))


def check_series_metadata(state: CheckState) -> None:
    api, tv = state.admin(), state.library_id(TV_LIBRARY, "series-metadata")
    series = next(
        (
            i
            for i in library_items(api, state.admin_id, tv, "Series", "ProviderIds,Overview")
            if i.get("Name") == SERIES_TITLE
        ),
        None,
    )
    if series is None:
        raise Fail("series-metadata", f"{SERIES_TITLE} not in the library")
    problems: list[str] = []
    gaps = _gaps(
        (
            ("TheMovieDb id", (series.get("ProviderIds") or {}).get("Tmdb")),
            ("poster", (series.get("ImageTags") or {}).get("Primary")),
        ),
    )
    if gaps:
        problems.append(f"{SERIES_TITLE} lacks {gaps}")
    series_id = str(series["Id"])
    if not library_items(api, state.admin_id, series_id, "Season", ""):
        problems.append(f"{SERIES_TITLE} has no season")
    episodes = library_items(api, state.admin_id, series_id, "Episode", "Overview")
    for number in SERIES_EPISODES:
        found = next(
            (
                e
                for e in episodes
                if e.get("ParentIndexNumber") == 1 and e.get("IndexNumber") == number
            ),
            None,
        )
        if found is None:
            problems.append(f"S01E{number:02d} not in the library")
        elif not (found.get("Overview") or "").strip():
            problems.append(f"S01E{number:02d} lacks plot")
    if problems:
        raise Fail("series-metadata", "; ".join(problems))


def check_metadata_local(state: CheckState) -> None:
    folder = JELLYFIN_DIR / "config" / "metadata"
    if not folder.is_dir() or not any(p.is_file() for p in folder.rglob("*")):
        raise Fail("metadata-local", "no image or metadata file below jellyfin/config/metadata")


_CHECK_FUNCTIONS: dict[str, Callable[[CheckState], None]] = {
    "wizard-complete": check_wizard_complete,
    "admin-login": check_admin_login,
    "public-users": check_public_users,
    "admin-hidden": check_admin_hidden,
    "household-policy": check_household_policy,
    "household-prefs": check_household_prefs,
    "libraries": check_libraries,
    "bitrate": check_bitrate,
    "movies-metadata": check_movies_metadata,
    "series-metadata": check_series_metadata,
    "metadata-local": check_metadata_local,
}
CHECK_STEPS = tuple(_CHECK_FUNCTIONS)
CHECKS = tuple(_CHECK_FUNCTIONS.items())


def cmd_check(args: argparse.Namespace) -> int:
    state = CheckState(args.base)
    failures = 0
    for step, function in CHECKS:
        try:
            function(state)
        except Fail as exc:
            failures += 1
            print(f"FAIL {step}: {exc.reason}")
        else:
            step_ok(step)
    return 1 if failures else 0


# --- measure and cap (JFIN-03, D-96) ----------------------------------------------------


def cmd_measure(args: argparse.Namespace) -> int:
    if not 1 <= args.size_mb <= MAX_TEST_MB:
        raise Fail("config", f"--size-mb must be from 1 to {MAX_TEST_MB}")
    if args.runs < 1:
        raise Fail("config", "--runs must be at least 1")
    password = _lookup_env(HOUSEHOLD_KEY)
    if not password or password.startswith("change-me"):
        password = getpass.getpass("Household password: ")
    token, _ = login(Api(args.base), HOUSEHOLD_USER, password, step="household-login")
    api = Api(args.base, token)
    speeds: list[float] = []
    for number in range(1, args.runs + 1):
        started = time.monotonic()
        status, payload = api.request(
            "GET", "/Playback/BitrateTest", query={"Size": args.size_mb * 1_000_000}
        )
        elapsed = time.monotonic() - started
        if status != 200 or not isinstance(payload, bytes) or not payload:
            raise Fail("measure", f"expected HTTP 200 with data, got {status}")
        speeds.append(len(payload) * 8 / 1_000_000 / max(elapsed, 1e-6))
        print(f"run {number}: {speeds[-1]:.0f} Mbps")
    median = statistics.median(speeds)
    print(f"median {median:.0f} Mbps")
    print(f"cap {bitrate_cap(median)} Mbps")
    return 0


def cmd_cap(args: argparse.Namespace) -> int:
    try:
        print(f"cap {bitrate_cap(args.mbps)} Mbps")
    except ValueError as exc:
        raise Fail("config", str(exc)) from None
    return 0


# --- command line ---------------------------------------------------------------------


def main(argv: list[str]) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--base", default=DEFAULT_BASE, help="Jellyfin URL through Caddy")
    parser = argparse.ArgumentParser(description="Provision and check Jellyfin")
    sub = parser.add_subparsers(dest="command", required=True)
    setup = sub.add_parser("setup", parents=[common])
    setup.add_argument("--no-scan", action="store_true", help="skip the library scan")
    setup.set_defaults(func=cmd_setup)
    check = sub.add_parser("check", parents=[common])
    check.set_defaults(func=cmd_check)
    measure = sub.add_parser("measure", parents=[common])
    measure.add_argument("--runs", type=int, default=3)
    measure.add_argument("--size-mb", type=int, default=50)
    measure.set_defaults(func=cmd_measure)
    cap = sub.add_parser("cap")
    cap.add_argument("--mbps", type=float, required=True, help="a measured or link speed")
    cap.set_defaults(func=cmd_cap)
    args = parser.parse_args(argv[1:])
    try:
        return args.func(args)
    except Fail as exc:
        print(f"FAIL {exc.step}: {exc.reason}")
        return 1
    except (urllib.error.URLError, OSError) as exc:
        print(f"FAIL connect: {type(exc).__name__}")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
