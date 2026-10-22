"""Docker-free invariants for the compose files (SEC-02, INFRA-01, INFRA-02, MEDIA-01).

The port map and media contract are written in docs/ports-and-media.md. These
tests read docker-compose.yml, docker-compose.admin.yml and .env.example as
plain YAML/text, so they run anywhere without Docker.
"""

from __future__ import annotations

import copy
import json
import re
import subprocess
from pathlib import Path

import pytest
import yaml

LOOPBACK = "127.0.0.1"


def _repo_root() -> Path:
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent,
    )
    return Path(out.stdout.strip())


ROOT = _repo_root()


def _load_yaml(name: str) -> dict:
    return yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))


def published_host_ip(entry) -> str | None:
    """Host IP a ports entry binds to, or None when it binds every interface.

    The comparison is on the exact string: a prefix such as 127.0.0.10 or a
    host name that merely starts with the loopback address is a different IP.
    """
    if isinstance(entry, dict):
        value = entry.get("host_ip")
        return None if value is None else str(value)
    text = str(entry).strip()
    if text.startswith("["):
        end = text.find("]")
        if end == -1:
            return None
        return text[: end + 1]
    parts = text.split(":")
    if len(parts) >= 3:
        return parts[0]
    return None


def check_qbittorrent_ports(entries) -> list[str]:
    """Every violation of "only entries bound to exactly 127.0.0.1", not just the first."""
    violations = []
    for index, entry in enumerate(entries or []):
        ip = published_host_ip(entry)
        if ip != LOOPBACK:
            violations.append(f"ports[{index}] {entry!r} binds {ip or 'all interfaces'}")
    return violations


def _host_port(entry) -> str | None:
    """Host side of a ports entry, with a ${VAR:-default} reduced to its default."""
    if isinstance(entry, dict):
        value = entry.get("published")
    else:
        text = str(entry).split("/")[0]
        if text.startswith("["):
            text = text[text.find("]") + 2 :]
        parts = text.split(":")
        value = parts[-2] if len(parts) >= 2 else None
        if len(parts) == 3:
            value = parts[1]
    if value is None:
        return None
    value = str(value)
    match = re.fullmatch(r"\$\{[A-Za-z_][A-Za-z0-9_]*:-(\d+)\}", value)
    return match.group(1) if match else value


def _networks(service: dict) -> set[str]:
    nets = service.get("networks") or []
    return set(nets.keys()) if isinstance(nets, dict) else set(nets)


@pytest.fixture(scope="module")
def base() -> dict:
    return _load_yaml("docker-compose.yml")


@pytest.fixture(scope="module")
def admin() -> dict:
    return _load_yaml("docker-compose.admin.yml")


@pytest.fixture(scope="module")
def env_example() -> dict[str, str]:
    values = {}
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


# --- published_host_ip and check_qbittorrent_ports (pure) -------------------


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        ("127.0.0.1:8088:8088", "127.0.0.1"),
        ("8088:8088", None),
        ("8088", None),
        ("0.0.0.0:8088:8088", "0.0.0.0"),
        ("127.0.0.10:8088:8088", "127.0.0.10"),
        ("127.0.0.1.nip.io:8088:8088", "127.0.0.1.nip.io"),
        ("[::]:8088:8088", "[::]"),
        ("127.0.0.1:8088:8088/tcp", "127.0.0.1"),
        ({"target": 8088, "published": 8088, "host_ip": "127.0.0.1"}, "127.0.0.1"),
        ({"target": 8088, "published": 8088}, None),
    ],
)
def test_published_host_ip_is_exact(entry, expected):
    assert published_host_ip(entry) == expected


def test_loopback_entry_passes_the_boundary():
    assert check_qbittorrent_ports(["127.0.0.1:8088:8088"]) == []


@pytest.mark.parametrize(
    "bad",
    [
        "8088:8088",
        "0.0.0.0:8088:8088",
        "127.0.0.10:8088:8088",
        "127.0.0.1.nip.io:8088:8088",
        "[::]:8088:8088",
        {"target": 8088, "published": 8088},
    ],
)
def test_non_loopback_entry_fails(bad):
    assert len(check_qbittorrent_ports([bad])) == 1


@pytest.mark.parametrize("empty", [None, []])
def test_absent_or_empty_ports_are_unpublished(empty):
    assert check_qbittorrent_ports(empty) == []


def test_bad_entry_fails_wherever_it_sits():
    good = "127.0.0.1:8088:8088"
    bad = "8088:8088"
    assert len(check_qbittorrent_ports([bad, good])) == 1
    assert len(check_qbittorrent_ports([good, bad])) == 1
    assert len(check_qbittorrent_ports([good, bad, good, "0.0.0.0:6881:6881"])) == 2


# --- the real compose files --------------------------------------------------


def test_only_web_publishes_a_port(base):
    published = {
        name: svc["ports"] for name, svc in base["services"].items() if svc.get("ports")
    }
    assert set(published) == {"web"}
    assert published["web"] == ["${WEB_PORT:-80}:80"]


def test_qbittorrent_publishes_nothing_in_the_base_stack(base):
    assert (base["services"]["qbittorrent"].get("ports") or []) == []


def test_a_bad_qbittorrent_entry_added_last_is_caught(base):
    mutated = copy.deepcopy(base)
    mutated["services"]["qbittorrent"]["ports"] = ["8088:8088"]
    assert (mutated["services"]["qbittorrent"].get("ports") or []) != []
    assert len(check_qbittorrent_ports(mutated["services"]["qbittorrent"]["ports"])) == 1


def test_admin_override_only_adds_loopback_ports_to_qbittorrent(admin):
    assert set(admin["services"]) == {"qbittorrent"}
    assert set(admin["services"]["qbittorrent"]) == {"ports"}
    entries = admin["services"]["qbittorrent"]["ports"]
    assert entries, "the admin override must publish the WebUI on the loopback"
    assert check_qbittorrent_ports(entries) == []


def test_qbittorrent_and_web_share_no_network(base):
    services = base["services"]
    assert _networks(services["qbittorrent"]) == {"qbit"}
    assert _networks(services["web"]) == {"edge"}
    assert _networks(services["backend"]) == {"edge", "qbit"}
    assert not (base["networks"].get("qbit") or {}).get("internal", False)


def test_host_ports_are_unique_across_base_and_admin(base, admin):
    host_ports = []
    for doc in (base, admin):
        for svc in doc["services"].values():
            for entry in svc.get("ports") or []:
                host_ports.append(_host_port(entry))
    assert None not in host_ports
    assert len(host_ports) == len(set(host_ports)), host_ports


def test_port_8080_is_used_nowhere(base, admin):
    for doc in (base, admin):
        assert not re.search(r"(?<!\d)8080(?!\d)", json.dumps(doc))


def test_webui_port_avoids_the_other_services(base, env_example):
    webui = base["services"]["qbittorrent"]["environment"]["WEBUI_PORT"]
    assert str(webui) not in {"80", "8000", "8080", "8096"}
    url_port = re.search(r":(\d+)(?:/|$)", env_example["QBITTORRENT_URL"])
    assert url_port and url_port.group(1) == str(webui)


def test_startup_order_is_enforced_by_health(base):
    services = base["services"]
    assert services["web"]["depends_on"]["backend"]["condition"] == "service_healthy"
    assert services["backend"]["depends_on"]["qbittorrent"]["condition"] == "service_healthy"


def test_every_service_has_a_healthcheck_and_qbittorrent_stays_unauthenticated(base):
    for name, svc in base["services"].items():
        assert svc.get("healthcheck"), f"{name} has no healthcheck"
    test = base["services"]["qbittorrent"]["healthcheck"]["test"]
    text = test if isinstance(test, str) else " ".join(test)
    assert "/api/v2" not in text


def _volume(service: dict, target: str) -> dict:
    matches = [
        v for v in service["volumes"] if isinstance(v, dict) and v.get("target") == target
    ]
    assert len(matches) == 1, f"expected one long-syntax bind for {target}"
    return matches[0]


@pytest.mark.parametrize("target", ["/media/Film", "/media/SerieTV", "/incomplete"])
def test_media_binds_refuse_missing_host_folders(base, target):
    volume = _volume(base["services"]["qbittorrent"], target)
    assert volume["type"] == "bind"
    assert volume["bind"]["create_host_path"] is False


def test_incomplete_folder_lives_outside_media_root(base):
    source = _volume(base["services"]["qbittorrent"], "/incomplete")["source"]
    assert not source.startswith("${MEDIA_ROOT")


def test_media_owner_is_set(base):
    env = base["services"]["qbittorrent"]["environment"]
    assert env.get("PUID") and env.get("PGID")


def test_images_are_pinned_and_compose_is_versionless(base):
    assert "version" not in base
    images = [svc["image"] for svc in base["services"].values() if "image" in svc]
    assert base["services"]["qbittorrent"]["image"].endswith(":5.2.4")
    assert images and not any(image.endswith(":latest") or ":" not in image for image in images)
    for dockerfile in ("web/Dockerfile", "backend/Dockerfile"):
        froms = re.findall(
            r"^FROM\s+(?:--\S+\s+)?(\S+)", (ROOT / dockerfile).read_text(), flags=re.M
        )
        stages = re.findall(r"^FROM\s+.*\s+AS\s+(\S+)", (ROOT / dockerfile).read_text(), flags=re.M)
        for ref in froms:
            if ref in stages:
                continue
            assert ":" in ref and not ref.endswith(":latest"), f"{dockerfile}: {ref}"


# -- the backend must not trust X-Forwarded-For from every container (WR-02) -----------------


def test_backend_does_not_trust_forwarded_for_from_every_peer():
    dockerfile = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    command = next(line for line in dockerfile.splitlines() if line.startswith("CMD"))
    assert "--forwarded-allow-ips" not in command
    assert "--proxy-headers" not in command.replace("--no-proxy-headers", "")
    assert "--no-proxy-headers" in command


def test_caddy_sets_forwarded_for_from_the_address_it_saw():
    caddyfile = (ROOT / "web" / "Caddyfile").read_text(encoding="utf-8")
    assert "header_up X-Forwarded-For {remote_host}" in caddyfile


# -- Caddy cache rules: a redeploy must reach the phones (D-42) -------------------------------


def _caddy_handle_blocks() -> list[str]:
    """Top-level `handle` blocks of the site, each as its own text, found by counting braces."""
    lines = (ROOT / "web" / "Caddyfile").read_text(encoding="utf-8").splitlines()
    blocks: list[list[str]] = []
    current: list[str] | None = None
    depth = 0
    for line in lines:
        stripped = line.strip()
        if current is None and depth == 1 and stripped.startswith("handle"):
            current = []
            blocks.append(current)
        if current is not None:
            current.append(line)
        depth += line.count("{") - line.count("}")
        if current is not None and depth == 1:
            current = None
    return ["\n".join(block) for block in blocks]


def test_hashed_assets_are_immutable_only_for_2xx_and_never_fall_back():
    blocks = [b for b in _caddy_handle_blocks() if b.lstrip().startswith("handle /assets/*")]
    assert len(blocks) == 1
    block = blocks[0]
    assert "immutable" in block
    assert "max-age=31536000" in block
    assert "match status 2xx" in block
    assert "file_server" in block
    assert "try_files" not in block


def test_index_and_spa_fallback_are_revalidated():
    blocks = _caddy_handle_blocks()
    catch_all = blocks[-1]
    assert catch_all.lstrip().startswith("handle {")
    assert 'Cache-Control "no-cache"' in catch_all
    assert "try_files {path} /index.html" in catch_all
    assert "immutable" not in catch_all
