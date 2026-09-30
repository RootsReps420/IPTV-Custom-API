"""Xtream HTTP MPEG-TS probe — what IPTV apps actually pull.

Multicast UDP cannot be aimed at these portal hostnames. Players request
  GET {dns}/live/{user}/{pass}/{stream_id}.ts
and receive MPEG-TS over HTTP (content-type video/mp2t, packets start with 0x47).

We authenticate with player_api.php first, then (Magnum only) read a few hundred
bytes of a live stream and stop. Failures here count toward failover except
Strong 8K VPS-blind results (404/CF/401 from this datacentre).
"""

from __future__ import annotations

import asyncio
import time
from typing import Iterable

import httpx

from iptv_monitor.vpn import magnum_client_kwargs

# MPEG-TS packets are 188 bytes; the sync byte is always 0x47.
TS_SYNC = 0x47
TS_PACKET = 188
_STREAM_UA = "VLC/3.0.20 LibVLC/3.0.20"
# Cap parallel stream checks so a large standby pool does not stampede origins.
_SEM = asyncio.Semaphore(8)
_STREAM_ID_CACHE: dict[str, tuple[float, list[int]]] = {}
_STREAM_ID_TTL = 600.0
# Last MPEG-TS stream id that worked, keyed by portal base URL.
_LAST_GOOD_ID: dict[str, int] = {}
# MAG / Xtream panel codes. 452/453 = blocked; 456 = geo; 464 = DNS locked.
_PANEL_DENY_STATUSES = {452, 453, 456, 464}
_PLACEHOLDER_MARKERS = ("black.ts", "/video/black")
_STREAM_BLOCK_MARKERS = ("cloudflare-terms-of-service-abuse",)
_API_PATHS = ("/player_api.php", "/panel_api.php")
_ALT_UA = "Lavf/60.16.100"
# Strong 8K: the VPS often cannot see Xtream (CF 404/challenge/401) while TVs still play.
# These are not downs. Magnum still treats them as down because /watch is this box.
STRONG_INCONCLUSIVE = frozenset(
    {
        "stream_no_api",
        "stream_unverified",
        "stream_blocked",
        "stream_timeout",
        "stream_error",
    }
)

Credentials = list[tuple[str, str]]


def _redact(text: str, secrets: Iterable[str]) -> str:
    value = text
    for secret in secrets:
        if secret:
            value = value.replace(secret, "***")
    return value


def looks_like_mpegts(data: bytes) -> bool:
    """True if we see 0x47 repeating every 188 bytes (not HTML that happens to contain 'G')."""
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


def _is_placeholder_url(url: str) -> bool:
    low = url.lower()
    return any(marker in low for marker in _PLACEHOLDER_MARKERS)


def _is_blocked_stream_url(url: str) -> bool:
    """Cloudflare TOS-abuse interstitial: a short fake MPEG-TS file, not a live pipe."""
    low = (url or "").lower()
    return any(marker in low for marker in _STREAM_BLOCK_MARKERS)


def _deny_status(hops: list[int]) -> int | None:
    for status in hops:
        if status in _PANEL_DENY_STATUSES:
            return status
    return None


def _hops(response: httpx.Response) -> list[int]:
    return [item.status_code for item in response.history] + [response.status_code]


def _is_challenge(text: str) -> bool:
    low = text.lower()
    return "<html" in low and ("just a moment" in low or "challenge-platform" in low)


async def _read_prefix(client: httpx.AsyncClient, url: str, nbytes: int) -> tuple[int, str, bytes, str, list[int]]:
    """Read a short prefix then hang up so we do not download a full live channel."""
    async with client.stream("GET", url, headers={"Connection": "close"}) as response:
        ctype = (response.headers.get("content-type") or "").split(";")[0]
        chunks = b""
        async for chunk in response.aiter_bytes():
            chunks += chunk
            if len(chunks) >= nbytes:
                break
        hops = [item.status_code for item in response.history] + [response.status_code]
        return response.status_code, ctype, chunks, str(response.url), hops


async def _stream_ids(
    client: httpx.AsyncClient,
    api: str,
    username: str,
    password: str,
    cache_key: str,
) -> list[int]:
    """First few live stream IDs from Xtream. Cached so we do not download the full list every cycle."""
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
        if len(ids) >= 12:
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
    *,
    host_key: str,
) -> tuple[bool | None, str]:
    """Try /live/.../{id}.ts (and without .ts).

    True = real MPEG-TS from a non-placeholder URL.
    False = no usable stream among these ids.
    None = panel returned 452/453/456/464 — treat the host as down immediately.
    """
    secrets = [username, password]
    last_detail = "no mpegts"
    for stream_id in stream_ids:
        for suffix in (f"{stream_id}.ts", str(stream_id)):
            url = f"{base}/live/{username}/{password}/{suffix}"
            try:
                status, stream_type, data, final_url, hops = await _read_prefix(
                    client, url, TS_PACKET * 3
                )
            except httpx.TimeoutException:
                last_detail = f"timeout {suffix}"
                continue
            except httpx.RequestError as exc:
                last_detail = _redact(str(exc), secrets)[:180]
                continue
            denied = _deny_status(hops)
            if denied is not None:
                return None, f"live HTTP {denied}"
            if _is_blocked_stream_url(url) or _is_blocked_stream_url(final_url):
                return False, "cloudflare-stream-block"
            if _is_placeholder_url(url) or _is_placeholder_url(final_url):
                last_detail = "placeholder black.ts"
                continue
            if looks_like_mpegts(data) or (
                status == 200 and "mp2t" in stream_type and data[:1] == bytes([TS_SYNC])
            ):
                _LAST_GOOD_ID[host_key] = stream_id
                return True, ""
            if status in {401, 403}:
                last_detail = f"live HTTP {status}"
                continue
            preview = data[:40].decode("utf-8", errors="replace").replace("\n", " ")
            last_detail = _redact(
                f"live HTTP {status} {stream_type} {preview}".strip(),
                secrets,
            )[:180]
    return False, last_detail


async def _get_php_is_m3u(
    client: httpx.AsyncClient,
    base: str,
    username: str,
    password: str,
) -> tuple[bool | None, str | None, str | None]:
    """True if get.php looks like an Xtream M3U. None = not visible. False = panel lock."""
    url = f"{base}/get.php"
    params = {
        "username": username,
        "password": password,
        "type": "m3u_plus",
        "output": "ts",
    }
    try:
        async with client.stream("GET", url, params=params, headers={"Connection": "close"}) as response:
            hops = _hops(response)
            denied = _deny_status(hops)
            if denied is not None:
                return False, "stream_452", f"get.php HTTP {denied}"
            chunks = b""
            async for chunk in response.aiter_bytes():
                chunks += chunk
                if len(chunks) >= 512:
                    break
            status = response.status_code
    except httpx.TimeoutException:
        return None, "stream_timeout", "get.php"
    except httpx.RequestError as exc:
        return None, "stream_error", _redact(str(exc), [username, password])[:180]

    preview = chunks.decode("utf-8", errors="replace")
    if "#EXTM3U" in preview or "#EXTINF" in preview:
        return True, None, None
    if status in _PANEL_DENY_STATUSES:
        return False, "stream_452", f"get.php HTTP {status}"
    return None, "stream_unverified", f"get.php HTTP {status}"


async def _player_api_payload(
    client: httpx.AsyncClient,
    url: str,
    username: str,
    password: str,
    *,
    headers: dict[str, str] | None = None,
) -> tuple[int, object | None, str, list[int], str | None]:
    """GET an Xtream API path. Returns status, json-or-None, text prefix, hops, network-fail."""
    try:
        response = await client.get(
            url,
            params={"username": username, "password": password},
            headers=headers,
        )
    except httpx.TimeoutException:
        return 0, None, "", [], "stream_timeout"
    except httpx.RequestError as exc:
        return 0, None, _redact(str(exc), [username, password])[:180], [], "stream_error"

    text = response.text[:800]
    try:
        payload: object | None = response.json()
    except Exception:
        payload = None
    return response.status_code, payload, text, _hops(response), None


async def _try_credentials(
    client: httpx.AsyncClient,
    base: str,
    username: str,
    password: str,
    *,
    require_mpegts: bool,
) -> tuple[bool | None, str | None, str | None]:
    """One account against one portal.

    True = portal is usable (MPEG-TS, or a confirmed Xtream login for Strong 8K).
    False = host is actually unusable (panel 452, Magnum stream fail).
    None = try the next account, or VPS-blind for Strong 8K.
    """
    last_blind: tuple[str, str] = ("stream_unverified", "no xtream from vps")
    api_url = f"{base}/player_api.php"
    found_api = False
    for path in _API_PATHS:
        url = f"{base}{path}"
        status, payload, text, hops, net_fail = await _player_api_payload(
            client, url, username, password
        )
        if net_fail:
            last_blind = (net_fail, text or path)
            if require_mpegts:
                return False, net_fail, text or path
            continue
        denied = _deny_status(hops) or (status if status in _PANEL_DENY_STATUSES else None)
        if denied is not None:
            return False, "stream_452", f"{path} HTTP {denied}"
        if _is_challenge(text):
            alt_status, alt_payload, alt_text, alt_hops, alt_net = await _player_api_payload(
                client,
                url,
                username,
                password,
                headers={"User-Agent": _ALT_UA, "Accept": "application/json"},
            )
            if not alt_net:
                status, payload, text, hops = alt_status, alt_payload, alt_text, alt_hops
                denied = _deny_status(hops) or (
                    status if status in _PANEL_DENY_STATUSES else None
                )
                if denied is not None:
                    return False, "stream_452", f"{path} HTTP {denied}"
            if _is_challenge(text):
                last_blind = ("stream_blocked", "cloudflare-challenge")
                if require_mpegts:
                    return False, "stream_blocked", "cloudflare-challenge"
                continue
        if status in {401, 403}:
            last_blind = ("stream_blocked", f"{path} HTTP {status}")
            if require_mpegts:
                return False, "stream_blocked", f"{path} HTTP {status}"
            continue
        if status == 404 or payload is None:
            last_blind = (
                "stream_no_api" if status == 404 else "stream_blocked",
                f"{path} HTTP {status}",
            )
            if require_mpegts and status != 404:
                return False, "stream_blocked", f"{path} HTTP {status}"
            continue
        if not _auth_ok(payload):
            return None, "stream_auth", "xtream auth failed"
        api_url = url
        found_api = True
        break

    if not found_api:
        m3u_ok, m3u_reason, m3u_detail = await _get_php_is_m3u(
            client, base, username, password
        )
        if m3u_ok is True:
            if not require_mpegts:
                return True, None, None
        elif m3u_ok is False:
            return False, m3u_reason, m3u_detail
        else:
            last_blind = (m3u_reason or last_blind[0], m3u_detail or last_blind[1])
        if require_mpegts:
            return False, last_blind[0], last_blind[1]
        return None, last_blind[0], last_blind[1]

    if not require_mpegts:
        return True, None, None

    cheap: list[int] = []
    last_id = _LAST_GOOD_ID.get(base)
    if last_id is not None:
        cheap.append(last_id)
    cheap.append(1)
    ok, detail = await _probe_stream_ids(
        client, base, username, password, _unique(cheap), host_key=base
    )
    if ok is True:
        return True, None, None
    if ok is None:
        return False, "stream_452", detail
    if detail == "cloudflare-stream-block":
        return False, "stream_blocked", detail

    listed = await _stream_ids(client, api_url, username, password, f"{base}|{username}")
    remaining = [item for item in listed if item not in set(cheap)]
    if remaining:
        ok, detail = await _probe_stream_ids(
            client, base, username, password, remaining, host_key=base
        )
        if ok is True:
            return True, None, None
        if ok is None:
            return False, "stream_452", detail
        if detail == "cloudflare-stream-block":
            return False, "stream_blocked", detail
    return False, "stream_no_mpegts", detail or "no mpegts"


async def check_xtream_mpegts(
    base_url: str,
    credentials: Credentials,
    timeout: float,
    insecure: bool,
    *,
    via_vpn: bool = False,
    require_mpegts: bool = True,
) -> tuple[bool | None, str | None, str | None]:
    """Probe a portal with each playlist account.

    Magnum (require_mpegts): DNS/TCP/MPEG-TS from the VPS — /watch is this box.
    Strong 8K: confirmed Xtream login or M3U is up. 404/CF/401 from this
    datacentre is not a down — home players often still work. Panel 452 and
    JSON auth-fail still count as down.

    Returns (ok, fail_reason, detail). ok is None when we had no credentials,
    or when Strong 8K is VPS-blind (caller must not treat that as down).
    """
    if not credentials:
        return None, None, None
    base = base_url.rstrip("/")
    timeout_cfg = httpx.Timeout(timeout, connect=min(5.0, timeout))
    last_skip: tuple[str | None, str | None] = (None, None)
    last_fail: tuple[str | None, str | None] | None = None
    extra = magnum_client_kwargs() if via_vpn else {}
    async with _SEM:
        async with httpx.AsyncClient(
            verify=not insecure,
            follow_redirects=True,
            timeout=timeout_cfg,
            headers={"User-Agent": _STREAM_UA, "Accept": "*/*"},
            **extra,
        ) as client:
            for username, password in credentials:
                ok, reason, detail = await _try_credentials(
                    client, base, username, password, require_mpegts=require_mpegts
                )
                if ok is True:
                    return True, None, None
                if ok is False:
                    last_fail = (reason, detail)
                else:
                    last_skip = (reason, detail)
    if last_fail:
        return False, last_fail[0], last_fail[1]
    if last_skip[0]:
        if not require_mpegts and last_skip[0] in STRONG_INCONCLUSIVE:
            return None, last_skip[0], last_skip[1]
        return False, last_skip[0], last_skip[1]
    return None, None, None
