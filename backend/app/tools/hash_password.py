"""Create the APP_PASS_HASH line for the shared portal account (D-17, Pitfall 6).

Usage:
    uv run --directory backend --frozen python -m app.tools.hash_password
    docker compose run --rm --no-deps backend python -m app.tools.hash_password
    printf '%s\\n' "$PASSWORD" | python -m app.tools.hash_password --stdin

Stdout is exactly one line, `APP_PASS_HASH='$argon2id$...'`, single-quoted so that
Docker Compose takes the `$` signs literally. Paste it into .env as is. Problems
go to stderr with exit code 2, and the password is never printed.
"""

import argparse
import getpass
import sys

from argon2 import PasswordHasher

MIN_LENGTH = 8


def _fail(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.tools.hash_password",
        description="Print an APP_PASS_HASH='...' line for .env",
    )
    parser.add_argument(
        "--stdin", action="store_true", help="read the password from one line of standard input"
    )
    args = parser.parse_args(argv)

    if args.stdin:
        password = sys.stdin.readline().rstrip("\r\n")
    else:
        password = getpass.getpass("Password: ")
        if getpass.getpass("Ripeti la password: ") != password:
            return _fail("the two passwords differ")

    if len(password) < MIN_LENGTH:
        return _fail(f"the password must have at least {MIN_LENGTH} characters")

    print(f"APP_PASS_HASH='{PasswordHasher().hash(password)}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
