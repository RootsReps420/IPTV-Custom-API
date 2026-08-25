"""HTTP surface for the whole product (status UI, owner APIs, History, Watch).

Public (no login): `/`, `/history`, `/api/public`, `/api/history`, `/static`, `/key`
Owner (Caddy basicauth): `/owner`, `/api/status`, `/api/switch`, `/api/switch-back`
Watch (app cookie): `/watch`, `/api/watch/*`, `/api/player/*` — registered in watch.py

The app binds 127.0.0.1:8787 in production; Caddy terminates HTTPS.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
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


def create_app(monitor: Monitor) -> FastAPI:
    """Build the FastAPI app. Watch routes register first; /static must mount last."""
    app = FastAPI(title="IPTV Portal Monitor", docs_url=None, redoc_url=None)
    app.state.monitor = monitor
    app.state.watch = WatchService(monitor.root)
    register_watch(app, STATIC_DIR)

    @app.get("/api/status")
    async def status() -> dict:
        """Owner JSON: playlists, Current DNS, full events. Behind Caddy basicauth."""
        return monitor.shared.snapshot()

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
    import uvicorn

    config = uvicorn.Config(
        create_app(monitor),
        host=host,
        port=port,
        log_level="warning",
        access_log=False,
        log_config=None,
    )
    server = uvicorn.Server(config)
    logger.info("Dashboard listening on http://%s:%s", host, port)
    await server.serve()
