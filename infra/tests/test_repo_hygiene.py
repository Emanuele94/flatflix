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

# (first octet, second octet, prefix length) for 10/8, 172.16/12, 192.168/16,
# 169.254/16 and 100.64/10. Kept as tuples so this file holds no full address.
_PRIVATE_BLOCKS = [(10, 0, 8), (172, 16, 12), (192, 168, 16), (169, 254, 16), (100, 64, 10)]
PRIVATE_NETWORKS = [
    ipaddress.ip_network(f"{a}.{b}.0.0/{prefix}") for a, b, prefix in _PRIVATE_BLOCKS
]
_DOTTED_QUAD = re.compile(r"(?<![\w.])\d{1,3}(?:\.\d{1,3}){3}(?!\w|\.\d)")
_ARGON2 = re.compile(
    r"\$argon2id\$v=\d+\$m=\d+,t=\d+,p=\d+\$[A-Za-z0-9+/]{16,}\$[A-Za-z0-9+/]{16,}"
)
_QBIT_HASH = re.compile(r"@ByteArray\([A-Za-z0-9+/=]{16,}:[A-Za-z0-9+/=]{16,}\)")


def find_lan_ips(text: str) -> list[tuple[int, str]]:
    """(line number, address) for every private, link-local or CGNAT address in text."""
    found = []
    for number, line in enumerate(text.splitlines(), start=1):
        for match in _DOTTED_QUAD.finditer(line):
            try:
                address = ipaddress.ip_address(match.group(0))
            except ValueError:
                continue
            if any(address in net for net in PRIVATE_NETWORKS):
                found.append((number, match.group(0)))
    return found


def find_secret_material(text: str) -> list[tuple[int, str]]:
    """(line number, kind) for every complete argon2id hash or qBittorrent PBKDF2 value."""
    found = []
    for number, line in enumerate(text.splitlines(), start=1):
        if _ARGON2.search(line):
            found.append((number, "argon2id hash"))
        if _QBIT_HASH.search(line):
            found.append((number, "qBittorrent password hash"))
    return found


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


def secret_like_offenders(lines: list[str]) -> list[str]:
    """Keys that look secret and hold anything but a change-me placeholder or an empty value.

    An empty value holds no secret: the opt-in TMDB_API_KEY ships empty (D-93).
    """
    offenders = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        secret_like = any(word in key.upper() for word in ("PASS", "SECRET", "KEY", "HASH", "TOKEN"))
        if secret_like and value != "" and not value.startswith("change-me"):
            offenders.append(key)
    return offenders


def test_secret_like_example_values_are_placeholders():
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    assert secret_like_offenders(lines) == []


@pytest.mark.parametrize(
    ("line", "offends"),
    [
        ("TMDB_API_KEY=", False),
        ("TMDB_API_KEY=abc123", True),
        ("JELLYFIN_ADMIN_PASSWORD=change-me-x", False),
        ("JELLYFIN_ADMIN_PASSWORD=hunter22", True),
    ],
)
def test_secret_like_offenders_accepts_only_a_placeholder_or_an_empty_value(line, offends):
    assert bool(secret_like_offenders([line])) is offends


def test_no_tracked_file_contains_a_lan_address():
    offenders = _scan(find_lan_ips)
    assert offenders == [], "\n".join(offenders)


def test_no_tracked_file_contains_a_complete_password_hash():
    offenders = _scan(find_secret_material)
    assert offenders == [], "\n".join(offenders)


# -- the sandbox is built from the repo, never committed as binaries (QUAR-05, T-02.1-20) ------

_BINARY_SUFFIXES = ("vmlinux", ".ext4", ".img", ".tgz")


def _tracked_paths() -> list[str]:
    return [raw.decode() for raw in _git("ls-files", "-z").stdout.split(b"\0") if raw]


def find_committed_sandbox_binaries(paths: list[str]) -> list[str]:
    """Tracked paths that look like a kernel, a disk image, a release tarball or the VMM."""
    return [
        path
        for path in paths
        if path.endswith(_BINARY_SUFFIXES) or path.rsplit("/", 1)[-1] == "firecracker"
    ]


def find_nul_files(root: Path, paths: list[str], folder: str) -> list[str]:
    offenders = []
    for path in paths:
        if not path.startswith(folder + "/") or not (root / path).is_file():
            continue
        if b"\0" in (root / path).read_bytes():
            offenders.append(path)
    return offenders


def test_the_binary_finder_has_teeth():
    found = find_committed_sandbox_binaries(
        ["sandbox/vmlinux", "a/rootfs.ext4", "x.img", "fc.tgz", "bin/firecracker", "sandbox/Dockerfile"]
    )
    assert found == ["sandbox/vmlinux", "a/rootfs.ext4", "x.img", "fc.tgz", "bin/firecracker"]


def test_no_kernel_rootfs_or_firecracker_binary_is_tracked():
    assert find_committed_sandbox_binaries(_tracked_paths()) == []


def test_no_tracked_file_under_sandbox_contains_a_nul_byte():
    assert find_nul_files(ROOT, _tracked_paths(), "sandbox") == []


def test_the_nul_finder_has_teeth(tmp_path):
    (tmp_path / "sandbox").mkdir()
    (tmp_path / "sandbox" / "blob").write_bytes(b"ab\0cd")
    (tmp_path / "sandbox" / "text").write_text("plain")
    assert find_nul_files(tmp_path, ["sandbox/blob", "sandbox/text"], "sandbox") == [
        "sandbox/blob"
    ]


def test_the_sandbox_build_pins_and_checks_its_downloads():
    text = (ROOT / "sandbox" / "Dockerfile").read_text(encoding="utf-8")
    assert re.search(r"^ARG FIRECRACKER_VERSION=1\.17\.0$", text, flags=re.MULTILINE)
    assert re.search(r"^ARG KERNEL_VERSION=6\.18\.58$", text, flags=re.MULTILINE)
    for name in ("FIRECRACKER_SHA256", "KERNEL_SHA256"):
        assert re.search(rf"^ARG {name}=[0-9a-f]{{64}}$", text, flags=re.MULTILINE), name
    assert re.search(r"^ARG FFMPEG_APK_VERSION=\S+$", text, flags=re.MULTILINE)
    assert 'ffmpeg=${FFMPEG_APK_VERSION}"' in text
    assert text.count("sha256sum -c") >= 2


def test_the_guest_init_is_a_tracked_executable():
    out = _git("ls-files", "-s", "sandbox/guest/init").stdout.decode()
    assert out.startswith("100755 "), out
