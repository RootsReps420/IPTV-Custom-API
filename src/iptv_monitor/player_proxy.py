"""Same-origin media proxy so the browser never sees Xtream user/pass.

Live/movie/series URLs are built server-side. HLS playlists are rewritten so
every URI goes through signed /api/player/fetch. MPEG-TS is streamed in chunks
(never loaded fully into RAM). Gzip must stay off these paths in Caddy.
"""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from urllib.parse import quote, urljoin, urlparse

import httpx
from fastapi import HTTPException
from fastapi.responses import Response, StreamingResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from iptv_monitor.player_xtream import PlayerConfig
from iptv_monitor.stream import _STREAM_UA

logger = logging.getLogger("iptv_monitor.player_proxy")

FETCH_MAX_AGE = 8 * 3600
_URI_ATTR = re.compile(r'URI="([^"]+)"')
_HLS_HINTS = ("application/vnd.apple.mpegurl", "application/x-mpegurl", "audio/mpegurl")


def panel_media_url(cfg: PlayerConfig, kind: str, stream_id: str, ext: str) -> str:
    """Xtream path layout: /live|movie|series/{user}/{pass}/{id}.{ext}."""
    user = quote(cfg.username.strip(), safe="")
    password = quote(cfg.password.strip(), safe="")
    suffix = ext.lstrip(".")
    if kind == "live":
        return f"{cfg.base}/live/{user}/{password}/{stream_id}.{suffix}"
    if kind == "movie":
        return f"{cfg.base}/movie/{user}/{password}/{stream_id}.{suffix}"
    if kind == "series":
        return f"{cfg.base}/series/{user}/{password}/{stream_id}.{suffix}"
    raise HTTPException(status_code=400, detail="Invalid media kind.")


def sign_url(serializer: URLSafeTimedSerializer, url: str) -> str:
    return serializer.dumps(url)


def load_signed_url(serializer: URLSafeTimedSerializer, token: str) -> str:
    try:
        url = serializer.loads(token, max_age=FETCH_MAX_AGE)
    except (BadSignature, SignatureExpired, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid media token.") from exc
    if not isinstance(url, str):
        raise HTTPException(status_code=400, detail="Invalid media token.")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Invalid media URL.")
    return url


def _local_fetch(token: str, sid: str) -> str:
    q = f"t={quote(token, safe='')}&sid={quote(sid, safe='')}"
    return f"/api/player/fetch?{q}"


def rewrite_hls(text: str, serializer: URLSafeTimedSerializer, playlist_url: str, sid: str) -> str:
    """Point every playlist URI at signed /api/player/fetch so credentials stay server-side."""
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append(line)
            continue
        if stripped.startswith("#"):

            def _repl(match: re.Match[str]) -> str:
                absolute = urljoin(playlist_url, match.group(1))
                return f'URI="{_local_fetch(sign_url(serializer, absolute), sid)}"'

            lines.append(_URI_ATTR.sub(_repl, line))
            continue
        absolute = urljoin(playlist_url, stripped)
        lines.append(_local_fetch(sign_url(serializer, absolute), sid))
    return "\n".join(lines) + "\n"


def _is_hls(content_type: str, body: bytes) -> bool:
    ctype = (content_type or "").split(";")[0].strip().lower()
    if any(hint in ctype for hint in _HLS_HINTS):
        return True
    head = body.lstrip()[:7]
    return head.startswith(b"#EXTM3U")


async def proxy_url(
    url: str,
    *,
    serializer: URLSafeTimedSerializer | None = None,
    sid: str = "",
    range_header: str | None = None,
) -> Response:
    """Stream upstream bytes. If the body is HLS, rewrite it; otherwise pass through."""
    headers = {"User-Agent": _STREAM_UA, "Accept": "*/*"}
    if range_header:
        headers["Range"] = range_header
    timeout = httpx.Timeout(None, connect=15.0)
    client = httpx.AsyncClient(
        verify=False,
        follow_redirects=True,
        timeout=timeout,
        headers=headers,
    )
    try:
        request = client.build_request("GET", url)
        response = await client.send(request, stream=True)
    except httpx.RequestError as exc:
        await client.aclose()
        logger.warning("Media proxy failed: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Could not reach the stream.") from exc

    ctype = response.headers.get("content-type") or "application/octet-stream"
    if response.status_code >= 400:
        await response.aclose()
        await client.aclose()
        raise HTTPException(
            status_code=502,
            detail=f"Stream HTTP {response.status_code}",
        )

    peek = b""
    stream = response.aiter_bytes(64 * 1024)
    try:
        peek = await anext(stream)
    except StopAsyncIteration:
        peek = b""

    if serializer and sid and _is_hls(ctype, peek):
        chunks = [peek]
        total = len(peek)
        async for part in stream:
            chunks.append(part)
            total += len(part)
            if total > 2_000_000:
                break
        await response.aclose()
        await client.aclose()
        text = b"".join(chunks).decode("utf-8", errors="replace")
        body = rewrite_hls(text, serializer, str(response.url), sid)
        return Response(
            content=body,
            media_type="application/vnd.apple.mpegurl",
            headers={"Cache-Control": "no-store"},
        )

    async def _iter() -> AsyncIterator[bytes]:
        try:
            if peek:
                yield peek
            async for chunk in stream:
                yield chunk
        finally:
            await response.aclose()
            await client.aclose()

    out_headers = {"Cache-Control": "no-store"}
    if response.headers.get("content-range"):
        out_headers["Content-Range"] = response.headers["content-range"]
        out_headers["Accept-Ranges"] = "bytes"
    return StreamingResponse(
        _iter(),
        status_code=response.status_code,
        media_type=ctype.split(";")[0],
        headers=out_headers,
    )
