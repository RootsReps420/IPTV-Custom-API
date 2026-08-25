"""Background live catalogue + XMLTV pull for /watch.

Runs beside the dashboard. Every watch_sync_seconds (default 2 hours) downloads
get_live_categories, get_live_streams (all channels), and xmltv.php into state/.
Category clicks then read disk. Credentials never go in the JSON files.
"""

from __future__ import annotations

import asyncio
import logging
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from iptv_monitor.config import load_settings, resolve_paths
from iptv_monitor.player_guide import WatchGuide, decode_xtream_text
from iptv_monitor.player_xtream import (
    _CATEGORY_KEYS,
    _LIVE_KEYS,
    _as_list,
    _pick,
    load_player_config,
)
from iptv_monitor.stream import _STREAM_UA

logger = logging.getLogger("iptv_monitor.player_sync")

LIVE_TIMEOUT = httpx.Timeout(connect=15.0, read=600.0, write=60.0, pool=15.0)
EPG_TIMEOUT = httpx.Timeout(connect=15.0, read=600.0, write=60.0, pool=15.0)
XMLTV_MAX_BYTES = 180_000_000
EPG_HORIZON = 24 * 3600
EPG_FLOOR = 15 * 60
EPG_PER_CHANNEL = 40
_LIVE_SYNC_KEYS = _LIVE_KEYS


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_xmltv_time(value: str) -> int | None:
    text = (value or "").strip()
    if len(text) < 14:
        return None
    try:
        dt = datetime.strptime(text[:14], "%Y%m%d%H%M%S")
    except ValueError:
        return None
    tz = text[14:].strip().replace(":", "")
    if tz and tz[0] in "+-" and len(tz) >= 5:
        sign = 1 if tz[0] == "+" else -1
        hours = int(tz[1:3])
        mins = int(tz[3:5])
        dt = dt.replace(tzinfo=timezone(sign * timedelta(hours=hours, minutes=mins)))
    else:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def parse_xmltv_file(path: Path, now: int) -> dict[str, list[dict[str, Any]]]:
    """Keep programmes in a sliding window. elem.clear() so a 100MB XML does not stay in RAM."""
    floor = now - EPG_FLOOR
    horizon = now + EPG_HORIZON
    channels: dict[str, list[dict[str, Any]]] = {}
    for _event, elem in ET.iterparse(path, events=("end",)):
        if _local_name(elem.tag) != "programme":
            continue
        channel = str(elem.attrib.get("channel") or "").strip()
        start = parse_xmltv_time(elem.attrib.get("start") or "")
        stop = parse_xmltv_time(elem.attrib.get("stop") or "")
        if not channel or start is None or stop is None or stop <= floor or start >= horizon:
            elem.clear()
            continue
        title = ""
        desc = ""
        for child in list(elem):
            name = _local_name(child.tag)
            if name == "title" and not title:
                title = decode_xtream_text("".join(child.itertext()))
            elif name in {"desc", "sub-title"} and not desc:
                desc = decode_xtream_text("".join(child.itertext()))[:400]
        bucket = channels.setdefault(channel, [])
        if len(bucket) < EPG_PER_CHANNEL:
            bucket.append({"start": start, "stop": stop, "title": title, "desc": desc})
        elem.clear()
    for rows in channels.values():
        rows.sort(key=lambda row: int(row["start"]))
    return channels


class WatchSyncer:
    def __init__(self, root: Path | None, guide: WatchGuide) -> None:
        self.root = root
        self.guide = guide
        self._lock = asyncio.Lock()

    def _interval(self) -> int:
        try:
            seconds = int(load_settings(resolve_paths(self.root).settings).watch_sync_seconds)
        except Exception:
            seconds = 7200
        return max(600, seconds)

    async def run_forever(self) -> None:
        """First sync if the on-disk guide is missing or older than the interval, then every 2 hours."""
        await asyncio.sleep(8)
        while True:
            interval = self._interval()
            self.guide.interval_seconds = interval
            age = self.guide.age_seconds()
            if age is None or age >= interval:
                try:
                    await self.sync_once()
                except Exception:
                    logger.exception("Watch guide sync failed")
                    self.guide.last_error = "sync failed"
                    self.guide.running = False
                    self.guide.write_meta()
                    await asyncio.sleep(120)
                    continue
            wait = interval - (self.guide.age_seconds() or 0)
            await asyncio.sleep(max(60, wait))

    async def sync_once(self) -> None:
        async with self._lock:
            cfg = load_player_config(self.root)
            if not cfg.configured:
                self.guide.progress = "Watch player is not configured."
                self.guide.write_meta()
                return
            self.guide.running = True
            self.guide.last_error = ""
            started = time.monotonic()
            try:
                self.guide.progress = "Downloading live channels…"
                self.guide.write_meta()
                categories, streams = await asyncio.to_thread(self._download_live, cfg)
                self.guide.replace_live(categories, streams)
                logger.info(
                    "Watch guide live: %s categories, %s streams in %.1fs",
                    len(categories),
                    len(streams),
                    time.monotonic() - started,
                )
                self.guide.progress = "Downloading EPG…"
                self.guide.write_meta()
                epg_started = time.monotonic()
                try:
                    channels = await asyncio.to_thread(self._download_epg, cfg)
                    self.guide.replace_epg(channels)
                    logger.info(
                        "Watch guide EPG: %s channels in %.1fs",
                        len(channels),
                        time.monotonic() - epg_started,
                    )
                    self.guide.last_error = ""
                except Exception as exc:
                    logger.warning("Watch guide EPG failed: %s", exc)
                    self.guide.last_error = f"channels ok; EPG failed ({exc})"[:180]
                self.guide.progress = ""
            except Exception as exc:
                self.guide.last_error = str(exc)[:180]
                raise
            finally:
                self.guide.running = False
                self.guide.progress = ""
                self.guide.write_meta()
                logger.info("Watch guide sync finished in %.1fs", time.monotonic() - started)

    def _client(self, timeout: httpx.Timeout) -> httpx.Client:
        return httpx.Client(
            verify=False,
            follow_redirects=True,
            timeout=timeout,
            headers={"User-Agent": _STREAM_UA, "Accept": "*/*"},
        )

    def _download_live(self, cfg) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        creds = {"username": cfg.username.strip(), "password": cfg.password.strip()}
        with self._client(LIVE_TIMEOUT) as client:
            cats_resp = client.get(
                f"{cfg.base}/player_api.php",
                params={**creds, "action": "get_live_categories"},
            )
            if cats_resp.status_code >= 400:
                raise RuntimeError(f"categories HTTP {cats_resp.status_code}")
            categories = [_pick(item, _CATEGORY_KEYS) for item in _as_list(cats_resp.json())]
            streams_resp = client.get(
                f"{cfg.base}/player_api.php",
                params={**creds, "action": "get_live_streams"},
            )
            if streams_resp.status_code >= 400:
                raise RuntimeError(f"live streams HTTP {streams_resp.status_code}")
            payload = streams_resp.json()
        if isinstance(payload, dict):
            payload = payload.get("available_channels") or payload.get("streams") or payload
        streams = [_pick(item, _LIVE_SYNC_KEYS) for item in _as_list(payload)]
        if not streams:
            raise RuntimeError("Panel returned no live streams")
        return categories, streams

    def _download_epg(self, cfg) -> dict[str, list[dict[str, Any]]]:
        creds = {"username": cfg.username.strip(), "password": cfg.password.strip()}
        folder = resolve_paths(self.root).root / "state"
        folder.mkdir(parents=True, exist_ok=True)
        tmp = folder / "watch_epg.xml.tmp"
        try:
            with self._client(EPG_TIMEOUT) as client:
                with client.stream("GET", f"{cfg.base}/xmltv.php", params=creds) as response:
                    if response.status_code >= 400:
                        raise RuntimeError(f"xmltv HTTP {response.status_code}")
                    written = 0
                    with tmp.open("wb") as handle:
                        for chunk in response.iter_bytes():
                            written += len(chunk)
                            if written > XMLTV_MAX_BYTES:
                                raise RuntimeError("xmltv larger than 180MB, aborting")
                            handle.write(chunk)
            logger.info("Watch guide xmltv downloaded (%s bytes)", tmp.stat().st_size)
            return parse_xmltv_file(tmp, int(time.time()))
        finally:
            tmp.unlink(missing_ok=True)
