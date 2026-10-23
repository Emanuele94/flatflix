#!/usr/bin/env python3
"""Create or complete the local env file from .env.example with random secrets.

Usage:
    uv run --project backend --frozen python scripts/dev_env.py          # create / complete
    uv run --project backend --frozen python scripts/dev_env.py --check  # verify only

Rules:
- Keys already present in the local file are never rewritten.
- Missing keys whose template value starts with "change-me" get a random secret;
  other missing keys copy the template value.
- A missing APP_PASS_HASH gets a random dev password, written to
  .dev-portal-password (mode 0600, gitignored), and its argon2id hash, single-quoted
  so Compose takes the `$` signs literally.
- A missing KVM_GID gets the group id of /dev/kvm (the sandbox microVM needs it); without the
  device it stays empty and one line says so.
- Only key names are printed, never values.
- --check writes nothing; exit 1 if a key is missing or still a placeholder.
"""

from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / ".env.example"
TARGET = ROOT / ".env"
PASSWORD_FILE = ROOT / ".dev-portal-password"
HASH_KEY = "APP_PASS_HASH"
PLACEHOLDER_PREFIX = "change-me"
KVM_KEY = "KVM_GID"
KVM_DEVICE = Path("/dev/kvm")


def parse(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def make_dev_login_hash() -> str:
    """Write a fresh dev password to its 0600 file and return the single-quoted env value."""
    # Lazy import: only needed on first run, inside the uv env.
    from argon2 import PasswordHasher

    password = secrets.token_urlsafe(12)
    PASSWORD_FILE.unlink(missing_ok=True)
    fd = os.open(PASSWORD_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(password + "\n")
    return "'" + PasswordHasher().hash(password) + "'"


def main(argv: list[str]) -> int:
    check = "--check" in argv
    template = parse(TEMPLATE)
    if not template:
        print(f"error: template {TEMPLATE.name} missing or empty", file=sys.stderr)
        return 2
    local = parse(TARGET)

    if check:
        missing = [k for k in template if k not in local]
        placeholder = [k for k, v in local.items() if v.startswith(PLACEHOLDER_PREFIX)]
        if missing:
            print("missing: " + ", ".join(missing))
        if placeholder:
            print("placeholder: " + ", ".join(placeholder))
        return 1 if (missing or placeholder) else 0

    added: list[str] = []
    lines: list[str] = []
    for key, value in template.items():
        if key in local:
            continue
        if key == HASH_KEY and value.startswith(PLACEHOLDER_PREFIX):
            value = make_dev_login_hash()
        elif value.startswith(PLACEHOLDER_PREFIX):
            value = secrets.token_urlsafe(32)
        elif key == KVM_KEY:
            if KVM_DEVICE.exists():
                value = str(KVM_DEVICE.stat().st_gid)
            else:
                print("KVM_GID left empty: /dev/kvm not found")
        lines.append(f"{key}={value}")
        added.append(key)

    if not TARGET.exists():
        fd = os.open(TARGET, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
    if lines:
        existing = TARGET.read_text(encoding="utf-8")
        prefix = "" if (not existing or existing.endswith("\n")) else "\n"
        with TARGET.open("a", encoding="utf-8") as fh:
            fh.write(prefix + "\n".join(lines) + "\n")
    os.chmod(TARGET, 0o600)
    print("added: " + (", ".join(added) if added else "(nothing)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
