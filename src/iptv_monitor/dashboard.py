"""HTTP surface for the whole product (status UI, owner APIs, History, Watch).

Dashboard sign-in is in the app (dash_auth.py, config/dashboard_users.yaml), not Caddy:
  `/` is the sign-in page when signed out and the monitor once signed in.
  Owner (dan): everything — `/owner`, `/key`, `/api/status`, `/api/switch`, `/api/switch-back`,
  `/api/kick-watch`, `/api/live-groups`, plus the viewer pages.
  Viewer (Steve): `/` and `/history` only (`/api/public`, `/api/history`, `/api/session`).
  Public: `/healthz`, `/login`, `/logout`, `/static`, and Watch below.
Watch (app cookie): `/watch`, `/api/watch/*`, `/api/player/*` — registered in watch.py
`/api/watch/me` requires a session cookie (401 if signed out).
iOS native HLS may omit cookies; media uses signed `k` query as well.
`/api/status` includes in-memory /watch sessions (not the public snapshot).
POST `/api/status` with `{kick: true, username}` also signs a Watch user out (owner-only).

The app binds 127.0.0.1:8787 in production; Caddy terminates HTTPS.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from iptv_monitor import dash_auth
from iptv_monitor.monitor import Monitor, SwitchError
from iptv_monitor.player_auth import (
    clear_login_failures,
    client_ip,
    record_login_failure,
    refuse_locked_login,
)
from iptv_monitor.watch import WatchService, register_watch

logger = logging.getLogger("iptv_monitor.dashboard")
STATIC_DIR = Path(__file__).resolve().parent / "static"
# Pages always revalidate (cheap 304 via ETag) so a deploy never pairs stale HTML with new CSS/JS.
# `/` serves the sign-in page or the monitor depending on the cookie, hence Vary.
PAGE_HEADERS = {"Cache-Control": "no-cache", "Vary": "Cookie"}


def _page(name: str) -> FileResponse:
    return FileResponse(STATIC_DIR / name, headers=PAGE_HEADERS)


class SwitchBody(BaseModel):
    playlist_id: str = Field(min_length=1)
    target_url: str | None = None


class KickWatchBody(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    kick: bool = False


class LiveGroupBody(BaseModel):
    name: str = Field(default="", max_length=200)
    category_id: str = Field(default="", max_length=80)
    enabled: bool


class LoginBody(BaseModel):
    username: str = Field(default="", max_length=80)
    password: str = Field(default="", max_length=256)
    remember: bool = False
    next: str = Field(default="/", max_length=300)


def create_app(monitor: Monitor) -> FastAPI:
    """Build the FastAPI app. Watch routes register first; /static must mount last."""
    app = FastAPI(title="IPTV Portal Monitor", docs_url=None, redoc_url=None, openapi_url=None)
    # Default-deny gate for every dashboard path (see dash_auth.required_role).
    app.add_middleware(dash_auth.DashboardAuthMiddleware, root=monitor.root)
    app.state.monitor = monitor
    app.state.watch = WatchService(monitor.root)
    register_watch(app, STATIC_DIR)

    @app.get("/api/status")
    async def status(request: Request) -> dict:
        """Owner JSON: playlists, Current DNS, full events, /watch sessions. Owner-only (dash_auth)."""
        data = monitor.shared.snapshot()
        watch = getattr(request.app.state, "watch", None)
        if watch is not None:
            data["watch"] = await watch.owner_watch()
            counts = data.setdefault("counts", {})
            counts["watch_online"] = data["watch"].get("online", 0)
            counts["watch_playing"] = data["watch"].get("playing", 0)
        return data

    @app.post("/api/status")
    @app.post("/api/kick-watch")
    async def kick_watch_user(request: Request, body: KickWatchBody) -> dict:
        """Sign a /watch user out on every device. Owner-only (dash_auth)."""
        if not body.kick:
            raise HTTPException(status_code=400, detail="Set kick: true to sign a Watch user out.")
        watch = getattr(request.app.state, "watch", None)
        if watch is None:
            raise HTTPException(status_code=503, detail="Watch is not running.")
        return await watch.kick_user(body.username)

    @app.get("/api/live-groups")
    async def live_groups(request: Request) -> dict:
        """All Magnum live groups with ON/OFF for /watch. Owner-only (dash_auth)."""
        watch = getattr(request.app.state, "watch", None)
        if watch is None:
            raise HTTPException(status_code=503, detail="Watch is not running.")
        return watch.guide.owner_live_groups()

    @app.post("/api/live-groups")
    async def set_live_group(request: Request, body: LiveGroupBody) -> dict:
        """Show or hide one live group on /watch immediately (YAML, no restart)."""
        if not body.name.strip() and not body.category_id.strip():
            raise HTTPException(status_code=400, detail="Set name or category_id.")
        watch = getattr(request.app.state, "watch", None)
        if watch is None:
            raise HTTPException(status_code=503, detail="Watch is not running.")
        try:
            return watch.guide.set_owner_live_group(
                name=body.name,
                category_id=body.category_id,
                enabled=body.enabled,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Unknown live group.") from exc

    @app.get("/api/public")
    async def public_status() -> dict:
        """Standby pool only — no live DNS, no playlist names."""
        return monitor.shared.public_snapshot()

    @app.get("/api/history")
    async def history() -> dict:
        """90-day down counts per pool URL (aggregates, not raw timestamps)."""
        return monitor.history_snapshot(owner=False)

    @app.post("/api/switch")
    async def switch_playlist(body: SwitchBody) -> dict:
        """Manual failover. Omit target_url for best healthy standby; set it to pick one."""
        try:
            return await monitor.manual_switch(body.playlist_id, target_url=body.target_url)
        except SwitchError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    @app.post("/api/switch-back")
    async def switch_back_playlist(body: SwitchBody) -> dict:
        """Revert to the DNS stored in manual_from_dns after a health check."""
        try:
            return await monitor.manual_revert(body.playlist_id)
        except SwitchError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    @app.get("/healthz")
    async def healthz() -> dict:
        """Liveness probe for deploy/update.sh. Never behind a login, returns no data."""
        return {"ok": True}

    @app.post("/login")
    async def login(request: Request, body: LoginBody) -> JSONResponse:
        """Dashboard sign-in. Same lockout as Watch (per IP + per name), names kept separate."""
        ip = client_ip(request)
        limit_key = f"dash:{body.username.strip().casefold()}"
        refuse_locked_login(ip=ip, username=limit_key)
        user = await dash_auth.authenticate(monitor.root, body.username, body.password)
        if user is None:
            record_login_failure(ip=ip, username=limit_key)
            logger.info("Dashboard sign-in failed for %r from %s", body.username[:40], ip)
            raise HTTPException(status_code=401, detail="Wrong username or password.")
        clear_login_failures(ip=ip, username=limit_key)
        logger.info("Dashboard sign-in: %s (%s) from %s", user.username, user.role, ip)
        response = JSONResponse(
            {"ok": True, "next": dash_auth.safe_next(body.next, user), "username": user.username, "role": user.role}
        )
        dash_auth.issue_cookie(response, request, monitor.root, user, body.remember)
        return response

    @app.post("/logout")
    async def logout() -> JSONResponse:
        response = JSONResponse({"ok": True})
        dash_auth.clear_cookie(response)
        return response

    @app.get("/api/session")
    async def session(request: Request) -> dict:
        """Who is signed in (sidebar name + which nav links to show)."""
        user = dash_auth.current_user(request, monitor.root)
        return {"username": user.username, "role": user.role} if user else {}

    @app.get("/")
    async def index(request: Request) -> FileResponse:
        """Sign-in page when signed out; the public monitor once signed in (JS: /api/public)."""
        if dash_auth.current_user(request, monitor.root) is None:
            return _page("landing.html")
        return _page("index.html")

    @app.get("/owner")
    async def owner() -> FileResponse:
        """Owner view of the same page (dash_auth: owner role only)."""
        return _page("index.html")

    @app.get("/key")
    async def key() -> FileResponse:
        return _page("key.html")

    @app.get("/history")
    async def history_page() -> FileResponse:
        return _page("history.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


async def serve_dashboard(monitor: Monitor, host: str, port: int) -> None:
    """Run uvicorn beside the monitor loop. access_log off to avoid leaking stream URLs."""
    import asyncio

    import uvicorn

    from iptv_monitor.player_sync import WatchSyncer

    app = create_app(monitor)
    syncer = WatchSyncer(monitor.root, app.state.watch.guide)
    app.state.watch_syncer = syncer
    monitor.watch_syncer = syncer
    monitor.watch_service = app.state.watch
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="warning",
        access_log=False,
        log_config=None,
    )
    server = uvicorn.Server(config)
    logger.info("Dashboard listening on http://%s:%s", host, port)
    await asyncio.gather(server.serve(), syncer.run_forever())
