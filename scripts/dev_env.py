#!/usr/bin/env python3
"""Create or complete the local env file from .env.example with random secrets.

Usage:
    uv run --project backend --frozen python scripts/dev_env.py          # create / complete
    uv run --project backend --frozen python scripts/dev_env.py --check  # verify only

Rules:
- Keys already present in the local file are never rewritten.
- Missing keys whose template value starts with "change-me" get a random secret;
  other missing keys copy the template value.
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
PLACEHOLDER_PREFIX = "change-me"


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
        if value.startswith(PLACEHOLDER_PREFIX):
            value = secrets.token_urlsafe(32)
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
