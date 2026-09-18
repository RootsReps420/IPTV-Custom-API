"""Xtream player_api client for the /watch catalogue. Credentials stay on the server.

Fetches movies/shows from Xtream player_api. Live TV uses the Magnum M3U in
player.yaml when live_m3u is set; otherwise it falls back to get_live_streams.
Responses are whitelisted field-by-field before JSON hits the browser.
Placeholder dns hosts (portal.example) count as unconfigured.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, field_validator
from ruamel.yaml import YAML

from iptv_monitor.config import resolve_paths
from iptv_monitor.player_guide import (
    decode_xtream_text,
    is_wanted_library_group,
    is_wanted_live_group,
    listings_to_guide_rows,
)
from iptv_monitor.health import normalize_url
from iptv_monitor.stream import _STREAM_UA

logger = logging.getLogger("iptv_monitor.player_xtream")

CACHE_TTL = 1800.0
API_TIMEOUT = 25.0
SLOW_READ_TIMEOUT = 90.0
_PLACEHOLDER_DNS = ("portal.example", "your-live-portal.example")
_SLOW_ACTIONS = frozenset(
    {
        "get_live_streams",
        "get_vod_streams",
        "get_series",
        "get_vod_info",
        "get_series_info",
    }
)


class PlayerConfig(BaseModel):
    max_concurrent: int = 5
    dns: str = ""
    username: str = ""
    password: str = ""
    # Magnum live M3U for the TV tab. Empty = Xtream get_live_streams (legacy).
    live_m3u: str = ""
    live_epg: str = ""

    @field_validator("live_m3u", "live_epg", mode="before")
    @classmethod
    def _blank_url(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @property
    def live_m3u_url(self) -> str:
        return (self.live_m3u or "").strip()

    @property
    def live_epg_url(self) -> str:
        return (self.live_epg or "").strip()

    @property
    def configured(self) -> bool:
        """False until real dns + user + pass are set (example hosts do not count)."""
        host = urlparse(self.base).hostname or ""
        if host.lower() in _PLACEHOLDER_DNS:
            return False
        return bool(self.base and self.username.strip() and self.password.strip())

    @property
    def base(self) -> str:
        raw = (self.dns or "").strip()
        if not raw:
            return ""
        try:
            return normalize_url(raw).rstrip("/")
        except ValueError:
            return ""


def load_player_config(root=None) -> PlayerConfig:
    """Read config/player.yaml only. Watch never follows playlists.yaml / DanMain DNS."""
    paths = resolve_paths(root)
    path = paths.player
    if not path.exists():
        return PlayerConfig()
    try:
        raw = YAML(typ="safe").load(path.read_text(encoding="utf-8")) or {}
        cfg = PlayerConfig.model_validate(raw)
    except Exception:
        logger.warning("Could not read player config from %s", path)
        return PlayerConfig()
    return cfg


def _as_list(payload: object) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _pick(item: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in keys:
        if key in item and item[key] is not None:
            out[key] = item[key]
    return out


_CATEGORY_KEYS = ("category_id", "category_name", "parent_id")
_LIVE_KEYS = (
    "num",
    "name",
    "stream_type",
    "stream_id",
    "stream_icon",
    "epg_channel_id",
    "added",
    "category_id",
    "tv_archive",
    "tv_archive_duration",
    "is_adult",
    "custom_sid",
    "title",
    "description",
    "category_ids",
)
_VOD_KEYS = (
    "num",
    "name",
    "stream_type",
    "stream_id",
    "stream_icon",
    "rating",
    "rating_5based",
    "added",
    "category_id",
    "container_extension",
    "plot",
    "genre",
    "director",
    "releasedate",
    "youtube_trailer",
    "duration",
    "duration_secs",
    "cover_big",
    "backdrop_path",
)
_SERIES_KEYS = (
    "num",
    "name",
    "series_id",
    "cover",
    "plot",
    "cast",
    "director",
    "genre",
    "releaseDate",
    "last_modified",
    "rating",
    "rating_5based",
    "backdrop_path",
    "youtube_trailer",
    "episode_run_time",
    "category_id",
)
_EPG_KEYS = ("id", "epg_id", "title", "lang", "start", "end", "description", "start_timestamp", "stop_timestamp")
_EPISODE_KEYS = (
    "id",
    "episode_num",
    "title",
    "container_extension",
    "plot",
    "duration",
    "rating",
    "season",
    "info",
)


class XtreamCatalogue:
    def __init__(self, root: Path | None = None, guide=None) -> None:
        self._root = root
        self.guide = guide
        self._cache: dict[str, tuple[float, Any]] = {}
        self._disk_loaded = False
        self._epg_tasks: dict[str, asyncio.Task] = {}

    def _key(self, cfg: PlayerConfig, action: str, extra: str) -> str:
        return f"{cfg.base}|{cfg.username}|{action}|{extra}"

    def _disk_path(self) -> Path:
        return resolve_paths(self._root).root / "state" / "watch_catalogue.json"

    def _load_disk(self) -> None:
        if self._disk_loaded:
            return
        self._disk_loaded = True
        path = self._disk_path()
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Could not read Watch catalogue cache")
            return
        if not isinstance(raw, dict):
            return
        now = time.time()
        for key, row in raw.items():
            if not isinstance(row, dict) or "payload" not in row:
                continue
            exp = float(row.get("exp") or 0)
            if exp <= now:
                continue
            self._cache[str(key)] = (time.monotonic() + max(1.0, exp - now), row["payload"])

    def _save_disk(self) -> None:
        path = self._disk_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        now_mono = time.monotonic()
        now = time.time()
        out: dict[str, Any] = {}
        for key, (expires, value) in self._cache.items():
            remaining = expires - now_mono
            if remaining <= 0:
                continue
            out[key] = {"exp": now + remaining, "payload": value}
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
        tmp.replace(path)

    def _get_cached(self, key: str) -> Any | None:
        self._load_disk()
        hit = self._cache.get(key)
        if not hit:
            return None
        expires, value = hit
        if time.monotonic() > expires:
            self._cache.pop(key, None)
            return None
        return value

    def _put(self, key: str, value: Any, *, persist: bool = False) -> Any:
        self._cache[key] = (time.monotonic() + CACHE_TTL, value)
        if persist:
            try:
                self._save_disk()
            except Exception:
                logger.warning("Could not write Watch catalogue cache")
        return value

    def _timeout(self, action: str | None) -> httpx.Timeout:
        read = SLOW_READ_TIMEOUT if action in _SLOW_ACTIONS else API_TIMEOUT
        return httpx.Timeout(connect=10.0, read=read, write=30.0, pool=10.0)

    async def _api(
        self,
        cfg: PlayerConfig,
        action: str | None = None,
        extra: dict[str, str] | None = None,
        *,
        cache: bool = True,
    ) -> Any:
        """GET player_api.php. Never returns username/password — callers whitelist fields."""
        if not cfg.configured:
            raise RuntimeError("Watch player is not configured.")
        extra = extra or {}
        cache_key = self._key(cfg, action or "auth", "&".join(f"{k}={v}" for k, v in sorted(extra.items())))
        if cache:
            hit = self._get_cached(cache_key)
            if hit is not None:
                return hit
        params: dict[str, str] = {
            "username": cfg.username.strip(),
            "password": cfg.password.strip(),
        }
        if action:
            params["action"] = action
        params.update(extra)
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(
                verify=False,
                follow_redirects=True,
                timeout=self._timeout(action),
                headers={"User-Agent": _STREAM_UA, "Accept": "application/json"},
            ) as client:
                response = await client.get(f"{cfg.base}/player_api.php", params=params)
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                "Panel timed out returning the channel list. Wait a moment and try the category again."
            ) from exc
        elapsed = time.monotonic() - started
        if action != "get_short_epg":
            logger.info("Watch %s in %.1fs (%s bytes)", action or "auth", elapsed, len(response.content))
        if response.status_code >= 400:
            raise RuntimeError(f"Panel HTTP {response.status_code}")
        try:
            payload = response.json()
        except Exception as exc:
            raise RuntimeError("Panel returned non-JSON") from exc
        if cache:
            return self._put(cache_key, payload, persist=action in _SLOW_ACTIONS)
        return payload

    async def categories(self, cfg: PlayerConfig, kind: str) -> list[dict[str, Any]]:
        if self.guide is not None:
            cached = None
            if kind == "live":
                cached = self.guide.live_categories()
            elif kind == "vod":
                cached = self.guide.vod_categories()
            elif kind == "series":
                cached = self.guide.series_categories()
            if cached is not None:
                return cached
            if kind == "live" and cfg.live_m3u_url:
                return []
            if self.guide.running:
                return []
        action = {
            "live": "get_live_categories",
            "vod": "get_vod_categories",
            "series": "get_series_categories",
        }[kind]
        rows = [_pick(item, _CATEGORY_KEYS) for item in _as_list(await self._api(cfg, action))]
        if kind == "live":
            rows = [row for row in rows if is_wanted_live_group(str(row.get("category_name") or ""))]
        elif kind in {"vod", "series"}:
            rows = [row for row in rows if is_wanted_library_group(str(row.get("category_name") or ""))]
        return rows

    async def live_streams(self, cfg: PlayerConfig, category_id: str) -> list[dict[str, Any]]:
        if self.guide is not None:
            cached = self.guide.live_streams(category_id)
            if cached is not None:
                if not cfg.live_m3u_url:
                    await self._await_epg_backfill(cfg, category_id, cached)
                    refreshed = self.guide.live_streams(category_id)
                    return refreshed if refreshed is not None else cached
                return cached
            if cfg.live_m3u_url or self.guide.running:
                return []
        extra = {"category_id": category_id} if category_id else {}
        rows = [_pick(item, _LIVE_KEYS) for item in _as_list(await self._api(cfg, "get_live_streams", extra))]
        if self.guide is not None:
            return [self.guide.decorate(row) for row in rows]
        return rows

    async def _await_epg_backfill(
        self, cfg: PlayerConfig, category_id: str, rows: list[dict[str, Any]]
    ) -> None:
        """Fill now/next for this group; wait briefly so the channel list is not empty on first paint."""
        cid = str(category_id or "").strip()
        if not cid:
            return
        missing = [
            row
            for row in rows
            if not str(row.get("now_title") or "").strip() and str(row.get("stream_id") or "").strip()
        ]
        if not missing:
            return
        task = self._epg_tasks.get(cid)
        if task is None or task.done():
            task = asyncio.create_task(self._backfill_epg(cfg, cid, missing[:80]))
            self._epg_tasks[cid] = task
        try:
            await asyncio.wait_for(asyncio.shield(task), 3.2)
        except (asyncio.TimeoutError, Exception):
            return

    async def _backfill_epg(self, cfg: PlayerConfig, category_id: str, rows: list[dict[str, Any]]) -> None:
        sem = asyncio.Semaphore(6)

        async def one(row: dict[str, Any]) -> None:
            async with sem:
                try:
                    await self.short_epg(cfg, str(row.get("stream_id") or ""))
                except Exception:
                    return

        try:
            await asyncio.gather(*(one(row) for row in rows))
        finally:
            current = self._epg_tasks.get(category_id)
            if current is not None and current.done():
                self._epg_tasks.pop(category_id, None)

    async def vod_streams(self, cfg: PlayerConfig, category_id: str) -> list[dict[str, Any]]:
        if self.guide is not None:
            cached = self.guide.vod_streams(category_id)
            if cached is not None:
                return cached
            if self.guide.running:
                return []
        extra = {"category_id": category_id} if category_id else {}
        return [_pick(item, _VOD_KEYS) for item in _as_list(await self._api(cfg, "get_vod_streams", extra))]

    async def series_list(self, cfg: PlayerConfig, category_id: str) -> list[dict[str, Any]]:
        if self.guide is not None:
            cached = self.guide.series_list(category_id)
            if cached is not None:
                return cached
            if self.guide.running:
                return []
        extra = {"category_id": category_id} if category_id else {}
        return [_pick(item, _SERIES_KEYS) for item in _as_list(await self._api(cfg, "get_series", extra))]

    async def vod_info(self, cfg: PlayerConfig, vod_id: str) -> dict[str, Any]:
        payload = await self._api(cfg, "get_vod_info", {"vod_id": vod_id}, cache=True)
        if not isinstance(payload, dict):
            return {}
        info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
        movie = payload.get("movie_data") if isinstance(payload.get("movie_data"), dict) else {}
        return {
            "info": _pick(info, _VOD_KEYS + ("name", "cover_big", "youtube_trailer", "duration", "duration_secs", "plot")),
            "movie_data": _pick(movie, _VOD_KEYS),
        }

    async def series_info(self, cfg: PlayerConfig, series_id: str) -> dict[str, Any]:
        payload = await self._api(cfg, "get_series_info", {"series_id": series_id}, cache=True)
        if not isinstance(payload, dict):
            return {}
        info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
        episodes_in = payload.get("episodes") if isinstance(payload.get("episodes"), dict) else {}
        episodes: dict[str, list[dict[str, Any]]] = {}
        for season, items in episodes_in.items():
            cleaned: list[dict[str, Any]] = []
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                row = _pick(item, _EPISODE_KEYS)
                if isinstance(item.get("info"), dict):
                    row["info"] = _pick(
                        item["info"],
                        ("duration", "duration_secs", "plot", "rating", "movie_image", "release_date", "name"),
                    )
                cleaned.append(row)
            episodes[str(season)] = cleaned
        seasons = payload.get("seasons") if isinstance(payload.get("seasons"), list) else []
        return {
            "info": _pick(info, _SERIES_KEYS),
            "seasons": seasons,
            "episodes": episodes,
        }

    async def short_epg(self, cfg: PlayerConfig, stream_id: str) -> list[dict[str, Any]]:
        if self.guide is not None:
            cached = self.guide.listings_for_stream(stream_id)
            if cached is not None:
                return cached
            if cfg.live_m3u_url:
                return []
        payload = await self._api(
            cfg, "get_short_epg", {"stream_id": stream_id, "limit": "8"}, cache=True
        )
        listings = []
        if isinstance(payload, dict):
            listings = payload.get("epg_listings") or []
        if not isinstance(listings, list):
            return []
        rows = [_pick(item, _EPG_KEYS) for item in listings if isinstance(item, dict)]
        for row in rows:
            if "title" in row:
                row["title"] = decode_xtream_text(str(row["title"]))
            if "description" in row:
                row["description"] = decode_xtream_text(str(row["description"]))
        if self.guide is not None:
            stream = self.guide.data.by_id.get(str(stream_id).strip())
            guide_rows = listings_to_guide_rows(rows)
            if stream and guide_rows:
                self.guide.ingest_short_epg(stream, guide_rows)
        return rows
