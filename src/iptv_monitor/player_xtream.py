"""Xtream player_api client for the /watch catalogue. Credentials stay on the server.

Fetches categories, streams, EPG, VOD info, series info. Responses are
whitelisted field-by-field before JSON hits the browser. Results cache ~8 minutes.
Placeholder dns hosts (portal.example) count as unconfigured.
"""

from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel
from ruamel.yaml import YAML

from iptv_monitor.config import resolve_paths
from iptv_monitor.health import normalize_url
from iptv_monitor.stream import _STREAM_UA

logger = logging.getLogger("iptv_monitor.player_xtream")

CACHE_TTL = 480.0
API_TIMEOUT = 25.0
_PLACEHOLDER_DNS = ("portal.example", "your-live-portal.example")


class PlayerConfig(BaseModel):
    max_concurrent: int = 5
    dns: str = ""
    username: str = ""
    password: str = ""

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
    """Read config/player.yaml. Missing/invalid file → empty unconfigured config."""
    path = resolve_paths(root).player
    if not path.exists():
        return PlayerConfig()
    try:
        raw = YAML(typ="safe").load(path.read_text(encoding="utf-8")) or {}
        return PlayerConfig.model_validate(raw)
    except Exception:
        logger.warning("Could not read player config from %s", path)
        return PlayerConfig()


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
    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, Any]] = {}

    def _key(self, cfg: PlayerConfig, action: str, extra: str) -> str:
        return f"{cfg.base}|{cfg.username}|{action}|{extra}"

    def _get_cached(self, key: str) -> Any | None:
        hit = self._cache.get(key)
        if not hit:
            return None
        expires, value = hit
        if time.monotonic() > expires:
            self._cache.pop(key, None)
            return None
        return value

    def _put(self, key: str, value: Any) -> Any:
        self._cache[key] = (time.monotonic() + CACHE_TTL, value)
        return value

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
        timeout = httpx.Timeout(API_TIMEOUT, connect=10.0)
        async with httpx.AsyncClient(
            verify=False,
            follow_redirects=True,
            timeout=timeout,
            headers={"User-Agent": _STREAM_UA, "Accept": "application/json"},
        ) as client:
            response = await client.get(f"{cfg.base}/player_api.php", params=params)
        if response.status_code >= 400:
            raise RuntimeError(f"Panel HTTP {response.status_code}")
        try:
            payload = response.json()
        except Exception as exc:
            raise RuntimeError("Panel returned non-JSON") from exc
        if cache:
            return self._put(cache_key, payload)
        return payload

    async def categories(self, cfg: PlayerConfig, kind: str) -> list[dict[str, Any]]:
        action = {
            "live": "get_live_categories",
            "vod": "get_vod_categories",
            "series": "get_series_categories",
        }[kind]
        rows = [_pick(item, _CATEGORY_KEYS) for item in _as_list(await self._api(cfg, action))]
        return rows

    async def live_streams(self, cfg: PlayerConfig, category_id: str) -> list[dict[str, Any]]:
        extra = {"category_id": category_id} if category_id else {}
        return [_pick(item, _LIVE_KEYS) for item in _as_list(await self._api(cfg, "get_live_streams", extra))]

    async def vod_streams(self, cfg: PlayerConfig, category_id: str) -> list[dict[str, Any]]:
        extra = {"category_id": category_id} if category_id else {}
        return [_pick(item, _VOD_KEYS) for item in _as_list(await self._api(cfg, "get_vod_streams", extra))]

    async def series_list(self, cfg: PlayerConfig, category_id: str) -> list[dict[str, Any]]:
        extra = {"category_id": category_id} if category_id else {}
        return [_pick(item, _SERIES_KEYS) for item in _as_list(await self._api(cfg, "get_series", extra))]

    async def vod_info(self, cfg: PlayerConfig, vod_id: str) -> dict[str, Any]:
        payload = await self._api(cfg, "get_vod_info", {"vod_id": vod_id}, cache=True)
        if not isinstance(payload, dict):
            return {}
        info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
        movie = payload.get("movie_data") if isinstance(payload.get("movie_data"), dict) else {}
        return {
            "info": _pick(info, _VOD_KEYS + ("name", "cover_big", "youtube_trailer", "duration", "plot")),
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
                        ("duration", "plot", "rating", "movie_image", "release_date", "name"),
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
        payload = await self._api(
            cfg, "get_short_epg", {"stream_id": stream_id, "limit": "8"}, cache=True
        )
        listings = []
        if isinstance(payload, dict):
            listings = payload.get("epg_listings") or []
        if not isinstance(listings, list):
            return []
        return [_pick(item, _EPG_KEYS) for item in listings if isinstance(item, dict)]
