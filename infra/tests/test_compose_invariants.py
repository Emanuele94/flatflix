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
    assert _networks(services["backend"]) == {"edge", "qbit", "sandbox"}
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


@pytest.mark.parametrize("name", ["qbittorrent", "backend"])
def test_data_bind_is_single_and_refuses_missing_host_folder(base, name):
    volume = _volume(base["services"][name], "/data")
    assert volume["type"] == "bind"
    assert volume["source"] == "${DATA_ROOT:-./data}"
    assert volume["bind"]["create_host_path"] is False


def test_no_service_mounts_the_old_media_targets(base):
    for name, service in base["services"].items():
        for volume in service.get("volumes") or []:
            target = volume["target"] if isinstance(volume, dict) else str(volume).split(":")[1]
            for old in ("/media", "/incomplete"):
                assert not (target == old or target.startswith(old + "/")), f"{name}: {target}"


def test_backend_runs_as_the_media_owner(base):
    assert base["services"]["backend"]["user"] == "${PUID:-1000}:${PGID:-1000}"


def test_media_owner_is_set(base):
    env = base["services"]["qbittorrent"]["environment"]
    assert env.get("PUID") and env.get("PGID")


def test_images_are_pinned_and_compose_is_versionless(base):
    assert "version" not in base
    images = [svc["image"] for svc in base["services"].values() if "image" in svc]
    assert base["services"]["qbittorrent"]["image"].endswith(":5.2.4")
    assert images and not any(image.endswith(":latest") or ":" not in image for image in images)
    for dockerfile in ("web/Dockerfile", "backend/Dockerfile", "sandbox/Dockerfile"):
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


# -- every container logs to stdout through Docker, rotated (D-40, SEC-06) --------------------


@pytest.mark.parametrize("name", ["qbittorrent", "backend", "sandbox", "web"])
def test_every_service_rotates_its_logs(base, name):
    assert base["services"][name]["logging"] == {
        "driver": "json-file",
        "options": {"max-size": "10m", "max-file": "5"},
    }


def test_no_service_writes_logs_to_a_volume(base):
    for name, service in base["services"].items():
        for volume in service.get("volumes") or []:
            target = volume["target"] if isinstance(volume, dict) else str(volume).split(":")[1]
            assert "log" not in target.lower(), f"{name} mounts a log path: {target}"


# -- the sandbox (microVM runner): hardened, offline, read-only (QUAR-02, D-68, D-71) ---------


def check_sandbox(service: dict) -> list[str]:
    """Every way the sandbox service is weaker than D-71 (amended) allows, not just the first."""
    violations = []
    if service.get("read_only") is not True:
        violations.append("read_only is not true")
    if service.get("cap_drop") != ["ALL"]:
        violations.append(f"cap_drop is {service.get('cap_drop')!r}, expected ['ALL']")
    if "cap_add" in service:
        violations.append(f"cap_add is set: {service['cap_add']!r}")
    if service.get("privileged"):
        violations.append("privileged is set")
    security_opt = service.get("security_opt") or []
    if "no-new-privileges:true" not in security_opt:
        violations.append("no-new-privileges:true is missing")
    for option in security_opt:
        if "unconfined" in str(option):
            violations.append(f"security_opt {option!r} switches a profile off")
    if service.get("devices") != ["/dev/kvm:/dev/kvm"]:
        violations.append(f"devices is {service.get('devices')!r}, expected only /dev/kvm")
    if service.get("user") != "10002:10002":
        violations.append(f"user is {service.get('user')!r}, expected '10002:10002'")
    groups = service.get("group_add") or []
    if len(groups) != 1 or not (
        str(groups[0]).startswith("${KVM_GID:?") and "init-host-dirs.sh" in str(groups[0])
    ):
        violations.append(f"group_add is {groups!r}, expected one required ${{KVM_GID:?...}}")
    for key in ("env_file", "ports", "expose", "network_mode", "pid", "ipc"):
        if key in service:
            violations.append(f"{key} is set")
    for key in ("pids_limit", "mem_limit"):
        if not service.get(key):
            violations.append(f"{key} is missing")
    volumes = service.get("volumes") or []
    if len(volumes) != 1 or not isinstance(volumes[0], dict):
        violations.append(f"expected exactly one long-syntax volume, got {volumes!r}")
    else:
        volume = volumes[0]
        if volume.get("type") != "bind":
            violations.append("the volume is not a bind")
        if volume.get("source") != "${DATA_ROOT:-./data}/quarantine":
            violations.append(f"volume source is {volume.get('source')!r}")
        if volume.get("target") != "/data/quarantine":
            violations.append(f"volume target is {volume.get('target')!r}")
        if volume.get("read_only") is not True:
            violations.append("the quarantine mount is not read_only")
        if (volume.get("bind") or {}).get("create_host_path") is not False:
            violations.append("create_host_path is not false")
    if _networks(service) != {"sandbox"}:
        violations.append(f"networks is {sorted(_networks(service))!r}, expected only sandbox")
    if not service.get("healthcheck"):
        violations.append("healthcheck is missing")
    if service.get("logging") != {
        "driver": "json-file",
        "options": {"max-size": "10m", "max-file": "5"},
    }:
        violations.append("logging is not the rotated json-file")
    return violations


def test_the_sandbox_service_is_hardened_as_decided(base):
    assert check_sandbox(base["services"]["sandbox"]) == []


def _mutated(base: dict, **changes) -> dict:
    service = copy.deepcopy(base["services"]["sandbox"])
    for key, value in changes.items():
        if value is None:
            service.pop(key, None)
        else:
            service[key] = value
    return service


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"cap_add": ["SYS_ADMIN"]}, "cap_add"),
        ({"security_opt": ["no-new-privileges:true", "seccomp=unconfined"]}, "unconfined"),
        ({"security_opt": ["apparmor=unconfined", "no-new-privileges:true"]}, "unconfined"),
        ({"privileged": True}, "privileged"),
        ({"devices": ["/dev/kvm:/dev/kvm", "/dev/net/tun:/dev/net/tun"]}, "devices"),
        ({"read_only": False}, "read_only"),
        ({"cap_drop": ["NET_RAW"]}, "cap_drop"),
        ({"user": "0:0"}, "user"),
        ({"user": None}, "user"),
        ({"group_add": ["993"]}, "group_add"),
        ({"env_file": ".env"}, "env_file"),
        ({"ports": ["127.0.0.1:8090:8090"]}, "ports"),
        ({"networks": ["sandbox", "qbit"]}, "networks"),
        ({"pids_limit": None}, "pids_limit"),
        ({"mem_limit": None}, "mem_limit"),
        ({"healthcheck": None}, "healthcheck"),
        ({"logging": None}, "logging"),
        (
            {
                "volumes": [
                    {
                        "type": "bind",
                        "source": "${DATA_ROOT:-./data}/quarantine",
                        "target": "/data/quarantine",
                        "bind": {"create_host_path": False},
                    }
                ]
            },
            "read_only",
        ),
        (
            {
                "volumes": [
                    {
                        "type": "bind",
                        "source": "${DATA_ROOT:-./data}",
                        "target": "/data",
                        "read_only": True,
                        "bind": {"create_host_path": False},
                    }
                ]
            },
            "volume",
        ),
    ],
)
def test_a_weakened_sandbox_entry_is_caught(base, change, expected):
    violations = check_sandbox(_mutated(base, **change))
    assert any(expected in violation for violation in violations), violations


def test_the_sandbox_network_is_internal_and_shared_with_the_backend_only(base):
    assert base["networks"]["sandbox"].get("internal") is True
    on_sandbox = {
        name for name, service in base["services"].items() if "sandbox" in _networks(service)
    }
    assert on_sandbox == {"backend", "sandbox"}


def test_the_backend_does_not_wait_for_the_sandbox(base):
    depends = base["services"]["backend"].get("depends_on") or {}
    assert "sandbox" not in depends


def test_a_sandbox_on_a_second_network_is_caught(base):
    service = _mutated(base, networks=["sandbox", "edge"])
    assert any("networks" in violation for violation in check_sandbox(service))


def test_the_admin_override_does_not_touch_the_sandbox(admin):
    assert "sandbox" not in admin["services"]
