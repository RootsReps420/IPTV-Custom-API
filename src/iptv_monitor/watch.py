"""/watch login and player API routes.

Friends get a cookie after POST /api/watch/login (config/watch_users.yaml).
Catalogue JSON is sanitized Xtream player_api (no panel user/pass).
Media is same-origin /api/player/media/... which proxies the panel.

Slot heartbeats cap concurrent playback at player.yaml max_concurrent (default 5).
Watch uses config/player.yaml only. Failover playlists.yaml is never a Watch source.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from iptv_monitor.config import resolve_paths
from iptv_monitor.player_auth import (
    LoginBody,
    authenticate,
    clear_session,
    current_username,
    fetch_serializer,
    require_username,
    set_session,
)
from iptv_monitor.player_proxy import load_signed_url, panel_media_url, proxy_url
from iptv_monitor.player_guide import WatchGuide
from iptv_monitor.player_slots import SlotTracker
from iptv_monitor.player_sync import queue_watch_force
from iptv_monitor.player_xtream import XtreamCatalogue, load_player_config

logger = logging.getLogger("iptv_monitor.watch")

KINDS = {"live", "movie", "series"}


class SlotBody(BaseModel):
    play_id: str = Field(default="", max_length=80)


class SyncBody(BaseModel):
    kind: Literal["playlist", "epg"]


class WatchService:
    """Per-process Watch state: slot table, shared live guide, Xtream fallback."""
    def __init__(self, root) -> None:
        self.root = root
        self.slots = SlotTracker()
        self.guide = WatchGuide(root)
        self.catalogue = XtreamCatalogue(root, guide=self.guide)
        self._cfg = None
        self._cfg_at = 0.0

    def config(self):
        """player.yaml is tiny, but reading it on every zap adds disk I/O to TTFB."""
        now = time.monotonic()
        if self._cfg is None or now - self._cfg_at > 5.0:
            self._cfg = load_player_config(self.root)
            self._cfg_at = now
            self.slots.max_concurrent = max(1, int(self._cfg.max_concurrent or 5))
        return self._cfg

    def sync_slot_limit(self) -> None:
        self.config()


def _root(request: Request):
    """Project root. systemd does not pass --root, so WatchService.root can be None."""
    return resolve_paths(request.app.state.watch.root).root


def _svc(request: Request) -> WatchService:
    return request.app.state.watch


async def _require_slot(svc: WatchService, username: str, play_id: str) -> None:
    svc.sync_slot_limit()
    ok, used, maximum = await svc.slots.heartbeat(username, play_id)
    if not ok:
        raise HTTPException(
            status_code=409,
            detail=f"All {maximum} watch slots are in use ({used}/{maximum}). Try again in a minute.",
        )


def _panel_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=502, detail=str(exc) or "Panel request failed.")


def register_watch(app: FastAPI, static_dir) -> None:
    """Attach /watch HTML plus login, catalogue, slot, and media-proxy routes."""
    @app.post("/api/watch/login")
    async def watch_login(request: Request, body: LoginBody) -> JSONResponse:
        name = authenticate(
            resolve_paths(_root(request)).watch_users,
            body.username,
            body.password,
        )
        if not name:
            raise HTTPException(status_code=401, detail="Unknown user or password.")
        response = JSONResponse({"ok": True, "username": name})
        set_session(response, request, _root(request), name)
        return response

    @app.post("/api/watch/logout")
    async def watch_logout(request: Request, body: SlotBody | None = None) -> JSONResponse:
        if body and body.play_id:
            await _svc(request).slots.release(body.play_id)
        payload = {"ok": True}
        response = JSONResponse(payload)
        clear_session(response)
        return response

    @app.get("/api/watch/me")
    async def watch_me(request: Request) -> dict[str, Any]:
        svc = _svc(request)
        cfg = svc.config()
        user = current_username(request, _root(request))
        snap = await svc.slots.snapshot()
        return {
            "username": user,
            "configured": cfg.configured,
            "max_concurrent": cfg.max_concurrent,
            "slots": snap,
            "sync": svc.guide.status(),
        }

    @app.post("/api/player/sync")
    async def player_sync(request: Request, body: SyncBody) -> dict[str, Any]:
        """Queue a manual playlist or EPG refresh. The background syncer picks it up immediately."""
        require_username(request, _root(request))
        cfg = _svc(request).config()
        if not cfg.configured:
            raise HTTPException(status_code=503, detail="Watch player is not configured.")
        try:
            syncer = getattr(request.app.state, "watch_syncer", None)
            if syncer is not None:
                return syncer.request(body.kind)
            queued = queue_watch_force(_root(request), body.kind)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "queued": queued, "running": bool(_svc(request).guide.running)}

    @app.post("/api/player/slot/heartbeat")
    async def slot_heartbeat(request: Request, body: SlotBody) -> dict[str, Any]:
        user = require_username(request, _root(request))
        if len((body.play_id or "").strip()) < 8:
            raise HTTPException(status_code=400, detail="Missing play_id.")
        cfg = _svc(request).config()
        if not cfg.configured:
            raise HTTPException(status_code=503, detail="Watch player is not configured.")
        await _require_slot(_svc(request), user, body.play_id)
        snap = await _svc(request).slots.snapshot()
        return {"ok": True, "slots": snap}

    @app.post("/api/player/slot/release")
    async def slot_release(request: Request, body: SlotBody) -> dict[str, Any]:
        require_username(request, _root(request))
        snap = await _svc(request).slots.release(body.play_id)
        return {"ok": True, "slots": snap}

    @app.get("/api/player/live/categories")
    async def live_categories(request: Request) -> dict[str, Any]:
        return await _categories(request, "live")

    @app.get("/api/player/vod/categories")
    async def vod_categories(request: Request) -> dict[str, Any]:
        return await _categories(request, "vod")

    @app.get("/api/player/series/categories")
    async def series_categories(request: Request) -> dict[str, Any]:
        return await _categories(request, "series")

    async def _categories(request: Request, kind: str) -> dict[str, Any]:
        require_username(request, _root(request))
        cfg = _svc(request).config()
        if not cfg.configured:
            raise HTTPException(status_code=503, detail="Watch player is not configured.")
        try:
            rows = await _svc(request).catalogue.categories(cfg, kind)
        except Exception as exc:
            raise _panel_error(exc) from exc
        return {"categories": rows}

    @app.get("/api/player/search")
    async def player_search(request: Request, q: str = Query(default="", max_length=80)) -> dict[str, Any]:
        """Search live TV, movies, and shows in the on-disk guide."""
        require_username(request, _root(request))
        cfg = _svc(request).config()
        if not cfg.configured:
            raise HTTPException(status_code=503, detail="Watch player is not configured.")
        return _svc(request).guide.search(q)

    @app.get("/api/player/live/streams")
    async def live_streams(request: Request, category_id: str = "") -> dict[str, Any]:
        require_username(request, _root(request))
        cfg = _svc(request).config()
        if not cfg.configured:
            raise HTTPException(status_code=503, detail="Watch player is not configured.")
        try:
            rows = await _svc(request).catalogue.live_streams(cfg, category_id)
        except Exception as exc:
            raise _panel_error(exc) from exc
        return {"streams": rows}

    @app.get("/api/player/live/epg")
    async def live_epg(request: Request, stream_id: str = Query(min_length=1)) -> dict[str, Any]:
        require_username(request, _root(request))
        cfg = _svc(request).config()
        if not cfg.configured:
            raise HTTPException(status_code=503, detail="Watch player is not configured.")
        try:
            rows = await _svc(request).catalogue.short_epg(cfg, stream_id)
        except Exception as exc:
            raise _panel_error(exc) from exc
        return {"epg": rows}

    @app.get("/api/player/vod/streams")
    async def vod_streams(request: Request, category_id: str = "") -> dict[str, Any]:
        require_username(request, _root(request))
        cfg = _svc(request).config()
        if not cfg.configured:
            raise HTTPException(status_code=503, detail="Watch player is not configured.")
        try:
            rows = await _svc(request).catalogue.vod_streams(cfg, category_id)
        except Exception as exc:
            raise _panel_error(exc) from exc
        return {"streams": rows}

    @app.get("/api/player/vod/info")
    async def vod_info(request: Request, vod_id: str = Query(min_length=1)) -> dict[str, Any]:
        require_username(request, _root(request))
        cfg = _svc(request).config()
        if not cfg.configured:
            raise HTTPException(status_code=503, detail="Watch player is not configured.")
        try:
            data = await _svc(request).catalogue.vod_info(cfg, vod_id)
        except Exception as exc:
            raise _panel_error(exc) from exc
        return data

    @app.get("/api/player/series/list")
    async def series_list(request: Request, category_id: str = "") -> dict[str, Any]:
        require_username(request, _root(request))
        cfg = _svc(request).config()
        if not cfg.configured:
            raise HTTPException(status_code=503, detail="Watch player is not configured.")
        try:
            rows = await _svc(request).catalogue.series_list(cfg, category_id)
        except Exception as exc:
            raise _panel_error(exc) from exc
        return {"series": rows}

    @app.get("/api/player/series/info")
    async def series_info(request: Request, series_id: str = Query(min_length=1)) -> dict[str, Any]:
        require_username(request, _root(request))
        cfg = _svc(request).config()
        if not cfg.configured:
            raise HTTPException(status_code=503, detail="Watch player is not configured.")
        try:
            data = await _svc(request).catalogue.series_info(cfg, series_id)
        except Exception as exc:
            raise _panel_error(exc) from exc
        return data

    @app.get("/api/player/media/{kind}/{stream_id}.{ext}")
    async def player_media(
        request: Request,
        kind: str,
        stream_id: str,
        ext: str,
        sid: str = Query(default="", min_length=0),
    ) -> Response:
        """Proxy live/movie/series. sid is the tab play_id required to hold a slot."""
        if kind not in KINDS:
            raise HTTPException(status_code=400, detail="Invalid media kind.")
        user = require_username(request, _root(request))
        svc = _svc(request)
        cfg = svc.config()
        if not cfg.configured:
            raise HTTPException(status_code=503, detail="Watch player is not configured.")
        if not sid or len(sid) < 8:
            raise HTTPException(status_code=400, detail="Missing sid.")
        await _require_slot(svc, user, sid)
        url = panel_media_url(cfg, kind, stream_id, ext)
        live_ts = kind == "live" and ext.lstrip(".").lower() == "ts"
        vod = kind in {"movie", "series"} and ext.lstrip(".").lower() not in {"m3u8", "mpd"}
        serializer = None if live_ts else fetch_serializer(_root(request))
        return await proxy_url(
            url,
            serializer=serializer,
            sid=sid,
            range_header=None if vod else request.headers.get("range"),
            assume_mpegts=live_ts,
            remux_aac=vod,
        )

    @app.get("/api/player/fetch")
    async def player_fetch(
        request: Request,
        t: str = Query(min_length=8),
        sid: str = Query(min_length=8),
    ) -> Response:
        """Follow a signed HLS segment URL minted while rewriting a playlist."""
        user = require_username(request, _root(request))
        await _require_slot(_svc(request), user, sid)
        serializer = fetch_serializer(_root(request))
        url = load_signed_url(serializer, t)
        return await proxy_url(
            url,
            serializer=serializer,
            sid=sid,
            range_header=request.headers.get("range"),
        )

    @app.get("/watch")
    async def watch_page() -> FileResponse:
        return FileResponse(static_dir / "watch.html")
