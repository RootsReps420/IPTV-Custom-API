"""/watch login and player API routes.

Friends get a cookie after POST /api/watch/login (config/watch_users.yaml).
TV uses the Magnum live M3U in player.yaml when set; movies/shows use Xtream.
Media is same-origin /api/player/media/... which proxies the stream.
Playback URLs never go to the browser.

Slot heartbeats cap concurrent playback at player.yaml max_concurrent (default 5).
Watch uses config/player.yaml. Magnum playlist failover writes that DNS and
refreshes the live M3U; Strong 8K playlists.yaml is never a Watch source.
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
    PasswordChangeBody,
    authenticate,
    change_watch_password,
    clear_login_failures,
    clear_session,
    client_ip,
    kick_username,
    mint_media_token,
    must_change_password,
    read_session,
    record_login_failure,
    refuse_locked_login,
    require_player_user,
    require_username,
    set_session,
)
from iptv_monitor.player_proxy import load_fetch_url, panel_media_url, proxy_url, vod_hls_wrapper
from iptv_monitor.player_m3u import with_live_ext
from iptv_monitor.player_guide import WatchGuide
from iptv_monitor.player_presence import PresenceTracker
from iptv_monitor.player_slots import SlotTracker
from iptv_monitor.player_sync import queue_watch_force
from iptv_monitor.player_xtream import XtreamCatalogue, load_player_config

logger = logging.getLogger("iptv_monitor.watch")

KINDS = {"live", "movie", "series"}


class SlotBody(BaseModel):
    play_id: str = Field(default="", max_length=80)
    kind: str = Field(default="", max_length=16)
    stream_id: str = Field(default="", max_length=80)
    title: str = Field(default="", max_length=200)
    detail: str = Field(default="", max_length=200)
    buffer_s: float = Field(default=0, ge=0, le=120)
    stalls: int = Field(default=0, ge=0, le=50)
    dropped: int = Field(default=0, ge=0, le=1_000_000)
    decoded: int = Field(default=0, ge=0, le=10_000_000)
    width: int = Field(default=0, ge=0, le=7680)
    height: int = Field(default=0, ge=0, le=4320)
    audio: str = Field(default="", max_length=40)


class SyncBody(BaseModel):
    kind: Literal["playlist", "epg"]


class WatchService:
    """Per-process Watch state: slot table, shared live guide, Xtream fallback."""
    def __init__(self, root) -> None:
        self.root = root
        self.slots = SlotTracker()
        self.presence = PresenceTracker()
        self.guide = WatchGuide(root)
        self.catalogue = XtreamCatalogue(root, guide=self.guide)
        self._cfg = None
        self._cfg_at = 0.0

    def invalidate_config(self) -> None:
        """Drop the player.yaml cache so Magnum DNS switches apply on the next stream."""
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

    async def owner_watch(self) -> dict[str, Any]:
        """Owner-only /watch presence + slot counts. Not included in public JSON."""
        presence = await self.presence.snapshot()
        slots = await self.slots.snapshot()
        return {**presence, "slots": slots}

    async def kick_user(self, username: str) -> dict[str, Any]:
        """Owner force-logout: revoke cookies, drop presence, free slots."""
        name = (username or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Missing username.")
        kicked_at = kick_username(name)
        dropped = await self.presence.drop_user(name)
        released = await self.slots.release_user(name)
        logger.info("Owner signed out Watch user %s (%s sessions, %s slots)", name, dropped, released)
        return {
            "ok": True,
            "username": name,
            "dropped": dropped,
            "slots_released": released,
            "kicked_at": int(kicked_at),
        }


def _root(request: Request):
    """Project root. systemd does not pass --root, so WatchService.root can be None."""
    return resolve_paths(request.app.state.watch.root).root


def _svc(request: Request) -> WatchService:
    return request.app.state.watch


async def _touch_presence(
    request: Request,
    response: JSONResponse | None = None,
    *,
    play_id: str = "",
    playing: bool | None = None,
    kind: str = "",
    stream_id: str = "",
    title: str = "",
    detail: str = "",
    username: str | None = None,
    buffer_s: float = 0,
    stalls: int = 0,
    dropped: int = 0,
    decoded: int = 0,
    width: int = 0,
    height: int = 0,
    audio: str = "",
) -> None:
    """Record presence from requests /watch already makes. Optional cookie sid mint."""
    root = _root(request)
    session = read_session(request, root)
    name = (username or "").strip() or (session.username if session else "")
    if not name:
        return
    sid = session.session_id if session else ""
    ip = client_ip(request)
    if response is not None and not sid:
        reused = await _svc(request).presence.reuse_sid(name, ip)
        sid = set_session(
            response,
            request,
            root,
            name,
            session_id=reused or None,
            issued_at=(session.issued_at if session else 0) or None,
        )
    looked_title = title
    looked_detail = detail
    if playing and stream_id:
        guide_title, guide_detail = _svc(request).guide.describe_media(kind, stream_id)
        looked_title = title or guide_title
        looked_detail = detail or guide_detail
    await _svc(request).presence.touch(
        username=name,
        session_id=sid or play_id,
        ip=ip,
        issued_at=float(session.issued_at if session else 0),
        play_id=play_id,
        playing=playing,
        kind=kind,
        stream_id=stream_id,
        title=looked_title,
        detail=looked_detail,
        buffer_s=buffer_s,
        stalls=stalls,
        dropped=dropped,
        decoded=decoded,
        width=width,
        height=height,
        audio=audio,
    )


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
        ip = client_ip(request)
        refuse_locked_login(ip=ip, username=body.username)
        name = authenticate(
            resolve_paths(_root(request)).watch_users,
            body.username,
            body.password,
        )
        if not name:
            record_login_failure(ip=ip, username=body.username)
            refuse_locked_login(ip=ip, username=body.username)
            raise HTTPException(status_code=401, detail="Unknown user or password.")
        clear_login_failures(ip=ip, username=name)
        users_path = resolve_paths(_root(request)).watch_users
        needs_new = must_change_password(users_path, name)
        response = JSONResponse(
            {"ok": True, "username": name, "must_change_password": needs_new}
        )
        sid = set_session(response, request, _root(request), name)
        await _svc(request).presence.touch(
            username=name,
            session_id=sid,
            ip=ip,
            issued_at=time.time(),
        )
        return response

    @app.post("/api/watch/logout")
    async def watch_logout(request: Request, body: SlotBody | None = None) -> JSONResponse:
        session = read_session(request, _root(request))
        play_id = (body.play_id if body else "") or ""
        if play_id:
            await _svc(request).slots.release(play_id)
        await _svc(request).presence.drop(
            session_id=session.session_id if session else "",
            play_id=play_id,
        )
        response = JSONResponse({"ok": True})
        clear_session(response)
        return response

    @app.post("/api/watch/password")
    async def watch_password(request: Request, body: PasswordChangeBody) -> dict:
        """Set a new hashed Watch password. Refuses until complexity checks pass."""
        name = require_username(request, _root(request), allow_password_change=True)
        ip = client_ip(request)
        refuse_locked_login(ip=ip, username=name)
        users_path = resolve_paths(_root(request)).watch_users
        try:
            change_watch_password(
                users_path,
                name,
                current_password=body.current_password,
                new_password=body.new_password,
                confirm_password=body.confirm_password,
            )
        except HTTPException as exc:
            if exc.status_code == 401:
                record_login_failure(ip=ip, username=name)
                refuse_locked_login(ip=ip, username=name)
            raise
        clear_login_failures(ip=ip, username=name)
        return {"ok": True, "username": name, "must_change_password": False}

    @app.get("/api/watch/me")
    async def watch_me(
        request: Request,
        play_id: str = Query(default="", max_length=80),
        buffer_s: float = Query(default=0, ge=0, le=120),
        stalls: int = Query(default=0, ge=0, le=50),
        dropped: int = Query(default=0, ge=0, le=1_000_000),
        decoded: int = Query(default=0, ge=0, le=10_000_000),
        width: int = Query(default=0, ge=0, le=7680),
        height: int = Query(default=0, ge=0, le=4320),
        audio: str = Query(default="", max_length=40),
    ) -> JSONResponse:
        session = read_session(request, _root(request))
        if not session:
            raise HTTPException(status_code=401, detail="Sign in to watch.")
        svc = _svc(request)
        cfg = svc.config()
        needs_new = must_change_password(
            resolve_paths(_root(request)).watch_users, session.username
        )
        snap = await svc.slots.snapshot()
        payload = {
            "username": session.username,
            "must_change_password": needs_new,
            "configured": False if needs_new else cfg.configured,
            "max_concurrent": cfg.max_concurrent,
            "slots": snap,
            "sync": None if needs_new else svc.guide.status(),
            "media_token": (
                None
                if needs_new or len((play_id or "").strip()) < 8
                else mint_media_token(_root(request), session.username, play_id.strip())
            ),
        }
        response = JSONResponse(payload)
        await _touch_presence(
            request,
            response,
            play_id=play_id,
            buffer_s=buffer_s,
            stalls=stalls,
            dropped=dropped,
            decoded=decoded,
            width=width,
            height=height,
            audio=audio,
        )
        return response

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
        kind = (body.kind or "").strip().lower()
        await _touch_presence(
            request,
            play_id=body.play_id,
            playing=True,
            kind=kind if kind in KINDS else "",
            stream_id=body.stream_id,
            title=body.title,
            detail=body.detail,
            buffer_s=body.buffer_s,
            stalls=body.stalls,
            dropped=body.dropped,
            decoded=body.decoded,
            width=body.width,
            height=body.height,
            audio=body.audio,
        )
        snap = await _svc(request).slots.snapshot()
        return {"ok": True, "slots": snap}

    @app.post("/api/player/slot/release")
    async def slot_release(request: Request, body: SlotBody) -> dict[str, Any]:
        require_username(request, _root(request))
        snap = await _svc(request).slots.release(body.play_id)
        await _touch_presence(request, play_id=body.play_id, playing=False)
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
        start: float = Query(default=0),
        src: str = Query(default=""),
        dur: float = Query(default=0),
        vc: str = Query(default=""),
    ) -> Response:
        """Proxy live/movie/series. sid is the tab play_id required to hold a slot."""
        if kind not in KINDS:
            raise HTTPException(status_code=400, detail="Invalid media kind.")
        user = require_player_user(request, _root(request))
        svc = _svc(request)
        cfg = svc.config()
        if not cfg.configured:
            raise HTTPException(status_code=503, detail="Watch player is not configured.")
        if not sid or len(sid) < 8:
            raise HTTPException(status_code=400, detail="Missing sid.")
        await _require_slot(svc, user, sid)
        await _touch_presence(
            request,
            play_id=sid,
            playing=True,
            kind=kind,
            stream_id=stream_id,
            username=user,
        )
        url = ""
        if kind == "live":
            playback = svc.guide.live_playback_url(stream_id)
            if playback:
                url = with_live_ext(playback, ext)
            elif cfg.live_m3u_url:
                raise HTTPException(status_code=404, detail="Unknown live stream.")
        if not url:
            url = panel_media_url(cfg, kind, stream_id, ext)
        live_ts = kind == "live" and ext.lstrip(".").lower() == "ts"
        kind_vod = kind in {"movie", "series"}
        vod_ext = ext.lstrip(".").lower()
        token = "" if live_ts else mint_media_token(_root(request), user, sid)
        if kind_vod and vod_ext == "m3u8":
            src_ext = "".join(ch for ch in (src or "mp4").lower().lstrip(".") if ch.isalnum())[:8] or "mp4"
            if src_ext in {"m3u8", "mpd", "ts"}:
                src_ext = "mp4"
            return vod_hls_wrapper(
                kind=kind,
                stream_id=stream_id,
                sid=sid,
                access_token=token,
                src_ext=src_ext,
                start_sec=max(0.0, float(start or 0.0)),
                duration_sec=max(0.0, float(dur or 0.0)),
                video_caps=vc,
            )
        vod = kind_vod and vod_ext not in {"m3u8", "mpd"}
        remux_container = "mpegts" if vod and vod_ext == "ts" else "mp4"
        if vod:
            src_ext = "".join(ch for ch in (src or "mp4").lower().lstrip(".") if ch.isalnum())[:8] or "mp4"
            if src_ext in {"m3u8", "mpd", "ts"}:
                src_ext = "mp4"
            url = panel_media_url(cfg, kind, stream_id, src_ext)
        presence = svc.presence
        start_sec = max(0.0, float(start or 0.0)) if vod else 0.0
        allow_hevc = any(
            part in {"hevc", "h265"}
            for part in (vc or "").lower().replace(" ", "").split(",")
            if part
        )
        return await proxy_url(
            url,
            rewrite_uris=not live_ts,
            sid=sid,
            range_header=None if vod else request.headers.get("range"),
            assume_mpegts=live_ts,
            remux_aac=vod,
            remux_container=remux_container,
            access_token=token,
            on_bytes=lambda n, pid=sid: presence.add_bytes(pid, n),
            start_sec=start_sec,
            allow_hevc=allow_hevc,
        )

    @app.get("/api/player/fetch")
    async def player_fetch(
        request: Request,
        t: str = Query(min_length=8),
        sid: str = Query(min_length=8),
    ) -> Response:
        """Follow an opaque HLS ticket minted while rewriting a playlist."""
        user = require_player_user(request, _root(request))
        await _require_slot(_svc(request), user, sid)
        url = load_fetch_url(t)
        presence = _svc(request).presence
        return await proxy_url(
            url,
            rewrite_uris=True,
            sid=sid,
            range_header=request.headers.get("range"),
            access_token=mint_media_token(_root(request), user, sid),
            on_bytes=lambda n, pid=sid: presence.add_bytes(pid, n),
        )

    @app.get("/watch")
    async def watch_page() -> FileResponse:
        return FileResponse(static_dir / "watch.html")
