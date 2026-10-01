"""HTTP surface for the whole product (status UI, owner APIs, History, Watch).

Open without Caddy: `/watch`, `/api/watch/*`, `/api/player/*`, `/static`
  (Watch still uses the app cookie / site login).
Caddy `dan` basicauth: `/`, `/owner`, `/history`, `/key`, `/api/public`,
  `/api/history`, `/api/status`, `/api/switch`, `/api/switch-back`, `/api/kick-watch`,
  `/api/live-groups`
Caddy `Steve` (if configured): `/` and `/history` only (`/api/public`, `/api/history`).
  Not `/key`, `/owner`, or owner APIs. Not a /watch user.
Watch (app cookie): `/watch`, `/api/watch/*`, `/api/player/*` — registered in watch.py
`/api/watch/me` requires a session cookie (401 if signed out).
iOS native HLS may omit cookies; media uses signed `k` query as well.
`/api/status` includes in-memory /watch sessions (not the public snapshot).
POST `/api/status` with `{kick: true, username}` also signs a Watch user out (same Caddy path).

The app binds 127.0.0.1:8787 in production; Caddy terminates HTTPS.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from iptv_monitor.monitor import Monitor, SwitchError
from iptv_monitor.watch import WatchService, register_watch

logger = logging.getLogger("iptv_monitor.dashboard")
STATIC_DIR = Path(__file__).resolve().parent / "static"


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


def create_app(monitor: Monitor) -> FastAPI:
    """Build the FastAPI app. Watch routes register first; /static must mount last."""
    app = FastAPI(title="IPTV Portal Monitor", docs_url=None, redoc_url=None)
    app.state.monitor = monitor
    app.state.watch = WatchService(monitor.root)
    register_watch(app, STATIC_DIR)

    @app.get("/api/status")
    async def status(request: Request) -> dict:
        """Owner JSON: playlists, Current DNS, full events, /watch sessions. Behind Caddy basicauth."""
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
        """Sign a /watch user out on every device. Behind Caddy (POST /api/status is already owner-only)."""
        if not body.kick:
            raise HTTPException(status_code=400, detail="Set kick: true to sign a Watch user out.")
        watch = getattr(request.app.state, "watch", None)
        if watch is None:
            raise HTTPException(status_code=503, detail="Watch is not running.")
        return await watch.kick_user(body.username)

    @app.get("/api/live-groups")
    async def live_groups(request: Request) -> dict:
        """All Magnum live groups with ON/OFF for /watch. Owner-only (Caddy)."""
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

    @app.get("/")
    async def index() -> FileResponse:
        """Public monitor. Same HTML as /owner; JS hides playlists unless owner JSON."""
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/owner")
    async def owner() -> FileResponse:
        """Owner view of the same page (Caddy login)."""
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/key")
    async def key() -> FileResponse:
        return FileResponse(STATIC_DIR / "key.html")

    @app.get("/history")
    async def history_page() -> FileResponse:
        return FileResponse(STATIC_DIR / "history.html")

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
