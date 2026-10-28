"""Dashboard sign-in for /, /owner, /history, /key and their APIs (replaces Caddy basicauth).

Users live in config/dashboard_users.yaml (gitignored):
    users:
      - username: dan
        role: owner            # owner = everything; viewer = Monitor + History only
        password_hash: ...     # pbkdf2_sha256$... (main.py dashboard-user) or bcrypt $2a$...
bcrypt hashes come from the old Caddy basicauth lines (main.py dashboard-user --import-caddy),
so existing passwords keep working.

Session: signed HttpOnly cookie `dash_session` (same secret as Watch, its own salt). "Keep me
signed in" lasts 30 days, otherwise 12 hours. The role is re-read from the YAML on every request,
so removing a user or changing a role takes effect at once. Missing YAML = nobody can sign in.

Access is by path and default-deny, mirroring the Caddyfile it replaces:
  public : / (sign-in page when signed out), /login, /logout, /healthz, /static/*,
           /watch*, /api/watch/*, /api/player/* (Watch has its own login)
  viewer : /history, /api/public, /api/history, /api/session
  owner  : everything else (/owner, /key, /api/status, /api/switch*, /api/live-groups, ...)
Writes to protected paths must also be same-origin (Origin header), on top of SameSite=Lax.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import getpass
import json
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlsplit

from itsdangerous import BadSignature, URLSafeTimedSerializer
from ruamel.yaml import YAML
from starlette.requests import Request
from starlette.responses import Response

from iptv_monitor.config import resolve_paths
from iptv_monitor.hash_password import hash_password, validate_watch_password, verify_password
from iptv_monitor.player_auth import cookie_secure, session_secret

logger = logging.getLogger("iptv_monitor.dash_auth")

COOKIE = "dash_session"
REMEMBER_MAX_AGE = 30 * 24 * 3600
SHORT_MAX_AGE = 12 * 3600
ROLES = ("owner", "viewer")
USERS_FILE = "dashboard_users.yaml"

PUBLIC_EXACT = {"/", "/login", "/logout", "/healthz", "/favicon.ico"}
PUBLIC_TREES = ("/static", "/watch", "/api/watch", "/api/player")
VIEWER_EXACT = {"/api/public", "/api/history", "/api/session"}
VIEWER_TREES = ("/history",)
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@dataclass(frozen=True)
class DashUser:
    username: str
    role: str
    password_hash: str = ""

    @property
    def is_owner(self) -> bool:
        return self.role == "owner"


def _under(path: str, tree: str) -> bool:
    return path == tree or path.startswith(tree + "/")


def required_role(path: str) -> str:
    """'public', 'viewer' or 'owner' for a request path. Unknown paths are owner-only."""
    if path in PUBLIC_EXACT or any(_under(path, tree) for tree in PUBLIC_TREES):
        return "public"
    if path in VIEWER_EXACT or any(_under(path, tree) for tree in VIEWER_TREES):
        return "viewer"
    return "owner"


# ---------- Users ----------

_users_lock = threading.Lock()
_users_cache: dict[Path, tuple[float, dict[str, DashUser]]] = {}


def users_path(root: Path | None) -> Path:
    return resolve_paths(root).config_dir / USERS_FILE


def load_users(root: Path | None) -> dict[str, DashUser]:
    """Casefolded username -> user. Re-read when the file changes; broken file = no users."""
    path = users_path(root)
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        return {}
    with _users_lock:
        cached = _users_cache.get(path)
        if cached and cached[0] == mtime:
            return cached[1]
        users: dict[str, DashUser] = {}
        try:
            data = YAML(typ="safe").load(path.read_text(encoding="utf-8")) or {}
            for item in data.get("users") or []:
                name = str(item.get("username") or "").strip()
                role = str(item.get("role") or "viewer").strip().lower()
                stored = str(item.get("password_hash") or "").strip()
                if name and role in ROLES and stored:
                    users[name.casefold()] = DashUser(name, role, stored)
        except Exception as exc:  # noqa: BLE001
            logger.error("Could not read %s: %s", path, exc)
            users = {}
        _users_cache[path] = (mtime, users)
        return users


def _check_hash(password: str, stored: str) -> bool:
    """bcrypt ($2a$/$2b$, from Caddy) or pbkdf2_sha256 (hash_password.py)."""
    if stored.startswith("$2"):
        import bcrypt

        try:
            return bcrypt.checkpw(password.encode("utf-8"), stored.encode("ascii"))
        except ValueError:
            return False
    return verify_password(password, stored)


async def authenticate(root: Path | None, username: str, password: str) -> DashUser | None:
    """Check a password off the event loop (bcrypt cost 14 takes ~1s, streams must not stall)."""
    users = load_users(root)
    if not password or len(password) > 256:
        return None
    user = users.get((username or "").strip().casefold())
    if user is None:
        # Spend the same time on unknown names so response time does not reveal valid ones.
        decoy = next(iter(users.values()), None)
        if decoy is not None:
            await asyncio.to_thread(_check_hash, password, decoy.password_hash)
        return None
    ok = await asyncio.to_thread(_check_hash, password, user.password_hash)
    return user if ok else None


# ---------- Session cookie ----------


def _serializer(root: Path | None) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(session_secret(root), salt="iptv-dashboard-session")


def issue_cookie(response: Response, request: Request, root: Path | None, user: DashUser, remember: bool) -> None:
    token = _serializer(root).dumps({"u": user.username, "rm": bool(remember)})
    response.set_cookie(
        COOKIE,
        token,
        max_age=REMEMBER_MAX_AGE if remember else None,
        httponly=True,
        secure=cookie_secure(request),
        samesite="lax",
        path="/",
    )


def clear_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")


def user_from_token(root: Path | None, token: str) -> DashUser | None:
    if not token:
        return None
    try:
        payload, issued = _serializer(root).loads(token, max_age=REMEMBER_MAX_AGE, return_timestamp=True)
    except BadSignature:
        return None
    if not isinstance(payload, dict):
        return None
    if not payload.get("rm") and time.time() - issued.timestamp() > SHORT_MAX_AGE:
        return None
    return load_users(root).get(str(payload.get("u") or "").casefold())


def current_user(request: Request, root: Path | None) -> DashUser | None:
    return user_from_token(root, request.cookies.get(COOKIE, ""))


def safe_next(target: str, user: DashUser) -> str:
    """Where to land after sign-in: a same-site path the user may open, else the monitor."""
    target = (target or "").strip()
    if not target.startswith("/") or target.startswith("//") or "\\" in target:
        return "/"
    path = urlsplit(target).path or "/"
    if path in {"/login", "/logout"} or (required_role(path) == "owner" and not user.is_owner):
        return "/"
    return target


# ---------- ASGI gate ----------


def _header(scope: dict, name: bytes) -> str:
    for key, value in scope.get("headers") or []:
        if key == name:
            return value.decode("latin-1")
    return ""


def _cookie_from_scope(scope: dict) -> str:
    for key, value in scope.get("headers") or []:
        if key != b"cookie":
            continue
        for part in value.decode("latin-1").split(";"):
            name, _, raw = part.strip().partition("=")
            if name == COOKIE:
                return raw.strip().strip('"')
    return ""


def _same_origin(scope: dict) -> bool:
    origin = _header(scope, b"origin")
    if not origin:
        return True  # non-browser clients; the session cookie is still required
    host = _header(scope, b"x-forwarded-host") or _header(scope, b"host")
    return urlsplit(origin).netloc.lower() == host.split(",")[0].strip().lower()


async def _respond(send, status: int, headers: list[tuple[bytes, bytes]], body: bytes) -> None:
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


async def _deny(scope: dict, send, status: int, detail: str) -> None:
    path = scope.get("path") or "/"
    if path.startswith("/api/") or scope.get("method") not in SAFE_METHODS:
        body = json.dumps({"detail": detail}).encode()
        await _respond(send, status, [(b"content-type", b"application/json"), (b"cache-control", b"no-store")], body)
        return
    # Pages: signed out -> sign-in page (then back here); wrong role -> the monitor.
    if status == 401:
        query = scope.get("query_string", b"").decode("latin-1")
        target = path + (f"?{query}" if query else "")
        location = "/?next=" + quote(target, safe="")
    else:
        location = "/"
    await _respond(send, 303, [(b"location", location.encode("latin-1")), (b"cache-control", b"no-store")], b"")


class DashboardAuthMiddleware:
    """Pure ASGI (not BaseHTTPMiddleware) so public routes — long Watch streams — pass straight through."""

    def __init__(self, app, root: Path | None = None) -> None:
        self.app = app
        self.root = root

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        need = required_role(scope.get("path") or "/")
        if need == "public":
            await self.app(scope, receive, send)
            return
        user = user_from_token(self.root, _cookie_from_scope(scope))
        if user is None:
            await _deny(scope, send, 401, "Sign in to the dashboard first.")
            return
        if need == "owner" and not user.is_owner:
            await _deny(scope, send, 403, "This page is for the owner account.")
            return
        if scope.get("method") not in SAFE_METHODS and not _same_origin(scope):
            await _deny(scope, send, 403, "Cross-site request refused.")
            return
        await self.app(scope, receive, send)


# ---------- CLI: main.py dashboard-user ----------


def parse_caddy_users(text: str) -> list[DashUser]:
    """Users from Caddy `basicauth [@matcher] { name base64-bcrypt }` blocks.

    Anyone in a block whose matcher is `owner` (or an unnamed block) is an owner; the rest are viewers.
    """
    found: dict[str, DashUser] = {}
    block: str | None = None
    for line in text.splitlines():
        tokens = line.split("#", 1)[0].split()
        if not tokens:
            continue
        if tokens[0] in {"basicauth", "basic_auth"} and tokens[-1] == "{":
            # `basicauth [@matcher] [hash-algorithm] {`
            matcher = next((token for token in tokens[1:-1] if token.startswith("@")), "")
            block = matcher.lstrip("@")
            continue
        if block is None:
            continue
        if tokens == ["}"]:
            block = None
            continue
        if len(tokens) != 2:
            continue
        name, value = tokens
        stored = value
        if not value.startswith("$2"):
            try:
                stored = base64.b64decode(value, validate=True).decode("ascii")
            except ValueError:
                continue
        if not stored.startswith("$2"):
            continue
        owner = block in {"owner", ""} or found.get(name.casefold(), DashUser(name, "viewer")).is_owner
        found[name.casefold()] = DashUser(name, "owner" if owner else "viewer", stored)
    return list(found.values())


def _write_users(path: Path, users: list[DashUser]) -> None:
    yaml = YAML()
    yaml.default_flow_style = False
    body = {
        "users": [
            {"username": user.username, "role": user.role, "password_hash": user.password_hash}
            for user in sorted(users, key=lambda u: (u.role != "owner", u.username.casefold()))
        ]
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".yaml.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        handle.write("# Dashboard sign-in. Manage with: main.py dashboard-user (never commit this file).\n")
        yaml.dump(body, handle)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)


def add_cli_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("username", nargs="?", help="Add this user, or change their password / role")
    parser.add_argument("--role", choices=ROLES, help="owner = everything; viewer = Monitor + History")
    parser.add_argument("--remove", action="store_true", help="Delete the user")
    parser.add_argument("--list", action="store_true", help="Show users and roles (no hashes)")
    parser.add_argument(
        "--import-caddy",
        metavar="FILE",
        help="Copy users + bcrypt hashes from a Caddyfile's basicauth blocks ('-' = stdin)",
    )


def run_cli(args: argparse.Namespace, root: Path | None = None) -> int:
    """main.py dashboard-user: add / re-password / remove / list users, or import them from Caddy."""
    path = users_path(root)
    current = {key: user for key, user in load_users(root).items()}

    if args.list:
        if not current:
            print(f"No users in {path}")
        for user in current.values():
            print(f"{user.username:20} {user.role}")
        return 0

    if args.import_caddy:
        text = sys.stdin.read() if args.import_caddy == "-" else Path(args.import_caddy).read_text(encoding="utf-8")
        imported = parse_caddy_users(text)
        if not imported:
            print("No basicauth users found.", file=sys.stderr)
            return 1
        for user in imported:
            current[user.username.casefold()] = user
        _write_users(path, list(current.values()))
        for user in imported:
            print(f"Imported {user.username} ({user.role})")
        return 0

    if not args.username:
        print("Give a username, or use --list / --import-caddy. See: main.py dashboard-user -h", file=sys.stderr)
        return 1
    key = args.username.strip().casefold()
    existing = current.get(key)

    if args.remove:
        if existing is None:
            print(f"No user {args.username}", file=sys.stderr)
            return 1
        del current[key]
        _write_users(path, list(current.values()))
        print(f"Removed {existing.username}")
        return 0

    role = args.role or (existing.role if existing else "viewer")
    password = getpass.getpass(f"New password for {args.username}: ")
    problem = validate_watch_password(password, username=args.username)
    if problem:
        print(problem, file=sys.stderr)
        return 1
    if getpass.getpass("Again: ") != password:
        print("Passwords did not match.", file=sys.stderr)
        return 1
    name = existing.username if existing else args.username.strip()
    current[key] = DashUser(name, role, hash_password(password))
    _write_users(path, list(current.values()))
    print(f"{'Updated' if existing else 'Added'} {name} ({role})")
    return 0
