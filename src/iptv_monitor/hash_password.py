"""Hash / verify /watch site passwords (not Xtream panel passwords).

Stored form: pbkdf2_sha256$iterations$salt$hex
CLI: python -m iptv_monitor.hash_password
     python main.py watch-hash
Paste the printed line into config/watch_users.yaml as password_hash.
Never store the password itself.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import hmac
import os
import re
import sys

SCHEME = "pbkdf2_sha256"
ITERATIONS = 120_000
PASSWORD_MIN_LEN = 8
PASSWORD_MAX_LEN = 128
_HAS_LOWER = re.compile(r"[a-z]")
_HAS_UPPER = re.compile(r"[A-Z]")
_HAS_DIGIT = re.compile(r"[0-9]")
_HAS_SPECIAL = re.compile(r"[^A-Za-z0-9\s]")


def hash_password(password: str, *, iterations: int = ITERATIONS) -> str:
    """Return a salted pbkdf2 string safe to store in watch_users.yaml."""
    if not password:
        raise ValueError("Password is empty")
    salt = os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations
    )
    return f"{SCHEME}${iterations}${salt}${digest.hex()}"


def validate_watch_password(password: str, *, username: str = "") -> str | None:
    """Return a user-facing error, or None if the password meets Watch rules."""
    if not password:
        return "Enter a new password."
    if len(password) < PASSWORD_MIN_LEN:
        return f"Password must be at least {PASSWORD_MIN_LEN} characters."
    if len(password) > PASSWORD_MAX_LEN:
        return f"Password must be at most {PASSWORD_MAX_LEN} characters."
    if not _HAS_LOWER.search(password):
        return "Password must include a lowercase letter."
    if not _HAS_UPPER.search(password):
        return "Password must include an uppercase letter."
    if not _HAS_DIGIT.search(password):
        return "Password must include a number."
    if not _HAS_SPECIAL.search(password):
        return "Password must include a special character."
    name = (username or "").strip()
    if name and password.casefold() == name.casefold():
        return "Password cannot be the same as your username."
    return None


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
