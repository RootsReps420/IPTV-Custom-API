"""Background live catalogue + EPG pull for /watch.

Runs beside the dashboard. Live, EPG, and movies/shows refresh every
watch_sync_seconds / watch_library_sync_seconds (default 4 hours).
Category clicks then read disk. Magnum live M3U playback URLs stay in state/
on the server and are stripped from every browser payload.
"""

from __future__ import annotations

import asyncio
import gzip
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
from iptv_monitor.player_guide import (
    WatchGuide,
    decode_xtream_text,
    epg_alias_keys,
    is_wanted_library_group,
    is_wanted_live_group,
    listings_to_guide_rows,
)
from iptv_monitor.player_m3u import (
    M3U_MAX_BYTES,
    download_bytes,
    download_file,
    header_host,
    live_from_m3u_text,
)
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
CAT_RETRY_TIMEOUT = httpx.Timeout(connect=15.0, read=120.0, write=30.0, pool=10.0)
EPG_TIMEOUT = httpx.Timeout(connect=8.0, read=25.0, write=15.0, pool=8.0)
PLAYLIST_TIMEOUT = httpx.Timeout(connect=20.0, read=300.0, write=60.0, pool=20.0)
FORCE_SYNC_NAME = "watch_force_sync"
FORCE_PLAYLIST_NAME = "watch_force_playlist"
FORCE_EPG_NAME = "watch_force_epg"
XMLTV_MAX_BYTES = 180_000_000
EPG_HORIZON = 24 * 3600
EPG_FLOOR = 15 * 60
EPG_PER_CHANNEL = 40
CAT_WORKERS = 4
EPG_WORKERS = 8
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


def _open_xmltv(path: Path):
    with path.open("rb") as probe:
        magic = probe.read(2)
    if magic == b"\x1f\x8b":
        return gzip.open(path, "rb")
    return path.open("rb")


def parse_xmltv_file(path: Path, now: int) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:
    """Keep programmes in a sliding window. elem.clear() so a large XML does not stay in RAM.

    GitHub XMLTV is often .xml.gz; iterparse the gzip stream instead of writing hundreds of MB to disk.
    """
    floor = now - EPG_FLOOR
    horizon = now + EPG_HORIZON
    channels: dict[str, list[dict[str, Any]]] = {}
    aliases: dict[str, str] = {}

    def add_alias(raw: str, canon: str) -> None:
        for key in epg_alias_keys(raw):
            aliases.setdefault(key, canon)

    with _open_xmltv(path) as handle:
        for _event, elem in ET.iterparse(handle, events=("end",)):
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


def _state_dir(root: Path | None) -> Path:
    return resolve_paths(root).root / "state"


def queue_watch_force(root: Path | None, kind: str) -> str:
    """Write a force-sync flag. kind is playlist, epg, or all."""
    name = {
        "playlist": FORCE_PLAYLIST_NAME,
        "epg": FORCE_EPG_NAME,
        "all": FORCE_SYNC_NAME,
    }.get((kind or "").strip().lower())
    if not name:
        raise ValueError("kind must be playlist, epg, or all")
    path = _state_dir(root) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("1\n", encoding="utf-8")
    return kind.strip().lower()


class WatchSyncer:
    def __init__(self, root: Path | None, guide: WatchGuide) -> None:
        self.root = root
        self.guide = guide
        self._lock = asyncio.Lock()
        self._wake = asyncio.Event()

    def wake(self) -> None:
        self._wake.set()

    def request(self, kind: str) -> dict[str, Any]:
        queued = queue_watch_force(self.root, kind)
        self.wake()
        return {"ok": True, "queued": queued, "running": bool(self.guide.running)}

    def _interval(self) -> int:
        try:
            seconds = int(load_settings(resolve_paths(self.root).settings).watch_sync_seconds)
        except Exception:
            seconds = 14400
        return max(600, seconds)

    def _library_interval(self) -> int:
        try:
            seconds = int(load_settings(resolve_paths(self.root).settings).watch_library_sync_seconds)
        except Exception:
            seconds = 14400
        return max(600, seconds)

    def _library_fresh(self, lib) -> bool:
        age = self.guide.library_age_seconds(lib)
        return bool(lib.items and age is not None and age < self._library_interval())

    def _epg_fresh(self) -> bool:
        """Skip EPG if we already stored now/next within the live sync interval."""
        if not self.guide.data.epg:
            return False
        stamp = float(self.guide.data.epg_updated_at or 0)
        if stamp <= 0:
            return False
        return (time.time() - stamp) < self._interval()

    def _force_paths(self) -> tuple[Path, Path, Path]:
        folder = _state_dir(self.root)
        return folder / FORCE_SYNC_NAME, folder / FORCE_PLAYLIST_NAME, folder / FORCE_EPG_NAME

    def _force_pending(self) -> bool:
        return any(path.exists() for path in self._force_paths())

    def _unlink_force(self, path: Path) -> bool:
        if not path.exists():
            return False
        try:
            path.unlink()
        except OSError:
            logger.warning("Watch guide could not remove force-sync flag %s", path.name)
        return True

    def _consume_force(self) -> tuple[bool, bool]:
        """Return (force_playlist, force_epg). watch_force_sync still means both."""
        all_path, playlist_path, epg_path = self._force_paths()
        force_all = self._unlink_force(all_path)
        force_playlist = force_all or self._unlink_force(playlist_path)
        force_epg = force_all or self._unlink_force(epg_path)
        return force_playlist, force_epg

    async def _wait_for_next(self, seconds: float) -> None:
        """Sleep until due, or until a UI/SSH force flag arrives."""
        remaining = max(0.0, float(seconds))
        self._wake.clear()
        while remaining > 0:
            if self._force_pending():
                return
            chunk = min(15.0, remaining)
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=chunk)
                self._wake.clear()
                return
            except TimeoutError:
                remaining -= chunk

    async def run_forever(self) -> None:
        """Sync live, movies/shows, and EPG on the configured 4-hour cadence."""
        await asyncio.sleep(8)
        while True:
            interval = self._interval()
            lib_interval = self._library_interval()
            self.guide.interval_seconds = interval
            self.guide.library_interval_seconds = lib_interval
            force_playlist, force_epg = self._consume_force()
            age = self.guide.age_seconds()
            need_live = age is None or age >= interval
            need_lib = not self._library_fresh(self.guide.vod) or not self._library_fresh(self.guide.series)
            need_epg = self.guide.has_live() and not self._epg_fresh()
            try:
                cfg = load_player_config(self.root)
                if cfg.configured and bool(cfg.live_m3u_url) != self.guide.live_from_m3u():
                    need_live = True
                    need_epg = True
            except Exception:
                pass
            if force_playlist or force_epg or need_live or need_lib or need_epg:
                try:
                    await self.sync_once(
                        force_playlist=force_playlist,
                        force_epg=force_epg,
                    )
                except Exception:
                    logger.exception("Watch guide sync failed")
                    if not self.guide.last_error:
                        self.guide.last_error = "sync failed"
                    self.guide.finish_sync()
                    await asyncio.sleep(120)
                    continue
            waits: list[float] = []
            live_age = self.guide.age_seconds()
            if live_age is not None:
                waits.append(interval - live_age)
            for lib in (self.guide.vod, self.guide.series):
                lib_age = self.guide.library_age_seconds(lib)
                if lib_age is not None:
                    waits.append(lib_interval - lib_age)
            stamp = float(self.guide.data.epg_updated_at or 0)
            if stamp > 0 and self.guide.has_live():
                waits.append(interval - (time.time() - stamp))
            elif self.guide.has_live() and not self._epg_fresh():
                waits.append(180)
            wait = min(waits) if waits else 60
            if wait <= 0 and not self._force_pending():
                wait = 60
            await self._wait_for_next(wait)

    async def sync_once(self, *, force: bool = False, force_playlist: bool = False, force_epg: bool = False) -> None:
        if force:
            force_playlist = True
            force_epg = True
        async with self._lock:
            cfg = load_player_config(self.root)
            if not cfg.configured:
                self.guide.progress = "Watch player is not configured."
                self.guide.write_meta()
                return
            if force_playlist and force_epg:
                logger.info("Watch guide forced full refresh (live, movies, series, EPG)")
            elif force_playlist:
                logger.info("Watch guide forced playlist refresh (live, movies, series)")
            elif force_epg:
                logger.info("Watch guide forced EPG refresh")
            self.guide.begin_sync()
            started = time.monotonic()
            interval = self._interval()
            lib_interval = self._library_interval()
            self.guide.interval_seconds = interval
            self.guide.library_interval_seconds = lib_interval
            age = self.guide.age_seconds()
            want_m3u = bool(cfg.live_m3u_url)
            source_mismatch = want_m3u != self.guide.live_from_m3u()
            live_fresh = (
                (not force_playlist)
                and (not source_mismatch)
                and bool(self.guide.has_live() and age is not None and age < interval)
            )
            vod_fresh = (not force_playlist) and self._library_fresh(self.guide.vod)
            series_fresh = (not force_playlist) and self._library_fresh(self.guide.series)
            epg_ok = (not force_epg) and (not source_mismatch) and self._epg_fresh()
            try:
                header_epg = ""
                if live_fresh:
                    logger.info(
                        "Watch guide live still fresh (%ss old, %s streams); skipping live download",
                        int(age or 0),
                        len(self.guide.data.streams),
                    )
                else:
                    self.guide.set_phase("live", message="Downloading live channels…")
                    categories, streams, header_epg = await asyncio.to_thread(
                        self._download_live, cfg
                    )
                    source = "m3u" if want_m3u else "xtream"
                    self.guide.replace_live(categories, streams, source=source)
                    logger.info(
                        "Watch guide live: %s categories, %s streams (%s) in %.1fs",
                        len(categories),
                        len(streams),
                        source,
                        time.monotonic() - started,
                    )
                if vod_fresh:
                    logger.info(
                        "Watch guide movies still fresh (%ss old, %s titles); skipping",
                        int(self.guide.library_age_seconds(self.guide.vod) or 0),
                        len(self.guide.vod.items),
                    )
                else:
                    try:
                        self.guide.set_phase("movies", message="Downloading movies…")
                        vod_cats, vod_items = await asyncio.to_thread(self._download_vod, cfg)
                        self.guide.replace_vod(vod_cats, vod_items)
                        logger.info("Watch guide movies: %s titles", len(vod_items))
                    except Exception as exc:
                        logger.warning("Watch guide movies failed: %s", exc)
                        self.guide.last_error = (self.guide.last_error or "") + f" movies: {exc}"[:80]
                if series_fresh:
                    logger.info(
                        "Watch guide series still fresh (%ss old, %s titles); skipping",
                        int(self.guide.library_age_seconds(self.guide.series) or 0),
                        len(self.guide.series.items),
                    )
                else:
                    try:
                        self.guide.set_phase("series", message="Downloading series…")
                        series_cats, series_items = await asyncio.to_thread(self._download_series, cfg)
                        self.guide.replace_series(series_cats, series_items)
                        logger.info("Watch guide series: %s titles", len(series_items))
                    except Exception as exc:
                        logger.warning("Watch guide series failed: %s", exc)
                        self.guide.last_error = (self.guide.last_error or "") + f" series: {exc}"[:80]
                if epg_ok:
                    logger.info(
                        "Watch guide EPG still fresh (%s channels); skipping",
                        len(self.guide.data.epg),
                    )
                else:
                    self.guide.set_phase("epg", message="Downloading EPG…")
                    epg_started = time.monotonic()
                    epg_url = cfg.live_epg_url or header_epg
                    use_xmltv = bool(epg_url) or want_m3u
                    try:
                        if use_xmltv:
                            if not epg_url:
                                logger.warning(
                                    "Watch guide EPG skipped: live M3U has no url-tvg and live_epg is empty"
                                )
                                filled = 0
                            else:
                                filled = await asyncio.to_thread(self._download_xmltv_epg, epg_url)
                        else:
                            filled = await asyncio.to_thread(self._download_short_epg, cfg)
                        logger.info(
                            "Watch guide EPG: %s channels in %.1fs",
                            filled,
                            time.monotonic() - epg_started,
                        )
                    except Exception as exc:
                        logger.warning("Watch guide EPG failed: %s", exc)
                        self.guide.last_error = f"channels ok; EPG failed ({exc})"[:180]
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

    def _download_live(self, cfg) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
        if cfg.live_m3u_url:
            return self._download_live_m3u(cfg)
        categories, streams = self._download_by_category(
            cfg,
            cat_action="get_live_categories",
            list_action="get_live_streams",
            item_keys=_LIVE_SYNC_KEYS,
            id_key="stream_id",
            progress="Live",
            previous_by_cat=self.guide.data.by_cat,
        )
        return categories, streams, ""

    def _download_live_m3u(self, cfg) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
        url = cfg.live_m3u_url
        logger.info("Watch guide live: downloading M3U from %s", header_host(url))
        self.guide.set_phase("live", message="Downloading live playlist…")
        data = download_bytes(url, max_bytes=M3U_MAX_BYTES, timeout=PLAYLIST_TIMEOUT)
        text = data.decode("utf-8", errors="replace")
        epg_url, categories, streams = live_from_m3u_text(text)
        keep = [
            row
            for row in categories
            if not is_catch_all_category(str(row.get("category_name") or ""))
        ]
        if keep and len(keep) < len(categories):
            keep_ids = {str(row.get("category_id") or "") for row in keep}
            streams = [row for row in streams if str(row.get("category_id") or "") in keep_ids]
            categories = keep
            logger.info("Watch guide live M3U: skipped catch-all groups")
        if not streams:
            raise RuntimeError("Live M3U contained no channels")
        logger.info(
            "Watch guide live M3U: %s groups, %s channels",
            len(categories),
            len(streams),
        )
        return categories, streams, epg_url

    def _download_xmltv_epg(self, url: str) -> int:
        folder = _state_dir(self.root)
        raw_path = folder / "watch_epg.bin.tmp"
        xml_path = folder / "watch_epg.xml.tmp"
        logger.info("Watch guide EPG: downloading XMLTV from %s", header_host(url))

        def progress(written: int, total: int) -> None:
            self.guide.set_epg_bytes(written, total)

        try:
            download_file(
                url,
                raw_path,
                max_bytes=XMLTV_MAX_BYTES,
                timeout=PLAYLIST_TIMEOUT,
                on_bytes=progress,
            )
            self.guide.set_phase("epg", message="Parsing EPG…")
            channels, aliases = parse_xmltv_file(raw_path, int(time.time()))
            self.guide.replace_epg(channels, aliases)
            return len(channels)
        finally:
            raw_path.unlink(missing_ok=True)
            xml_path.unlink(missing_ok=True)

    def _download_vod(self, cfg) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        return self._download_by_category(
            cfg,
            cat_action="get_vod_categories",
            list_action="get_vod_streams",
            item_keys=_VOD_KEYS,
            id_key="stream_id",
            progress="Movies",
            previous_by_cat=self.guide.vod.by_cat,
        )

    def _download_series(self, cfg) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        return self._download_by_category(
            cfg,
            cat_action="get_series_categories",
            list_action="get_series",
            item_keys=_SERIES_KEYS,
            id_key="series_id",
            progress="Series",
            previous_by_cat=self.guide.series.by_cat,
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
        previous_by_cat: dict[str, list[dict[str, Any]]] | None = None,
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
            wanted = [row for row in keep if is_wanted_live_group(str(row.get("category_name") or ""))]
            logger.info(
                "Watch guide Live: kept %s groups, skipped %s others",
                len(wanted),
                len(keep) - len(wanted),
            )
            keep = wanted
        elif progress in {"Movies", "Series"}:
            wanted = [row for row in keep if is_wanted_library_group(str(row.get("category_name") or ""))]
            logger.info(
                "Watch guide %s: kept %s groups, skipped %s Arabic/Turkish/MENA",
                progress,
                len(wanted),
                len(keep) - len(wanted),
            )
            keep = wanted
        skipped = skipped_all
        total = len(keep)
        if skipped:
            logger.info("Watch guide %s: skipped %s catch-all groups", progress, skipped)
        phase = {"Live": "live", "Movies": "movies", "Series": "series"}.get(progress, progress.lower())
        self.guide.set_phase(phase, message=f"{progress} 0/{total} groups", total=total)
        by_id: dict[str, dict[str, Any]] = {}
        done = 0
        failed: list[dict[str, Any]] = []
        previous_by_cat = previous_by_cat or {}

        def fetch_group(
            cat: dict[str, Any], timeout: httpx.Timeout
        ) -> tuple[str, list[dict[str, Any]], dict[str, Any], bool]:
            name = str(cat.get("category_name") or cat.get("category_id") or "").strip()
            cid = str(cat.get("category_id") or "").strip()
            self.guide.group_start(name, phase, total)
            if not cid:
                return name, [], cat, True
            try:
                with self._client(timeout) as client:
                    resp = client.get(
                        f"{cfg.base}/player_api.php",
                        params={**creds, "action": list_action, "category_id": cid},
                    )
            except Exception as exc:
                logger.warning("Watch guide %s group %s failed: %s", progress, cid, type(exc).__name__)
                return name, [], cat, False
            if resp.status_code >= 400:
                logger.warning("Watch guide %s group %s HTTP %s", progress, cid, resp.status_code)
                return name, [], cat, False
            try:
                payload = resp.json()
            except Exception:
                logger.warning("Watch guide %s group %s returned invalid JSON", progress, cid)
                return name, [], cat, False
            if isinstance(payload, dict):
                payload = payload.get("available_channels") or payload.get("streams") or payload
            return name, [_pick(item, item_keys) for item in _as_list(payload)], cat, True

        def absorb(name: str, rows: list[dict[str, Any]], cat: dict[str, Any], ok: bool) -> None:
            nonlocal done
            done += 1
            self.guide.group_done(name, done, total, phase)
            if not ok:
                failed.append(cat)
                return
            for row in rows:
                sid = str(row.get(id_key) or "").strip()
                if sid:
                    by_id[sid] = row

        with ThreadPoolExecutor(max_workers=CAT_WORKERS) as pool:
            futures = [pool.submit(fetch_group, cat, CAT_TIMEOUT) for cat in keep]
            for fut in as_completed(futures):
                absorb(*fut.result())

        if failed:
            retry_cats = list(failed)
            failed = []
            logger.warning("Watch guide %s: retrying %s timed-out groups", progress, len(retry_cats))
            with ThreadPoolExecutor(max_workers=max(1, CAT_WORKERS // 2)) as pool:
                futures = [pool.submit(fetch_group, cat, CAT_RETRY_TIMEOUT) for cat in retry_cats]
                for fut in as_completed(futures):
                    name, rows, cat, ok = fut.result()
                    if not ok:
                        failed.append(cat)
                        continue
                    for row in rows:
                        sid = str(row.get(id_key) or "").strip()
                        if sid:
                            by_id[sid] = row

        if failed:
            kept_old = 0
            for cat in failed:
                cid = str(cat.get("category_id") or "").strip()
                name = str(cat.get("category_name") or cid).strip()
                logger.warning("Watch guide %s group still missing after retry: %s (%s)", progress, name, cid)
                for row in previous_by_cat.get(cid, []):
                    sid = str(row.get(id_key) or "").strip()
                    if sid and sid not in by_id:
                        by_id[sid] = row
                        kept_old += 1
            if kept_old:
                logger.info("Watch guide %s: kept %s previous items from failed groups", progress, kept_old)

        items = list(by_id.values())
        if not items:
            raise RuntimeError(f"Panel returned no {progress.lower()} items")
        return keep, items

    def _download_short_epg(self, cfg) -> int:
        """Now/next for UK live streams via get_short_epg. xmltv.php is too large/slow on this panel."""
        streams = list(self.guide.data.streams)
        total = len(streams)
        self.guide.set_phase("epg", message=f"EPG 0/{total} channels", total=total)
        if not total:
            return 0
        creds = {"username": cfg.username.strip(), "password": cfg.password.strip()}
        filled = 0
        done = 0
        limits = httpx.Limits(max_connections=EPG_WORKERS, max_keepalive_connections=EPG_WORKERS)

        def fetch(stream: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
            sid = str(stream.get("stream_id") or "").strip()
            if not sid:
                return stream, []
            try:
                resp = client.get(
                    f"{cfg.base}/player_api.php",
                    params={**creds, "action": "get_short_epg", "stream_id": sid, "limit": "4"},
                )
            except Exception:
                return stream, []
            if resp.status_code >= 400:
                return stream, []
            try:
                payload = resp.json()
            except Exception:
                return stream, []
            listings = payload.get("epg_listings") if isinstance(payload, dict) else payload
            if not isinstance(listings, list):
                return stream, []
            return stream, listings_to_guide_rows(listings)

        with httpx.Client(
            verify=False,
            follow_redirects=True,
            timeout=EPG_TIMEOUT,
            headers={"User-Agent": _STREAM_UA, "Accept": "application/json"},
            limits=limits,
        ) as client:
            with ThreadPoolExecutor(max_workers=EPG_WORKERS) as pool:
                futures = [pool.submit(fetch, stream) for stream in streams]
                for fut in as_completed(futures):
                    done += 1
                    stream, rows = fut.result()
                    name = str(stream.get("name") or stream.get("stream_id") or "").strip()
                    if rows:
                        self.guide.ingest_short_epg(stream, rows)
                        filled += 1
                    self.guide.group_done(name, done, total, "epg")
                    if done % 80 == 0:
                        self.guide.persist_epg()
        self.guide.persist_epg()
        tmp = resolve_paths(self.root).root / "state" / "watch_epg.xml.tmp"
        tmp.unlink(missing_ok=True)
        return filled
