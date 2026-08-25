"""Background live catalogue + XMLTV pull for /watch.

Runs beside the dashboard. Every watch_sync_seconds (default 4 hours) downloads
live/VOD/series lists (skipping catch-all "All Channels" groups) and xmltv.php
into state/. Category clicks then read disk. Credentials never go in the JSON files.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from iptv_monitor.config import load_settings, resolve_paths
from iptv_monitor.player_guide import WatchGuide, decode_xtream_text, epg_alias_keys, is_uk_live_group
from iptv_monitor.player_xtream import (
    _CATEGORY_KEYS,
    _LIVE_KEYS,
    _SERIES_KEYS,
    _VOD_KEYS,
    _as_list,
    _pick,
    load_player_config,
)
from iptv_monitor.stream import _STREAM_UA

logger = logging.getLogger("iptv_monitor.player_sync")

LIVE_TIMEOUT = httpx.Timeout(connect=15.0, read=600.0, write=60.0, pool=15.0)
CAT_TIMEOUT = httpx.Timeout(connect=10.0, read=70.0, write=30.0, pool=10.0)
EPG_TIMEOUT = httpx.Timeout(connect=15.0, read=600.0, write=60.0, pool=15.0)
XMLTV_MAX_BYTES = 180_000_000
EPG_HORIZON = 24 * 3600
EPG_FLOOR = 15 * 60
EPG_PER_CHANNEL = 40
CAT_WORKERS = 4
_LIVE_SYNC_KEYS = _LIVE_KEYS
_CATCH_ALL = re.compile(
    r"^(all|all\s*(channels?|tvs?|tv|live|streams?)|for you)$",
    re.I,
)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def is_catch_all_category(name: str) -> bool:
    """Skip mega-lists like 'All Channels' that hang player_api and duplicate every group."""
    normalized = re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()
    if not normalized:
        return False
    if _CATCH_ALL.match(normalized):
        return True
    return "all channel" in normalized


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


def parse_xmltv_file(path: Path, now: int) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:
    """Keep programmes in a sliding window. elem.clear() so a 100MB XML does not stay in RAM."""
    floor = now - EPG_FLOOR
    horizon = now + EPG_HORIZON
    channels: dict[str, list[dict[str, Any]]] = {}
    aliases: dict[str, str] = {}

    def add_alias(raw: str, canon: str) -> None:
        for key in epg_alias_keys(raw):
            aliases.setdefault(key, canon)

    for _event, elem in ET.iterparse(path, events=("end",)):
        tag = _local_name(elem.tag)
        if tag == "channel":
            cid = str(elem.attrib.get("id") or "").strip()
            if cid:
                add_alias(cid, cid)
                for child in list(elem):
                    if _local_name(child.tag) == "display-name":
                        add_alias("".join(child.itertext()), cid)
            elem.clear()
            continue
        if tag != "programme":
            continue
        channel = str(elem.attrib.get("channel") or "").strip()
        start = parse_xmltv_time(elem.attrib.get("start") or "")
        stop = parse_xmltv_time(elem.attrib.get("stop") or "")
        if not channel or start is None or stop is None or stop <= floor or start >= horizon:
            elem.clear()
            continue
        add_alias(channel, channel)
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
    return channels, aliases


class WatchSyncer:
    def __init__(self, root: Path | None, guide: WatchGuide) -> None:
        self.root = root
        self.guide = guide
        self._lock = asyncio.Lock()

    def _interval(self) -> int:
        try:
            seconds = int(load_settings(resolve_paths(self.root).settings).watch_sync_seconds)
        except Exception:
            seconds = 14400
        return max(600, seconds)

    async def run_forever(self) -> None:
        """First sync if the on-disk guide is missing or stale, then every 4 hours."""
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
                    if not self.guide.last_error:
                        self.guide.last_error = "sync failed"
                    self.guide.finish_sync()
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
            self.guide.begin_sync()
            started = time.monotonic()
            try:
                self.guide.set_phase("live", message="Downloading live channels…")
                categories, streams = await asyncio.to_thread(self._download_live, cfg)
                self.guide.replace_live(categories, streams)
                logger.info(
                    "Watch guide live: %s categories, %s streams in %.1fs",
                    len(categories),
                    len(streams),
                    time.monotonic() - started,
                )
                self.guide.set_phase("epg", message="Downloading EPG…")
                epg_started = time.monotonic()
                try:
                    channels, aliases = await asyncio.to_thread(self._download_epg, cfg)
                    self.guide.replace_epg(channels, aliases)
                    logger.info(
                        "Watch guide EPG: %s channels in %.1fs",
                        len(channels),
                        time.monotonic() - epg_started,
                    )
                    self.guide.last_error = ""
                except Exception as exc:
                    logger.warning("Watch guide EPG failed: %s", exc)
                    self.guide.last_error = f"channels ok; EPG failed ({exc})"[:180]
                try:
                    self.guide.set_phase("movies", message="Downloading movies…")
                    vod_cats, vod_items = await asyncio.to_thread(self._download_vod, cfg)
                    self.guide.replace_vod(vod_cats, vod_items)
                    logger.info("Watch guide movies: %s titles", len(vod_items))
                except Exception as exc:
                    logger.warning("Watch guide movies failed: %s", exc)
                    self.guide.last_error = (self.guide.last_error or "") + f" movies: {exc}"[:80]
                try:
                    self.guide.set_phase("series", message="Downloading series…")
                    series_cats, series_items = await asyncio.to_thread(self._download_series, cfg)
                    self.guide.replace_series(series_cats, series_items)
                    logger.info("Watch guide series: %s titles", len(series_items))
                except Exception as exc:
                    logger.warning("Watch guide series failed: %s", exc)
                    self.guide.last_error = (self.guide.last_error or "") + f" series: {exc}"[:80]
                self.guide.progress = ""
                logger.info("Watch guide sync finished in %.1fs", time.monotonic() - started)
            except Exception as exc:
                self.guide.last_error = str(exc)[:180]
                raise
            finally:
                self.guide.finish_sync()

    def _client(self, timeout: httpx.Timeout) -> httpx.Client:
        return httpx.Client(
            verify=False,
            follow_redirects=True,
            timeout=timeout,
            headers={"User-Agent": _STREAM_UA, "Accept": "*/*"},
        )

    def _download_live(self, cfg) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        return self._download_by_category(
            cfg,
            cat_action="get_live_categories",
            list_action="get_live_streams",
            item_keys=_LIVE_SYNC_KEYS,
            id_key="stream_id",
            progress="Live",
        )

    def _download_vod(self, cfg) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        return self._download_by_category(
            cfg,
            cat_action="get_vod_categories",
            list_action="get_vod_streams",
            item_keys=_VOD_KEYS,
            id_key="stream_id",
            progress="Movies",
        )

    def _download_series(self, cfg) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        return self._download_by_category(
            cfg,
            cat_action="get_series_categories",
            list_action="get_series",
            item_keys=_SERIES_KEYS,
            id_key="series_id",
            progress="Series",
        )

    def _download_by_category(
        self,
        cfg,
        *,
        cat_action: str,
        list_action: str,
        item_keys: tuple[str, ...],
        id_key: str,
        progress: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        creds = {"username": cfg.username.strip(), "password": cfg.password.strip()}
        with self._client(LIVE_TIMEOUT) as client:
            cats_resp = client.get(
                f"{cfg.base}/player_api.php",
                params={**creds, "action": cat_action},
            )
        if cats_resp.status_code >= 400:
            raise RuntimeError(f"{progress} categories HTTP {cats_resp.status_code}")
        categories = [_pick(item, _CATEGORY_KEYS) for item in _as_list(cats_resp.json())]
        keep = [row for row in categories if not is_catch_all_category(str(row.get("category_name") or ""))]
        skipped_all = len(categories) - len(keep)
        if progress == "Live":
            uk = [row for row in keep if is_uk_live_group(str(row.get("category_name") or ""))]
            logger.info(
                "Watch guide Live: kept %s UK groups, skipped %s others",
                len(uk),
                len(keep) - len(uk),
            )
            keep = uk
        skipped = skipped_all
        total = len(keep)
        if skipped:
            logger.info("Watch guide %s: skipped %s catch-all groups", progress, skipped)
        phase = {"Live": "live", "Movies": "movies", "Series": "series"}.get(progress, progress.lower())
        self.guide.set_phase(phase, message=f"{progress} 0/{total} groups", total=total)
        by_id: dict[str, dict[str, Any]] = {}
        done = 0

        def fetch_group(cat: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
            name = str(cat.get("category_name") or cat.get("category_id") or "").strip()
            cid = str(cat.get("category_id") or "").strip()
            self.guide.group_start(name, phase, total)
            if not cid:
                return name, []
            try:
                with self._client(CAT_TIMEOUT) as client:
                    resp = client.get(
                        f"{cfg.base}/player_api.php",
                        params={**creds, "action": list_action, "category_id": cid},
                    )
            except Exception as exc:
                logger.warning("Watch guide %s group %s failed: %s", progress, cid, type(exc).__name__)
                return name, []
            if resp.status_code >= 400:
                logger.warning("Watch guide %s group %s HTTP %s", progress, cid, resp.status_code)
                return name, []
            try:
                payload = resp.json()
            except Exception:
                return name, []
            if isinstance(payload, dict):
                payload = payload.get("available_channels") or payload.get("streams") or payload
            return name, [_pick(item, item_keys) for item in _as_list(payload)]

        with ThreadPoolExecutor(max_workers=CAT_WORKERS) as pool:
            futures = [pool.submit(fetch_group, cat) for cat in keep]
            for fut in as_completed(futures):
                done += 1
                name, rows = fut.result()
                self.guide.group_done(name, done, total, phase)
                for row in rows:
                    sid = str(row.get(id_key) or "").strip()
                    if sid:
                        by_id[sid] = row
        items = list(by_id.values())
        if not items:
            raise RuntimeError(f"Panel returned no {progress.lower()} items")
        return keep, items

    def _download_epg(self, cfg) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:
        creds = {"username": cfg.username.strip(), "password": cfg.password.strip()}
        folder = resolve_paths(self.root).root / "state"
        folder.mkdir(parents=True, exist_ok=True)
        tmp = folder / "watch_epg.xml.tmp"
        try:
            with self._client(EPG_TIMEOUT) as client:
                with client.stream("GET", f"{cfg.base}/xmltv.php", params=creds) as response:
                    if response.status_code >= 400:
                        raise RuntimeError(f"xmltv HTTP {response.status_code}")
                    size = 0
                    try:
                        size = int(response.headers.get("content-length") or 0)
                    except (TypeError, ValueError):
                        size = 0
                    written = 0
                    with tmp.open("wb") as handle:
                        for chunk in response.iter_bytes():
                            written += len(chunk)
                            if written > XMLTV_MAX_BYTES:
                                raise RuntimeError("xmltv larger than 180MB, aborting")
                            handle.write(chunk)
                            self.guide.set_epg_bytes(written, size)
            logger.info("Watch guide xmltv downloaded (%s bytes)", tmp.stat().st_size)
            self.guide.note("Parsing XMLTV…", "Parsing EPG…")
            return parse_xmltv_file(tmp, int(time.time()))
        finally:
            tmp.unlink(missing_ok=True)
