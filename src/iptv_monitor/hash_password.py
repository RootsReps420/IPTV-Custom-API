"""Hash / verify /watch site passwords (not Xtream panel passwords).

Stored form: pbkdf2_sha256$iterations$salt$hex
CLI: python -m iptv_monitor.hash_password
     python main.py watch-hash
Paste the printed line into config/watch_users.yaml as password_hash.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import hmac
import os
import sys

SCHEME = "pbkdf2_sha256"
ITERATIONS = 120_000


def hash_password(password: str, *, iterations: int = ITERATIONS) -> str:
    """Return a salted pbkdf2 string safe to store in watch_users.yaml."""
    if not password:
        raise ValueError("Password is empty")
    salt = os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations
    )
    return f"{SCHEME}${iterations}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time compare. False on empty hash, wrong scheme, or mismatch."""
    if not password or not stored:
        return False
    parts = stored.split("$")
    if len(parts) != 4 or parts[0] != SCHEME:
        return False
    try:
        iterations = int(parts[1])
    except ValueError:
        return False
    salt, expected = parts[2], parts[3]
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations
    )
    return hmac.compare_digest(digest.hex(), expected)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Hash a /watch login password for config/watch_users.yaml"
    )
    parser.add_argument("password", nargs="?", help="Password (prompted if omitted)")
    args = parser.parse_args(argv)
    password = args.password if args.password is not None else getpass.getpass("Password: ")
    try:
        print(hash_password(password))
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
