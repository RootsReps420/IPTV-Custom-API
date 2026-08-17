from __future__ import annotations

import asyncio
import logging
import time
from typing import Iterable

import httpx

logger = logging.getLogger("iptv_monitor.stream")

TS_SYNC = 0x47
TS_PACKET = 188
_STREAM_UA = "VLC/3.0.20 LibVLC/3.0.20"
_SEM = asyncio.Semaphore(8)
_STREAM_ID_CACHE: dict[str, tuple[float, list[int]]] = {}
_STREAM_ID_TTL = 600.0
_LAST_GOOD_ID: int | None = None

Credentials = list[tuple[str, str]]


def _redact(text: str, secrets: Iterable[str]) -> str:
    value = text
    for secret in secrets:
        if secret:
            value = value.replace(secret, "***")
    return value


def looks_like_mpegts(data: bytes) -> bool:
    if len(data) < TS_PACKET:
        return bool(data) and data[0] == TS_SYNC
    span = min(TS_PACKET, len(data) - TS_PACKET)
    for offset in range(span + 1):
        if data[offset] == TS_SYNC and data[offset + TS_PACKET] == TS_SYNC:
            return True
    return False


def _auth_ok(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    auth = (payload.get("user_info") or {}).get("auth")
    return auth in {1, "1", True, "true", "True"}


async def _read_prefix(client: httpx.AsyncClient, url: str, nbytes: int) -> tuple[int, str, bytes]:
    async with client.stream("GET", url) as response:
        ctype = (response.headers.get("content-type") or "").split(";")[0]
        chunks = b""
        async for chunk in response.aiter_bytes():
            chunks += chunk
            if len(chunks) >= nbytes:
                break
        return response.status_code, ctype, chunks


async def _stream_ids(
    client: httpx.AsyncClient,
    api: str,
    username: str,
    password: str,
    cache_key: str,
) -> list[int]:
    now = time.monotonic()
    cached = _STREAM_ID_CACHE.get(cache_key)
    if cached and now < cached[0]:
        return list(cached[1])
    response = await client.get(
        api,
        params={"username": username, "password": password, "action": "get_live_streams"},
    )
    try:
        payload = response.json()
    except Exception:
        return []
    if not isinstance(payload, list):
        return []
    ids: list[int] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        stream_id = item.get("stream_id")
        if stream_id is None:
            continue
        try:
            ids.append(int(stream_id))
        except (TypeError, ValueError):
            continue
        if len(ids) >= 5:
            break
    if ids:
        _STREAM_ID_CACHE[cache_key] = (now + _STREAM_ID_TTL, ids)
    return ids


def _unique(values: list[int]) -> list[int]:
    seen: set[int] = set()
    out: list[int] = []
    for item in values:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


async def _probe_stream_ids(
    client: httpx.AsyncClient,
    base: str,
    username: str,
    password: str,
    stream_ids: list[int],
) -> tuple[bool | None, str | None, str | None]:
    global _LAST_GOOD_ID
    secrets = [username, password]
    last_detail = "no mpegts"
    for stream_id in stream_ids:
        for suffix in (f"{stream_id}.ts", str(stream_id)):
            url = f"{base}/live/{username}/{password}/{suffix}"
            try:
                status, stream_type, data = await _read_prefix(client, url, TS_PACKET * 3)
            except httpx.TimeoutException:
                last_detail = f"timeout {suffix}"
                continue
            except httpx.RequestError as exc:
                last_detail = _redact(str(exc), secrets)[:180]
                continue
            if looks_like_mpegts(data) or (
                status == 200 and "mp2t" in stream_type and data[:1] == bytes([TS_SYNC])
            ):
                _LAST_GOOD_ID = stream_id
                return True, None, None
            if status in {401, 403}:
                last_detail = f"live HTTP {status}"
                continue
            preview = data[:40].decode("utf-8", errors="replace").replace("\n", " ")
            last_detail = _redact(
                f"live HTTP {status} {stream_type} {preview}".strip(),
                secrets,
            )[:180]
    return None, None, last_detail


async def _try_credentials(
    client: httpx.AsyncClient,
    base: str,
    username: str,
    password: str,
) -> tuple[bool | None, str | None, str | None]:
    """Return (ok, reason, detail). None ok means this account is not on this panel."""
    api = f"{base}/player_api.php"
    try:
        response = await client.get(api, params={"username": username, "password": password})
    except httpx.TimeoutException:
        return False, "stream_timeout", "player_api"
    except httpx.RequestError as exc:
        return False, "stream_error", _redact(str(exc), [username, password])[:180]

    if response.status_code in {401, 403}:
        return False, "stream_blocked", f"player_api HTTP {response.status_code}"
    if response.status_code == 404:
        return None, "stream_no_api", "player_api HTTP 404"
    ctype = (response.headers.get("content-type") or "").split(";")[0]
    text = response.text[:500].lower()
    if "<html" in text and ("just a moment" in text or "challenge-platform" in text):
        return False, "stream_blocked", "cloudflare-challenge"
    try:
        payload = response.json()
    except Exception:
        return False, "stream_blocked", ctype or f"HTTP {response.status_code}"
    if not _auth_ok(payload):
        return None, "stream_auth", "xtream auth failed"

    cache_key = f"{base}|{username}"
    cheap: list[int] = []
    if _LAST_GOOD_ID is not None:
        cheap.append(_LAST_GOOD_ID)
    cheap.append(1)
    ok, reason, detail = await _probe_stream_ids(
        client, base, username, password, _unique(cheap)
    )
    if ok is True:
        return True, None, None
    if ok is False:
        return False, reason, detail
    listed = await _stream_ids(client, api, username, password, cache_key)
    remaining = [item for item in listed if item not in set(cheap)]
    if remaining:
        ok, reason, detail = await _probe_stream_ids(
            client, base, username, password, remaining
        )
        if ok is True:
            return True, None, None
        if ok is False:
            return False, reason, detail
    return False, "stream_no_mpegts", detail or "no mpegts"


async def check_xtream_mpegts(
    base_url: str,
    credentials: Credentials,
    timeout: float,
    insecure: bool,
) -> tuple[bool | None, str | None, str | None]:
    """Probe Xtream HTTP MPEG-TS. None = skipped / this panel does not accept our accounts."""
    if not credentials:
        return None, None, None
    base = base_url.rstrip("/")
    timeout_cfg = httpx.Timeout(timeout, connect=min(5.0, timeout))
    last_skip: tuple[str | None, str | None] = (None, None)
    last_fail: tuple[str | None, str | None] | None = None
    async with _SEM:
        async with httpx.AsyncClient(
            verify=not insecure,
            follow_redirects=True,
            timeout=timeout_cfg,
            headers={"User-Agent": _STREAM_UA, "Accept": "*/*"},
        ) as client:
            for username, password in credentials:
                ok, reason, detail = await _try_credentials(client, base, username, password)
                if ok is True:
                    return True, None, None
                if ok is False:
                    last_fail = (reason, detail)
                else:
                    last_skip = (reason, detail)
    if last_fail:
        return False, last_fail[0], last_fail[1]
    if last_skip[0]:
        return False, last_skip[0], last_skip[1]
    return None, None, None
