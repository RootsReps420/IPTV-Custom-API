"""Shared live channel + EPG store for /watch.

Background sync writes state/watch_live.json and state/watch_epg.json.
All site users read this; category clicks do not hit the panel.
Now/next is computed at read time from the XMLTV window.
"""

from __future__ import annotations

import base64
import html
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from iptv_monitor.config import resolve_paths

logger = logging.getLogger("iptv_monitor.player_guide")

LIVE_NAME = "watch_live.json"
VOD_NAME = "watch_vod.json"
SERIES_NAME = "watch_series.json"
EPG_NAME = "watch_epg.json"
META_NAME = "watch_sync.json"
_B64 = re.compile(r"^[A-Za-z0-9+/]{8,}={0,2}$")
_NOT_ALNUM = re.compile(r"[^a-z0-9]+")


def norm_epg_key(value: str) -> str:
    """Collapse XMLTV ids, display-names, and stream names for matching."""
    return _NOT_ALNUM.sub("", (value or "").lower())


def epg_alias_keys(raw: str) -> list[str]:
    """Variants: full id, id without a trailing .uk/.com-style suffix."""
    text = (raw or "").strip()
    if not text:
        return []
    keys = [norm_epg_key(text)]
    if "." in text:
        keys.append(norm_epg_key(text.rsplit(".", 1)[0]))
    return [key for key in keys if key]


def decode_xtream_text(value: str | None) -> str:
    """Xtream XMLTV titles/descriptions are often base64. Plain text is left as-is."""
    raw = html.unescape((value or "").strip())
    if not raw or not _B64.match(raw):
        return raw
    try:
        pad = "=" * ((4 - len(raw) % 4) % 4)
        out = base64.b64decode(raw + pad).decode("utf-8")
    except Exception:
        return raw
    if not out or "\x00" in out:
        return raw
    return html.unescape(out).strip() or raw


def _state_dir(root: Path | None) -> Path:
    path = resolve_paths(root).root / "state"
    path.mkdir(parents=True, exist_ok=True)
    return path


def atomic_write_json(path: Path, payload: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def load_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Could not read %s", path.name)
        return None


def category_ids_of(stream: dict[str, Any]) -> list[str]:
    """Xtream may send category_id as int, string, CSV, or category_ids list."""
    raw = stream.get("category_ids")
    if isinstance(raw, list) and raw:
        return [str(item).strip() for item in raw if str(item).strip()]
    raw = stream.get("category_id")
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    text = str(raw or "").strip()
    if not text:
        return []
    if "," in text:
        return [part.strip() for part in text.split(",") if part.strip()]
    return [text]


@dataclass
class GuideData:
    categories: list[dict[str, Any]] = field(default_factory=list)
    streams: list[dict[str, Any]] = field(default_factory=list)
    by_cat: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    by_id: dict[str, dict[str, Any]] = field(default_factory=dict)
    epg: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)
    updated_at: float = 0.0
    epg_updated_at: float = 0.0


def index_items(
    items: list[dict[str, Any]], id_key: str
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]]]:
    by_cat: dict[str, list[dict[str, Any]]] = {}
    by_id: dict[str, dict[str, Any]] = {}
    for item in items:
        sid = str(item.get(id_key) or "").strip()
        if sid:
            by_id[sid] = item
        for cid in category_ids_of(item):
            by_cat.setdefault(cid, []).append(item)
    return by_cat, by_id


def index_streams(streams: list[dict[str, Any]]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]]]:
    return index_items(streams, "stream_id")


@dataclass
class ItemLibrary:
    categories: list[dict[str, Any]] = field(default_factory=list)
    items: list[dict[str, Any]] = field(default_factory=list)
    by_cat: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    by_id: dict[str, dict[str, Any]] = field(default_factory=dict)
    updated_at: float = 0.0


def with_counts(categories: list[dict[str, Any]], by_cat: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in categories:
        item = dict(row)
        cid = str(item.get("category_id") or "")
        item["stream_count"] = len(by_cat.get(cid, []))
        out.append(item)
    return out


class WatchGuide:
    """In-memory snapshot of the last successful live + EPG sync."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root
        self.data = GuideData()
        self.running = False
        self.progress = ""
        self.last_error = ""
        self.interval_seconds = 14400
        self.vod = ItemLibrary()
        self.series = ItemLibrary()
        self.load_disk()

    def paths(self) -> tuple[Path, Path, Path, Path, Path]:
        folder = _state_dir(self.root)
        return (
            folder / LIVE_NAME,
            folder / VOD_NAME,
            folder / SERIES_NAME,
            folder / EPG_NAME,
            folder / META_NAME,
        )

    def _load_library(self, path: Path, id_key: str) -> ItemLibrary:
        raw = load_json(path)
        lib = ItemLibrary()
        if not isinstance(raw, dict):
            return lib
        lib.categories = [row for row in (raw.get("categories") or []) if isinstance(row, dict)]
        lib.items = [row for row in (raw.get("items") or raw.get("streams") or raw.get("series") or []) if isinstance(row, dict)]
        lib.updated_at = float(raw.get("updated_at") or 0)
        lib.by_cat, lib.by_id = index_items(lib.items, id_key)
        lib.categories = with_counts(lib.categories, lib.by_cat)
        return lib

    def load_disk(self) -> None:
        live_path, vod_path, series_path, epg_path, _meta = self.paths()
        live = load_json(live_path)
        epg_raw = load_json(epg_path)
        streams: list[dict[str, Any]] = []
        categories: list[dict[str, Any]] = []
        updated = 0.0
        if isinstance(live, dict):
            categories = [row for row in (live.get("categories") or []) if isinstance(row, dict)]
            streams = [row for row in (live.get("streams") or []) if isinstance(row, dict)]
            updated = float(live.get("updated_at") or 0)
        epg: dict[str, list[dict[str, Any]]] = {}
        aliases: dict[str, str] = {}
        epg_updated = 0.0
        if isinstance(epg_raw, dict):
            epg_updated = float(epg_raw.get("updated_at") or 0)
            channels = epg_raw.get("channels") or {}
            if isinstance(channels, dict):
                for key, rows in channels.items():
                    if not isinstance(rows, list):
                        continue
                    cleaned = [row for row in rows if isinstance(row, dict) and "start" in row]
                    if cleaned:
                        epg[str(key)] = cleaned
            raw_alias = epg_raw.get("aliases") or {}
            if isinstance(raw_alias, dict):
                aliases = {
                    str(key): str(val)
                    for key, val in raw_alias.items()
                    if str(key).strip() and str(val).strip()
                }
        by_cat, by_id = index_streams(streams)
        self.data = GuideData(
            categories=with_counts(categories, by_cat),
            streams=streams,
            by_cat=by_cat,
            by_id=by_id,
            epg=epg,
            aliases=aliases,
            updated_at=updated,
            epg_updated_at=epg_updated,
        )
        self.link_stream_aliases(persist=False)
        self.vod = self._load_library(vod_path, "stream_id")
        self.series = self._load_library(series_path, "series_id")
        logger.info(
            "Watch guide loaded: %s live, %s movies, %s series, %s EPG channels",
            len(self.data.streams),
            len(self.vod.items),
            len(self.series.items),
            len(self.data.epg),
        )

    def replace_live(self, categories: list[dict[str, Any]], streams: list[dict[str, Any]]) -> None:
        by_cat, by_id = index_streams(streams)
        now = time.time()
        self.data = GuideData(
            categories=with_counts(categories, by_cat),
            streams=streams,
            by_cat=by_cat,
            by_id=by_id,
            epg=self.data.epg,
            aliases=self.data.aliases,
            updated_at=now,
            epg_updated_at=self.data.epg_updated_at,
        )
        self.link_stream_aliases(persist=True)
        live_path, _vod, _series, _epg, _meta = self.paths()
        atomic_write_json(
            live_path,
            {"updated_at": now, "categories": self.data.categories, "streams": streams},
        )

    def _replace_library(
        self, lib: ItemLibrary, path: Path, categories: list[dict[str, Any]], items: list[dict[str, Any]], id_key: str
    ) -> ItemLibrary:
        now = time.time()
        by_cat, by_id = index_items(items, id_key)
        lib = ItemLibrary(
            categories=with_counts(categories, by_cat),
            items=items,
            by_cat=by_cat,
            by_id=by_id,
            updated_at=now,
        )
        atomic_write_json(
            path,
            {"updated_at": now, "categories": lib.categories, "items": items},
        )
        return lib

    def replace_vod(self, categories: list[dict[str, Any]], items: list[dict[str, Any]]) -> None:
        _live, vod_path, _series, _epg, _meta = self.paths()
        self.vod = self._replace_library(self.vod, vod_path, categories, items, "stream_id")

    def replace_series(self, categories: list[dict[str, Any]], items: list[dict[str, Any]]) -> None:
        _live, _vod, series_path, _epg, _meta = self.paths()
        self.series = self._replace_library(self.series, series_path, categories, items, "series_id")

    def replace_epg(
        self,
        channels: dict[str, list[dict[str, Any]]],
        aliases: dict[str, str] | None = None,
    ) -> None:
        now = time.time()
        self.data.epg = channels
        if aliases is not None:
            self.data.aliases = dict(aliases)
        self.data.epg_updated_at = now
        self.link_stream_aliases(persist=True)

    def _write_epg(self) -> None:
        _live, _vod, _series, epg_path, _meta = self.paths()
        atomic_write_json(
            epg_path,
            {
                "updated_at": self.data.epg_updated_at,
                "channels": self.data.epg,
                "aliases": self.data.aliases,
            },
        )

    def link_stream_aliases(self, *, persist: bool) -> None:
        """Map stream names / epg_channel_id / stream_id onto XMLTV channel ids."""
        if not self.data.epg:
            return
        aliases = dict(self.data.aliases)
        for stream in self.data.streams:
            candidates = [
                str(stream.get("epg_channel_id") or "").strip(),
                str(stream.get("stream_id") or "").strip(),
                str(stream.get("name") or "").strip(),
            ]
            canon = None
            for cand in candidates:
                if not cand:
                    continue
                if cand in self.data.epg or cand.lower() in self.data.epg:
                    canon = cand if cand in self.data.epg else cand.lower()
                    break
                mapped = aliases.get(norm_epg_key(cand))
                if mapped and (mapped in self.data.epg or mapped.lower() in self.data.epg):
                    canon = mapped if mapped in self.data.epg else mapped.lower()
                    break
            if not canon:
                continue
            for cand in candidates:
                for key in epg_alias_keys(cand):
                    aliases.setdefault(key, canon)
        self.data.aliases = aliases
        if persist and self.data.epg_updated_at:
            self._write_epg()

    def write_meta(self) -> None:
        *_rest, meta_path = self.paths()
        atomic_write_json(meta_path, self.status())

    def has_live(self) -> bool:
        return bool(self.data.streams)

    def age_seconds(self) -> float | None:
        if not self.data.updated_at:
            return None
        return max(0.0, time.time() - self.data.updated_at)

    def status(self) -> dict[str, Any]:
        age = self.age_seconds()
        last_ok = None
        if self.data.updated_at:
            last_ok = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.data.updated_at))
        return {
            "ready": self.has_live(),
            "running": self.running,
            "progress": self.progress,
            "last_ok": last_ok,
            "age_seconds": None if age is None else int(age),
            "categories": len(self.data.categories),
            "streams": len(self.data.streams),
            "movies": len(self.vod.items),
            "series": len(self.series.items),
            "epg_channels": len(self.data.epg),
            "interval_seconds": int(self.interval_seconds),
            "last_error": self.last_error or None,
        }

    def live_categories(self) -> list[dict[str, Any]] | None:
        if not self.has_live():
            return None
        return self.data.categories

    def live_streams(self, category_id: str) -> list[dict[str, Any]] | None:
        if not self.has_live():
            return None
        cid = str(category_id or "").strip()
        if not cid:
            return []
        rows = self.data.by_cat.get(cid, [])
        return [self.decorate(stream) for stream in rows]

    def _library_categories(self, lib: ItemLibrary) -> list[dict[str, Any]] | None:
        if not lib.items:
            return None
        return lib.categories

    def _library_items(self, lib: ItemLibrary, category_id: str) -> list[dict[str, Any]] | None:
        if not lib.items:
            return None
        cid = str(category_id or "").strip()
        if not cid:
            return []
        return list(lib.by_cat.get(cid, []))

    def vod_categories(self) -> list[dict[str, Any]] | None:
        return self._library_categories(self.vod)

    def vod_streams(self, category_id: str) -> list[dict[str, Any]] | None:
        return self._library_items(self.vod, category_id)

    def series_categories(self) -> list[dict[str, Any]] | None:
        return self._library_categories(self.series)

    def series_list(self, category_id: str) -> list[dict[str, Any]] | None:
        return self._library_items(self.series, category_id)

    def decorate(self, stream: dict[str, Any]) -> dict[str, Any]:
        out = dict(stream)
        current, nxt = self.now_next_for_stream(out)
        title = (current or {}).get("title") or ""
        if not title:
            extra = decode_xtream_text(str(out.get("title") or ""))
            name = str(out.get("name") or "").strip()
            if extra and extra.lower() != name.lower():
                title = extra
        out["now_title"] = title
        out["next_title"] = (nxt or {}).get("title") or ""
        if current:
            if current.get("start"):
                out["now_start"] = current["start"]
            if current.get("stop"):
                out["now_stop"] = current["stop"]
            if current.get("desc"):
                out["now_desc"] = current["desc"]
        return out

    def now_next_for_stream(
        self, stream: dict[str, Any], now: int | None = None
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        rows = self._epg_rows_for_stream(stream)
        if not rows:
            return None, None
        return self._now_next_from_rows(rows, now)

    def now_next(self, epg_id: str, now: int | None = None) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        rows = self._epg_rows(epg_id)
        if not rows:
            return None, None
        return self._now_next_from_rows(rows, now)

    def _epg_rows_for_stream(self, stream: dict[str, Any]) -> list[dict[str, Any]] | None:
        return self._epg_rows(
            str(stream.get("epg_channel_id") or ""),
            str(stream.get("stream_id") or ""),
            str(stream.get("name") or ""),
        )

    def _epg_rows(self, *keys: str) -> list[dict[str, Any]] | None:
        for raw in keys:
            key = str(raw or "").strip()
            if not key:
                continue
            rows = self.data.epg.get(key) or self.data.epg.get(key.lower())
            if rows:
                return rows
            mapped = self.data.aliases.get(norm_epg_key(key))
            if not mapped and "." in key:
                mapped = self.data.aliases.get(norm_epg_key(key.rsplit(".", 1)[0]))
            if mapped:
                rows = self.data.epg.get(mapped) or self.data.epg.get(mapped.lower())
                if rows:
                    return rows
        return None

    def _now_next_from_rows(
        self, rows: list[dict[str, Any]], now: int | None = None
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        stamp = int(now or time.time())
        current = None
        nxt = None
        for row in rows:
            try:
                start = int(row["start"])
                stop = int(row["stop"])
            except (KeyError, TypeError, ValueError):
                continue
            if start <= stamp < stop:
                current = row
            elif start >= stamp:
                nxt = row
                break
        return current, nxt

    def listings_for_stream(self, stream_id: str, *, limit: int = 8) -> list[dict[str, Any]] | None:
        if not self.data.epg:
            return None
        stream = self.data.by_id.get(str(stream_id).strip())
        if not stream:
            return None
        rows = self._epg_rows_for_stream(stream)
        if not rows:
            return None
        stamp = int(time.time()) - 60
        out: list[dict[str, Any]] = []
        for row in rows:
            try:
                stop = int(row["stop"])
                start = int(row["start"])
            except (KeyError, TypeError, ValueError):
                continue
            if stop <= stamp:
                continue
            out.append(
                {
                    "title": row.get("title") or "",
                    "description": row.get("desc") or "",
                    "start_timestamp": start,
                    "stop_timestamp": stop,
                    "start": start,
                    "end": stop,
                }
            )
            if len(out) >= limit:
                break
        return out
