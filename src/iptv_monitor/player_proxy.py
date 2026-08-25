"""Same-origin media proxy so the browser never sees Xtream user/pass.

Live/movie/series URLs are built server-side. HLS playlists are rewritten so
every URI goes through signed /api/player/fetch. MPEG-TS is streamed in chunks
(never loaded fully into RAM). Gzip must stay off these paths in Caddy.

VOD is remuxed with ffmpeg to fragmented MP4 for Chrome/Android.
H.264/HEVC video is copied; older codecs (MPEG-4 ASP / Xvid, MPEG-2, …) are
transcoded to H.264. Audio is always AAC. Matroska/E-AC3 is otherwise unplayable.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
from collections.abc import AsyncIterator, Callable
from urllib.parse import quote, urljoin, urlparse

import httpx
from fastapi import HTTPException
from fastapi.responses import Response, StreamingResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from iptv_monitor.player_xtream import PlayerConfig
from iptv_monitor.stream import TS_SYNC, _STREAM_UA, _is_blocked_stream_url

logger = logging.getLogger("iptv_monitor.player_proxy")

FETCH_MAX_AGE = 8 * 3600
_URI_ATTR = re.compile(r'URI="([^"]+)"')
_HLS_HINTS = ("application/vnd.apple.mpegurl", "application/x-mpegurl", "audio/mpegurl")
_HTTP: httpx.AsyncClient | None = None
_BROWSER_COPY_VIDEO = frozenset({"h264", "hevc", "h265", "av1", "vp8", "vp9"})
_PEEK_BYTES = 1024 * 1024
_CODEC_MARKERS = (
    ("h264", (b"V_MPEG4/ISO/AVC", b"avc1", b"avcC")),
    ("hevc", (b"V_MPEGH/ISO/HEVC", b"V_MPEGI/ISO/HEVC", b"hvc1", b"hev1", b"hvcC")),
    ("av1", (b"V_AV1", b"av01")),
    ("vp9", (b"V_VP9",)),
    ("mpeg4", (b"V_MPEG4/ISO/ASP", b"V_MPEG4/MS/V3", b"mp4v")),
    ("mpeg2video", (b"V_MPEG2",)),
    ("msmpeg4", (b"V_MS/VFW/FOURCC",)),
)


def http_client() -> httpx.AsyncClient:
    """Keepalive pool so zapping a channel does not redo TLS to the panel every time."""
    global _HTTP
    if _HTTP is None or _HTTP.is_closed:
        _HTTP = httpx.AsyncClient(
            verify=False,
            follow_redirects=True,
            http2=False,
            timeout=httpx.Timeout(None, connect=8.0),
            headers={"User-Agent": _STREAM_UA, "Accept": "*/*"},
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=40, keepalive_expiry=90),
        )
    return _HTTP


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


def _local_fetch(token: str, sid: str, access: str = "") -> str:
    q = f"t={quote(token, safe='')}&sid={quote(sid, safe='')}"
    if access:
        q += f"&k={quote(access, safe='')}"
    return f"/api/player/fetch?{q}"


def rewrite_hls(
    text: str,
    serializer: URLSafeTimedSerializer,
    playlist_url: str,
    sid: str,
    access: str = "",
) -> str:
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
                return f'URI="{_local_fetch(sign_url(serializer, absolute), sid, access)}"'

            lines.append(_URI_ATTR.sub(_repl, line))
            continue
        absolute = urljoin(playlist_url, stripped)
        lines.append(_local_fetch(sign_url(serializer, absolute), sid, access))
    return "\n".join(lines) + "\n"


def _is_hls(content_type: str, body: bytes) -> bool:
    ctype = (content_type or "").split(";")[0].strip().lower()
    if any(hint in ctype for hint in _HLS_HINTS):
        return True
    head = body.lstrip()[:7]
    return head.startswith(b"#EXTM3U")


def ffmpeg_bin() -> str | None:
    return shutil.which("ffmpeg")


def video_codec_from_peek(data: bytes) -> str:
    """Read codec from MKV/MP4 headers so we do not open a second Xtream connection."""
    blob = data or b""
    for name, needles in _CODEC_MARKERS:
        if any(marker in blob for marker in needles):
            return name
    return ""


def _vod_ffmpeg_args(binary: str, *, copy_video: bool, codec: str) -> list[str]:
    args = [
        binary,
        "-hide_banner",
        "-loglevel",
        "error",
        "-probesize",
        "5000000",
        "-analyzeduration",
        "5000000",
        "-fflags",
        "+genpts",
        "-i",
        "pipe:0",
        "-map",
        "0:V:0",
        "-map",
        "0:a:0?",
    ]
    if copy_video:
        args.extend(["-c:v", "copy"])
        if codec in {"h264"}:
            args.extend(["-tag:v", "avc1"])
        elif codec in {"hevc", "h265"}:
            args.extend(["-tag:v", "hvc1"])
    else:
        args.extend(
            [
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-pix_fmt",
                "yuv420p",
                "-profile:v",
                "high",
                "-crf",
                "20",
                "-g",
                "48",
                "-keyint_min",
                "48",
                "-vf",
                "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            ]
        )
    args.extend(
        [
            "-c:a",
            "aac",
            "-ac",
            "2",
            "-b:a",
            "192k",
            "-max_muxing_queue_size",
            "1024",
            "-flush_packets",
            "1",
            "-movflags",
            "frag_keyframe+empty_moov+default_base_moof",
            "-f",
            "mp4",
            "pipe:1",
        ]
    )
    return args


def _stop_proc(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    try:
        proc.kill()
    except ProcessLookupError:
        return


async def remux_vod_to_browser_mp4(
    url: str, on_bytes: Callable[[int], None] | None = None
) -> StreamingResponse:
    """Fragmented MP4 for Chrome: copy H.264/HEVC, transcode older video, AAC audio."""
    binary = ffmpeg_bin()
    if not binary:
        raise RuntimeError("ffmpeg is not installed")
    client = http_client()
    try:
        request = client.build_request(
            "GET",
            url,
            headers={"User-Agent": _STREAM_UA, "Accept": "*/*"},
        )
        response = await client.send(request, stream=True)
    except httpx.RequestError as exc:
        logger.warning("VOD remux source failed: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Could not reach the stream.") from exc
    if response.status_code >= 400:
        await response.aclose()
        raise HTTPException(status_code=502, detail=f"Stream HTTP {response.status_code}")

    stream = response.aiter_bytes(64 * 1024)
    peek = bytearray()
    codec = ""
    try:
        async for chunk in stream:
            peek.extend(chunk)
            codec = video_codec_from_peek(bytes(peek))
            if codec or len(peek) >= _PEEK_BYTES:
                break
    except Exception:
        await response.aclose()
        raise HTTPException(status_code=502, detail="Could not read the stream.") from None
    if not peek:
        await response.aclose()
        raise HTTPException(status_code=502, detail="Empty stream.")

    copy_video = codec in _BROWSER_COPY_VIDEO
    logger.info("VOD remux %s (%s)", "copy" if copy_video else "libx264", codec or "unknown")
    ffmpeg_args = _vod_ffmpeg_args(binary, copy_video=copy_video, codec=codec)
    proc_kwargs: dict[str, object] = {
        "stdin": asyncio.subprocess.PIPE,
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.PIPE,
        "limit": 8 * 1024 * 1024,
    }
    try:
        proc = await asyncio.create_subprocess_exec(*ffmpeg_args, **proc_kwargs)
    except TypeError:
        proc_kwargs.pop("limit", None)
        proc = await asyncio.create_subprocess_exec(*ffmpeg_args, **proc_kwargs)

    async def feed_source() -> None:
        try:
            if proc.stdin is not None:
                proc.stdin.write(peek)
                await proc.stdin.drain()
            async for chunk in stream:
                if proc.stdin is None or proc.returncode is not None:
                    break
                try:
                    proc.stdin.write(chunk)
                    await proc.stdin.drain()
                except (BrokenPipeError, ConnectionResetError):
                    break
            if proc.stdin and proc.returncode is None:
                proc.stdin.close()
                await proc.stdin.wait_closed()
        except Exception:
            logger.warning("VOD remux input stopped")
            _stop_proc(proc)
        finally:
            await response.aclose()

    async def drain_stderr() -> None:
        if proc.stderr is None:
            return
        try:
            while True:
                line = await proc.stderr.readline()
                if not line:
                    return
                text = line.decode("utf-8", "replace").strip()
                if text:
                    logger.warning("VOD remux: %s", text[:180])
        except Exception:
            return

    async def body() -> AsyncIterator[bytes]:
        feed_task = asyncio.create_task(feed_source())
        err_task = asyncio.create_task(drain_stderr())
        try:
            assert proc.stdout is not None
            while True:
                chunk = await proc.stdout.read(64 * 1024)
                if not chunk:
                    break
                if on_bytes:
                    on_bytes(len(chunk))
                yield chunk
        finally:
            _stop_proc(proc)
            for task in (feed_task, err_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(feed_task, err_task, proc.wait(), return_exceptions=True)

    return StreamingResponse(
        body(),
        media_type="video/mp4",
        headers={
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
    )


async def proxy_url(
    url: str,
    *,
    serializer: URLSafeTimedSerializer | None = None,
    sid: str = "",
    range_header: str | None = None,
    assume_mpegts: bool = False,
    remux_aac: bool = False,
    access_token: str = "",
    on_bytes: Callable[[int], None] | None = None,
) -> Response:
    """Stream upstream bytes. Live TS skips body-peek so the player gets headers immediately."""
    if remux_aac and ffmpeg_bin() and not assume_mpegts:
        return await remux_vod_to_browser_mp4(url, on_bytes=on_bytes)

    headers = {"User-Agent": _STREAM_UA, "Accept": "*/*"}
    if range_header:
        headers["Range"] = range_header
    client = http_client()
    try:
        request = client.build_request("GET", url, headers=headers)
        response = await client.send(request, stream=True)
    except httpx.RequestError as exc:
        logger.warning("Media proxy failed: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Could not reach the stream.") from exc

    ctype = response.headers.get("content-type") or "application/octet-stream"
    if response.status_code >= 400:
        await response.aclose()
        raise HTTPException(
            status_code=502,
            detail=f"Stream HTTP {response.status_code}",
        )
    if assume_mpegts and _is_blocked_stream_url(str(response.url)):
        await response.aclose()
        raise HTTPException(
            status_code=502,
            detail="This portal is not serving a live stream. Waiting for DNS failover.",
        )

    passthrough_headers = {
        "Cache-Control": "no-store",
        "X-Accel-Buffering": "no",
    }

    if assume_mpegts:
        async def _live_iter() -> AsyncIterator[bytes]:
            try:
                async for chunk in response.aiter_bytes(64 * 1024):
                    if on_bytes:
                        on_bytes(len(chunk))
                    yield chunk
            finally:
                await response.aclose()

        return StreamingResponse(
            _live_iter(),
            status_code=response.status_code,
            media_type="video/mp2t",
            headers=passthrough_headers,
        )

    peek = b""
    stream = response.aiter_bytes(16 * 1024)
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
        text = b"".join(chunks).decode("utf-8", errors="replace")
        body = rewrite_hls(text, serializer, str(response.url), sid, access_token)
        return Response(
            content=body,
            media_type="application/vnd.apple.mpegurl",
            headers={"Cache-Control": "no-store"},
        )

    if serializer and sid and peek[:1] == bytes((TS_SYNC,)):
        logger.warning("HLS requested but upstream is MPEG-TS; iOS native player cannot use this")

    async def _iter() -> AsyncIterator[bytes]:
        try:
            if peek:
                if on_bytes:
                    on_bytes(len(peek))
                yield peek
            async for chunk in stream:
                if on_bytes:
                    on_bytes(len(chunk))
                yield chunk
        finally:
            await response.aclose()

    media_type = ctype.split(";")[0]
    if peek[:1] == bytes((TS_SYNC,)) and "mpegurl" not in media_type.lower():
        media_type = "video/mp2t"
    if not media_type or media_type == "application/octet-stream":
        media_type = "video/mp4"
    if response.headers.get("content-range"):
        passthrough_headers["Content-Range"] = response.headers["content-range"]
        passthrough_headers["Accept-Ranges"] = "bytes"
        clen = response.headers.get("content-length")
        if clen:
            passthrough_headers["Content-Length"] = clen
    else:
        clen = response.headers.get("content-length")
        if clen:
            passthrough_headers["Content-Length"] = clen
        passthrough_headers["Accept-Ranges"] = "bytes"
    return StreamingResponse(
        _iter(),
        status_code=response.status_code,
        media_type=media_type,
        headers=passthrough_headers,
    )
