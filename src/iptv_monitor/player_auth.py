"""Friend logins for /watch. Xtream credentials never go in the cookie.

Signed HttpOnly cookie `watch_session` proves the site user. Secret lives in
WATCH_SESSION_SECRET or state/watch_secret.txt. Login attempts are rate-limited
in memory. HLS fetch tickets live in player_proxy, not in this cookie.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from dataclasses import dataclass
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
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


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


def media_serializer(root: Path | None) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(session_secret(root), salt="iptv-watch-media")


LOGIN_WINDOW_S = 15 * 60
LOGIN_MAX_FAILS_IP = 10
LOGIN_MAX_FAILS_USER = 8
_login_fails: dict[str, list[float]] = {}


def _fail_key(kind: str, value: str) -> str:
    return f"{kind}:{(value or '').strip()[:80] or 'unknown'}"


def _prune_fail_times(times: list[float], now: float) -> list[float]:
    cutoff = now - LOGIN_WINDOW_S
    return [stamp for stamp in times if stamp > cutoff]


def login_retry_after(*, ip: str, username: str = "") -> int:
    """Seconds until another login attempt is allowed. 0 if the attempt may proceed."""
    now = time.time()
    waits: list[int] = []
    checks = [(_fail_key("ip", ip), LOGIN_MAX_FAILS_IP)]
    if (username or "").strip():
        checks.append((_fail_key("user", username), LOGIN_MAX_FAILS_USER))
    for key, limit in checks:
        times = _prune_fail_times(_login_fails.get(key, []), now)
        if times:
            _login_fails[key] = times
        else:
            _login_fails.pop(key, None)
        if len(times) < limit:
            continue
        waits.append(max(1, int(times[0] + LOGIN_WINDOW_S - now)))
    return max(waits) if waits else 0


def record_login_failure(*, ip: str, username: str = "") -> None:
    now = time.time()
    keys = [_fail_key("ip", ip)]
    if (username or "").strip():
        keys.append(_fail_key("user", username))
    for key in keys:
        times = _prune_fail_times(_login_fails.get(key, []), now)
        times.append(now)
        _login_fails[key] = times


def clear_login_failures(*, ip: str, username: str = "") -> None:
    _login_fails.pop(_fail_key("ip", ip), None)
    _login_fails.pop(_fail_key("user", username), None)


def refuse_locked_login(*, ip: str, username: str = "") -> None:
    retry = login_retry_after(ip=ip, username=username)
    if retry <= 0:
        return
    raise HTTPException(
        status_code=429,
        detail="Too many sign-in attempts. Try again in a few minutes.",
        headers={"Retry-After": str(retry)},
    )


MEDIA_TOKEN_MAX_AGE = 8 * 3600


def mint_media_token(root: Path, username: str) -> str:
    """Short-lived token for <video> HLS on iOS, which often omits cookies."""
    return media_serializer(root).dumps({"u": username})


def username_from_media_token(root: Path, token: str) -> str | None:
    raw = (token or "").strip()
    if not raw:
        return None
    try:
        loaded = media_serializer(root).loads(
            raw, max_age=MEDIA_TOKEN_MAX_AGE, return_timestamp=True
        )
    except (BadSignature, SignatureExpired, TypeError, ValueError):
        return None
    if isinstance(loaded, tuple) and len(loaded) == 2:
        payload, stamped = loaded
        issued = stamped.timestamp() if hasattr(stamped, "timestamp") else float(stamped)
    else:
        payload, issued = loaded, 0.0
    if not isinstance(payload, dict):
        return None
    name = str(payload.get("u") or "").strip()
    if not name or is_kicked(name, issued):
        return None
    return name


def cookie_secure(request: Request) -> bool:
    """Secure flag on HTTPS (including Caddy's X-Forwarded-Proto). HTTP local dashboard stays off."""
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "").lower()
    return proto == "https"


@dataclass
class WatchSession:
    username: str
    session_id: str = ""
    issued_at: float = 0


def client_ip(request: Request) -> str:
    """Client IP. Trust X-Forwarded-For because the app only listens on loopback."""
    forwarded = (request.headers.get("x-forwarded-for") or "").strip()
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    host = request.client.host if request.client else ""
    return (host or "")[:64]


def set_session(
    response: Response,
    request: Request,
    root: Path,
    username: str,
    *,
    session_id: str | None = None,
    issued_at: int | None = None,
) -> str:
    sid = (session_id or "").strip() or uuid.uuid4().hex
    issued = float(issued_at or time.time())
    token = _serializer(root).dumps({"u": username, "sid": sid, "t": issued})
    response.set_cookie(
        COOKIE,
        token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=cookie_secure(request),
        samesite="lax",
        path="/",
    )
    return sid


def clear_session(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")


# Username -> unix time. Cookies and media tokens issued at or before this are dead
# until the person signs in again. In-memory: a process restart clears kicks.
_kicked_at: dict[str, float] = {}


def kick_username(username: str) -> float:
    """Invalidate every Watch cookie/token for this site user."""
    name = (username or "").strip()
    if not name:
        raise ValueError("username")
    at = time.time()
    _kicked_at[name] = at
    return at


def is_kicked(username: str, issued_at: float) -> bool:
    name = (username or "").strip()
    if not name:
        return False
    at = _kicked_at.get(name)
    if at is None:
        return False
    try:
        issued = float(issued_at or 0)
    except (TypeError, ValueError):
        issued = 0.0
    return issued < at


def read_session(request: Request, root: Path) -> WatchSession | None:
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
    if not name:
        return None
    try:
        issued = float(payload.get("t") or 0)
    except (TypeError, ValueError):
        issued = 0.0
    if is_kicked(name, issued):
        return None
    return WatchSession(
        username=name,
        session_id=str(payload.get("sid") or "").strip(),
        issued_at=issued,
    )


def current_username(request: Request, root: Path) -> str | None:
    session = read_session(request, root)
    return session.username if session else None


def require_username(request: Request, root: Path) -> str:
    name = current_username(request, root)
    if not name:
        raise HTTPException(status_code=401, detail="Sign in to watch.")
    return name


def require_player_user(request: Request, root: Path) -> str:
    """Cookie first; media token `k` for iOS native HLS (AVPlayer skips cookies)."""
    name = current_username(request, root)
    if name:
        return name
    token = (request.query_params.get("k") or "").strip()
    name = username_from_media_token(root, token)
    if not name:
        raise HTTPException(status_code=401, detail="Sign in to watch.")
    return name
