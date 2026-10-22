"""SEC-04 hygiene: no secrets, no LAN addresses and no real credentials in the public repo.

Addresses in comments, docstrings and plans must be written in the short form
(for example "the 10/8 block"), never as full dotted quads, or this scan flags
its own repository. Synthetic samples below are assembled at run time for the
same reason.
"""

from __future__ import annotations

import ipaddress
import re
import subprocess
from pathlib import Path

import pytest


def _git(*args: str, check: bool = True, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        check=check,
        capture_output=True,
        cwd=cwd or ROOT,
    )


ROOT = Path(
    subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent,
    ).stdout.strip()
)

PRIVATE_NETWORKS = [
    ipaddress.ip_network(net)
    for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", "100.64.0.0/10")
]
_DOTTED_QUAD = re.compile(r"(?<![\w.])\d{1,3}(?:\.\d{1,3}){3}(?!\w|\.\d)")
_ARGON2 = re.compile(
    r"\$argon2id\$v=\d+\$m=\d+,t=\d+,p=\d+\$[A-Za-z0-9+/]{16,}\$[A-Za-z0-9+/]{16,}"
)
_QBIT_HASH = re.compile(r"@ByteArray\([A-Za-z0-9+/=]{16,}:[A-Za-z0-9+/=]{16,}\)")


def find_lan_ips(text: str) -> list[tuple[int, str]]:
    return []  # RED stub

def find_secret_material(text: str) -> list[tuple[int, str]]:
    return []  # RED stub

def _tracked_text_files() -> list[Path]:
    names = _git("ls-files", "-z").stdout.split(b"\0")
    files = []
    for raw in names:
        if not raw:
            continue
        path = ROOT / raw.decode()
        if not path.is_file():
            continue
        with path.open("rb") as handle:
            if b"\0" in handle.read(8192):
                continue
        files.append(path)
    return files


def _scan(finder) -> list[str]:
    offenders = []
    for path in _tracked_text_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for number, what in finder(text):
            offenders.append(f"{path.relative_to(ROOT)}:{number}: {what}")
    return offenders


def _dotted(*octets: int) -> str:
    return ".".join(str(o) for o in octets)


# --- pure scanners ------------------------------------------------------------


@pytest.mark.parametrize(
    "address",
    [
        _dotted(10, 0, 0, 1),
        _dotted(172, 16, 5, 9),
        _dotted(172, 31, 255, 254),
        _dotted(192, 168, 1, 20),
        _dotted(169, 254, 10, 10),
        _dotted(100, 64, 0, 1),
        _dotted(100, 127, 255, 255),
    ],
)
def test_scanner_flags_private_ranges(address):
    assert find_lan_ips(f"host: {address}\n") == [(1, address)]


@pytest.mark.parametrize(
    "address",
    [
        _dotted(127, 0, 0, 1),
        _dotted(8, 8, 8, 8),
        _dotted(172, 32, 0, 1),
        _dotted(100, 128, 0, 1),
        _dotted(192, 169, 0, 1),
        _dotted(0, 0, 0, 0),
    ],
)
def test_scanner_ignores_public_and_loopback(address):
    assert find_lan_ips(f"host: {address}\n") == []


def test_scanner_reports_every_line_in_order():
    text = f"a {_dotted(10, 1, 1, 1)}\nok\nb {_dotted(192, 168, 0, 5)} and {_dotted(10, 2, 2, 2)}\n"
    assert [n for n, _ in find_lan_ips(text)] == [1, 3, 3]


def test_scanner_does_not_match_version_like_longer_strings():
    assert find_lan_ips(f"v{_dotted(10, 0, 0, 1)}\n{_dotted(10, 0, 0, 1)}.5\n") == []


def test_secret_scanner_flags_complete_hashes_only():
    salt = "A" * 22
    key = "b" * 43
    argon = "$argon2id$v=19$m=65536,t=3,p=4$" + salt + "$" + key
    qbit = "@ByteArray(" + "c" * 24 + ":" + "d" * 88 + ")"
    assert find_secret_material(argon) == [(1, "argon2id hash")]
    assert find_secret_material(qbit) == [(1, "qBittorrent password hash")]
    assert find_secret_material("$argon2id$v=19$m=65536,t=3,p=4$short$short") == []
    assert find_secret_material("@ByteArray(salt:key)") == []


# --- the real repository --------------------------------------------------------


def _ignored(path: str) -> bool:
    return _git("check-ignore", "-q", path, check=False).returncode == 0


def _tracked(path: str) -> bool:
    return bool(_git("ls-files", "--", path).stdout.strip())


def test_local_env_file_is_ignored_and_untracked():
    assert _ignored(".env")
    assert not _tracked(".env")


def test_env_example_is_tracked_and_not_ignored():
    assert _tracked(".env.example")
    assert not _ignored(".env.example")


@pytest.mark.parametrize(
    "path",
    [".dev-portal-password", "qbittorrent/config/qBittorrent/qBittorrent.conf"],
)
def test_generated_secrets_are_ignored(path):
    assert _ignored(path)


def test_secret_like_example_values_are_placeholders():
    offenders = []
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if any(word in key.upper() for word in ("PASS", "SECRET", "KEY", "HASH", "TOKEN")):
            if not value.startswith("change-me"):
                offenders.append(key)
    assert offenders == []


def test_no_tracked_file_contains_a_lan_address():
    offenders = _scan(find_lan_ips)
    assert offenders == [], "\n".join(offenders)


def test_no_tracked_file_contains_a_complete_password_hash():
    offenders = _scan(find_secret_material)
    assert offenders == [], "\n".join(offenders)
