"""Friend logins for /watch. Xtream credentials never go in the cookie.

Signed HttpOnly cookie `watch_session` proves the site user. Secret lives in
WATCH_SESSION_SECRET or state/watch_secret.txt. A second serializer salt signs
HLS segment tokens so /api/player/fetch is not an open proxy.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import HTTPException, Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel, Field
from ruamel.yaml import YAML

from iptv_monitor.config import resolve_paths
from iptv_monitor.hash_password import verify_password

logger = logging.getLogger("iptv_monitor.player_auth")

COOKIE = "watch_session"
SESSION_MAX_AGE = 14 * 24 * 3600
_secret_cache: str | None = None


class WatchUser(BaseModel):
    name: str
    password_hash: str = ""


class WatchUsersFile(BaseModel):
    users: list[WatchUser] = Field(default_factory=list)


class LoginBody(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


def _yaml() -> YAML:
    return YAML(typ="safe")


def load_watch_users(path: Path) -> list[WatchUser]:
    if not path.exists():
        return []
    try:
        raw = _yaml().load(path.read_text(encoding="utf-8")) or {}
        return WatchUsersFile.model_validate(raw).users
    except Exception:
        logger.warning("Could not read watch users from %s", path)
        return []


def authenticate(path: Path, username: str, password: str) -> str | None:
    wanted = username.strip()
    for user in load_watch_users(path):
        if user.name.strip() != wanted:
            continue
        if not user.password_hash.strip():
            return None
        if verify_password(password, user.password_hash.strip()):
            return user.name.strip()
    return None


def session_secret(root: Path | None) -> str:
    """Env WATCH_SESSION_SECRET, else persist a random secret under state/ (gitignored)."""
    global _secret_cache
    env = os.getenv("WATCH_SESSION_SECRET", "").strip()
    if env:
        return env
    if _secret_cache:
        return _secret_cache
    path = resolve_paths(root).root / "state" / "watch_secret.txt"
    if path.exists():
        value = path.read_text(encoding="utf-8").strip()
        if value:
            _secret_cache = value
            return value
    path.parent.mkdir(parents=True, exist_ok=True)
    value = os.urandom(32).hex()
    path.write_text(value + "\n", encoding="utf-8")
    _secret_cache = value
    return value


def _serializer(root: Path | None) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(session_secret(root), salt="iptv-watch-session")


def fetch_serializer(root: Path | None) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(session_secret(root), salt="iptv-watch-fetch")


def cookie_secure(request: Request) -> bool:
    """Secure flag on HTTPS (including Caddy's X-Forwarded-Proto). HTTP local dashboard stays off."""
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "").lower()
    return proto == "https"


def set_session(response: Response, request: Request, root: Path, username: str) -> None:
    token = _serializer(root).dumps({"u": username})
    response.set_cookie(
        COOKIE,
        token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=cookie_secure(request),
        samesite="lax",
        path="/",
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")


def current_username(request: Request, root: Path) -> str | None:
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    try:
        payload = _serializer(root).loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired, TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    name = str(payload.get("u") or "").strip()
    return name or None


def require_username(request: Request, root: Path) -> str:
    name = current_username(request, root)
    if not name:
        raise HTTPException(status_code=401, detail="Sign in to watch.")
    return name
