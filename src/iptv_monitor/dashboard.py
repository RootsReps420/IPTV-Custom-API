"""Local FastAPI dashboard. Polls SharedState; does not run checks itself."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from iptv_monitor.monitor import SharedState

logger = logging.getLogger("iptv_monitor.dashboard")
STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(state: SharedState) -> FastAPI:
    app = FastAPI(title="IPTV Portal Monitor", docs_url=None, redoc_url=None)
    app.state.shared = state

    @app.get("/api/status")
    async def status() -> dict:
        return state.snapshot()

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


async def serve_dashboard(state: SharedState, host: str, port: int) -> None:
    import uvicorn

    config = uvicorn.Config(
        create_app(state),
        host=host,
        port=port,
        log_level="warning",
        access_log=False,
        log_config=None,
    )
    server = uvicorn.Server(config)
    logger.info("Dashboard listening on http://%s:%s", host, port)
    await server.serve()
