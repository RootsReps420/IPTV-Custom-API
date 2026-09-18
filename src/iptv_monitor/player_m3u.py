"""Parse and download the Magnum live M3U used by /watch TV.

Stream URLs (which contain panel credentials) stay server-side. The browser
only sees stream_id / name / logo / now-next. Movies and shows are not read
from this file — those stay on Xtream player_api.
"""

from __future__ import annotations

import hashlib
import html
import logging
import re
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse, urlunparse

import httpx

logger = logging.getLogger("iptv_monitor.player_m3u")

# Google Drive refuses a VLC user-agent; GitHub is fine with either.
PLAYLIST_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
M3U_MAX_BYTES = 40_000_000
_ATTR = re.compile(r'([A-Za-z0-9-]+)="([^"]*)"')
_HEADER_TVG = re.compile(
    r"(?:url-tvg|x-tvg-url|tvg-url)\s*=\s*(?:\"([^\"]+)\"|(\S+))",
    re.I,
)
_XTREAM_ID = re.compile(r"/(\d+)\.(ts|m3u8|mp4)$", re.I)
_SLUG = re.compile(r"[^a-z0-9]+")
_VOD_PATH = re.compile(r"/(movie|series)/", re.I)


def playlist_headers() -> dict[str, str]:
    return {"User-Agent": PLAYLIST_UA, "Accept": "*/*"}


def playlist_client(timeout: httpx.Timeout) -> httpx.Client:
    return httpx.Client(
        verify=True,
        follow_redirects=True,
        timeout=timeout,
        headers=playlist_headers(),
    )


def header_host(url: str) -> str:
    return urlparse(url).netloc or "playlist"


def with_live_ext(url: str, ext: str) -> str:
    """Xtream live paths usually exist as both .ts and .m3u8; match the player."""
    suffix = (ext or "ts").lstrip(".").lower()
    if suffix not in {"ts", "m3u8"}:
        return url
    parsed = urlparse(url)
    path = parsed.path
    lower = path.lower()
    if suffix == "m3u8" and lower.endswith(".ts"):
        path = path[: -len(".ts")] + ".m3u8"
    elif suffix == "ts" and lower.endswith(".m3u8"):
        path = path[: -len(".m3u8")] + ".ts"
    else:
        return url
    return urlunparse(
        (parsed.scheme, parsed.netloc, path, parsed.params, parsed.query, parsed.fragment)
    )


def parse_header_epg(line: str) -> str:
    match = _HEADER_TVG.search(line or "")
    if not match:
        return ""
    raw = (match.group(1) or match.group(2) or "").strip().strip("'")
    return raw.split(",")[0].strip()


def parse_extinf(line: str) -> dict[str, str]:
    body = line[7:].lstrip() if line.startswith("#EXTINF") else line
    if "," in body:
        meta, name = body.rsplit(",", 1)
    else:
        meta, name = body, ""
    attrs = {key.lower(): html.unescape(val) for key, val in _ATTR.findall(meta)}
    display = html.unescape(name).strip() or (attrs.get("tvg-name") or "").strip()
    return {
        "name": display,
        "tvg-id": (attrs.get("tvg-id") or "").strip(),
        "tvg-logo": (attrs.get("tvg-logo") or "").strip(),
        "group-title": (attrs.get("group-title") or "").strip(),
        "tvg-chno": (attrs.get("tvg-chno") or attrs.get("channel-number") or "").strip(),
    }


def _stream_id(url: str, used: set[str]) -> str:
    path = urlparse(url).path
    match = _XTREAM_ID.search(path)
    sid = match.group(1) if match else hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    if sid in used:
        sid = hashlib.sha1(f"{sid}:{url}".encode("utf-8")).hexdigest()[:16]
    used.add(sid)
    return sid


def _category_id(name: str, used: dict[str, str]) -> str:
    if name in used:
        return used[name]
    slug = _SLUG.sub("-", name.lower()).strip("-")[:60]
    if not slug:
        slug = "g-" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:10]
    base = slug
    n = 2
    taken = set(used.values())
    while slug in taken:
        slug = f"{base}-{n}"
        n += 1
    used[name] = slug
    return slug


def parse_m3u(text: str) -> tuple[str, list[dict[str, str]]]:
    """Return (epg_url from header, live entries with playback_url)."""
    epg_url = ""
    pending: dict[str, str] | None = None
    entries: list[dict[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXTM3U"):
            epg_url = parse_header_epg(line) or epg_url
            continue
        if line.startswith("#EXTINF"):
            pending = parse_extinf(line)
            continue
        if line.startswith("#"):
            continue
        if pending is None:
            continue
        pending["playback_url"] = line
        entries.append(pending)
        pending = None
    return epg_url, entries


def entries_to_live(entries: list[dict[str, str]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build Xtream-shaped categories/streams. Drops movie/series M3U rows."""
    cat_ids: dict[str, str] = {}
    categories: list[dict[str, Any]] = []
    streams: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    skipped_vod = 0
    for index, entry in enumerate(entries, start=1):
        url = (entry.get("playback_url") or "").strip()
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        if _VOD_PATH.search(parsed.path):
            skipped_vod += 1
            continue
        group = (entry.get("group-title") or "").strip() or "Live"
        new_group = group not in cat_ids
        cid = _category_id(group, cat_ids)
        if new_group:
            categories.append({"category_id": cid, "category_name": group, "parent_id": 0})
        chno = entry.get("tvg-chno") or ""
        try:
            num = int(chno)
        except (TypeError, ValueError):
            num = index
        streams.append(
            {
                "num": num,
                "name": (entry.get("name") or "").strip() or f"Channel {index}",
                "stream_type": "live",
                "stream_id": _stream_id(url, used_ids),
                "stream_icon": (entry.get("tvg-logo") or "").strip(),
                "epg_channel_id": (entry.get("tvg-id") or "").strip(),
                "category_id": cid,
                "playback_url": url,
            }
        )
    if skipped_vod:
        logger.info("Watch live M3U: skipped %s movie/series rows", skipped_vod)
    return categories, streams


def live_from_m3u_text(text: str) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    if not (text or "").lstrip().startswith("#EXTM3U"):
        raise RuntimeError("Live playlist was not an M3U file")
    epg_url, entries = parse_m3u(text)
    categories, streams = entries_to_live(entries)
    if not streams:
        raise RuntimeError("Live M3U contained no channels")
    return epg_url, categories, streams


def download_bytes(
    url: str,
    *,
    max_bytes: int,
    timeout: httpx.Timeout,
    on_bytes: Callable[[int, int], None] | None = None,
) -> bytes:
    with playlist_client(timeout) as client:
        with client.stream("GET", url) as response:
            if response.status_code >= 400:
                raise RuntimeError(f"Playlist HTTP {response.status_code}")
            total = int(response.headers.get("content-length") or 0)
            chunks: list[bytes] = []
            written = 0
            for chunk in response.iter_bytes(64 * 1024):
                written += len(chunk)
                if written > max_bytes:
                    raise RuntimeError("Playlist download exceeded size limit")
                chunks.append(chunk)
                if on_bytes:
                    on_bytes(written, total)
    data = b"".join(chunks)
    head = data.lstrip()[:15].lower()
    if head.startswith(b"<!doctype") or head.startswith(b"<html"):
        raise RuntimeError("Playlist download returned a web page, not a file")
    return data


def download_file(
    url: str,
    dest: Path,
    *,
    max_bytes: int,
    timeout: httpx.Timeout,
    on_bytes: Callable[[int, int], None] | None = None,
) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with playlist_client(timeout) as client:
        with client.stream("GET", url) as response:
            if response.status_code >= 400:
                raise RuntimeError(f"EPG HTTP {response.status_code}")
            total = int(response.headers.get("content-length") or 0)
            written = 0
            with dest.open("wb") as handle:
                for chunk in response.iter_bytes(64 * 1024):
                    written += len(chunk)
                    if written > max_bytes:
                        raise RuntimeError("EPG download exceeded size limit")
                    handle.write(chunk)
                    if on_bytes:
                        on_bytes(written, total)
    if dest.stat().st_size < 16:
        raise RuntimeError("EPG download was empty")
    with dest.open("rb") as handle:
        head = handle.read(15).lstrip().lower()
    if head.startswith(b"<!doctype") or head.startswith(b"<html"):
        raise RuntimeError("EPG download returned a web page, not XMLTV")
    return dest
