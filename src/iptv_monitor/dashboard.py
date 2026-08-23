"""Local FastAPI dashboard. Owner switch actions go through Monitor."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from iptv_monitor.monitor import Monitor, SwitchError

logger = logging.getLogger("iptv_monitor.dashboard")
STATIC_DIR = Path(__file__).resolve().parent / "static"


class SwitchBody(BaseModel):
    playlist_id: str = Field(min_length=1)


def create_app(monitor: Monitor) -> FastAPI:
    app = FastAPI(title="IPTV Portal Monitor", docs_url=None, redoc_url=None)
    app.state.monitor = monitor

    @app.get("/api/status")
    async def status() -> dict:
        return monitor.shared.snapshot()

    @app.get("/api/public")
    async def public_status() -> dict:
        return monitor.shared.public_snapshot()

    @app.post("/api/switch")
    async def switch_playlist(body: SwitchBody) -> dict:
        try:
            return await monitor.manual_switch(body.playlist_id)
        except SwitchError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    @app.post("/api/switch-back")
    async def switch_back_playlist(body: SwitchBody) -> dict:
        try:
            return await monitor.manual_revert(body.playlist_id)
        except SwitchError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/owner")
    async def owner() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/key")
    async def key() -> FileResponse:
        return FileResponse(STATIC_DIR / "key.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


async def serve_dashboard(monitor: Monitor, host: str, port: int) -> None:
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
