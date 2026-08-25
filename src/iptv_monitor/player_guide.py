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
EPG_NAME = "watch_epg.json"
META_NAME = "watch_sync.json"
_B64 = re.compile(r"^[A-Za-z0-9+/]{8,}={0,2}$")


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
    updated_at: float = 0.0
    epg_updated_at: float = 0.0


def index_streams(streams: list[dict[str, Any]]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]]]:
    by_cat: dict[str, list[dict[str, Any]]] = {}
    by_id: dict[str, dict[str, Any]] = {}
    for stream in streams:
        sid = str(stream.get("stream_id") or "").strip()
        if sid:
            by_id[sid] = stream
        for cid in category_ids_of(stream):
            by_cat.setdefault(cid, []).append(stream)
    return by_cat, by_id


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
        self.interval_seconds = 7200
        self.load_disk()

    def paths(self) -> tuple[Path, Path, Path]:
        folder = _state_dir(self.root)
        return folder / LIVE_NAME, folder / EPG_NAME, folder / META_NAME

    def load_disk(self) -> None:
        live_path, epg_path, _meta = self.paths()
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
        by_cat, by_id = index_streams(streams)
        self.data = GuideData(
            categories=with_counts(categories, by_cat),
            streams=streams,
            by_cat=by_cat,
            by_id=by_id,
            epg=epg,
            updated_at=updated,
            epg_updated_at=epg_updated,
        )
        logger.info(
            "Watch guide loaded: %s categories, %s streams, %s EPG channels",
            len(self.data.categories),
            len(self.data.streams),
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
            updated_at=now,
            epg_updated_at=self.data.epg_updated_at,
        )
        live_path, _epg, _meta = self.paths()
        atomic_write_json(
            live_path,
            {"updated_at": now, "categories": self.data.categories, "streams": streams},
        )

    def replace_epg(self, channels: dict[str, list[dict[str, Any]]]) -> None:
        now = time.time()
        self.data.epg = channels
        self.data.epg_updated_at = now
        _live, epg_path, _meta = self.paths()
        atomic_write_json(epg_path, {"updated_at": now, "channels": channels})

    def write_meta(self) -> None:
        _live, _epg, meta_path = self.paths()
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

    def decorate(self, stream: dict[str, Any]) -> dict[str, Any]:
        out = dict(stream)
        current, nxt = self.now_next(str(out.get("epg_channel_id") or "").strip())
        out["now_title"] = (current or {}).get("title") or ""
        out["next_title"] = (nxt or {}).get("title") or ""
        if current and current.get("stop"):
            out["now_stop"] = current["stop"]
        return out

    def now_next(self, epg_id: str, now: int | None = None) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        if not epg_id:
            return None, None
        rows = self.data.epg.get(epg_id) or self.data.epg.get(epg_id.lower())
        if not rows:
            return None, None
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
            return []
        epg_id = str(stream.get("epg_channel_id") or "").strip()
        rows = self.data.epg.get(epg_id) if epg_id else None
        if not rows:
            return []
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
