"""Seekable VOD HLS for Safari, iPhone/iPad and AirPlay.

The playlist is a real `#EXT-X-PLAYLIST-TYPE:VOD` with the full runtime cut
into fixed 6s segments, so iOS shows the scrubber and AirPlay receivers accept
it. One ffmpeg per playback writes fMP4 segments to disk:

- a segment request inside the running window is served (or waited for);
- a seek outside it restarts ffmpeg at that segment (`-ss`, `-start_number`);
- ffmpeg is SIGSTOPped once it is AHEAD segments past the player, so a film
  is not pulled from Magnum faster than it is watched.

`frag_discont` + `-copyts` keep segment times absolute after a restart, and
the init segment is byte-identical between runs, so the player's cached
EXT-X-MAP stays valid across seeks.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import secrets
import shutil
import signal
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, urlencode

from fastapi import HTTPException
from fastapi.responses import Response

from iptv_monitor import player_proxy
from iptv_monitor.stream import _STREAM_UA

logger = logging.getLogger("iptv_monitor.player_hls")

SEG_SEC = 6
AHEAD = 10
BEHIND = 3
JUMP = 4
IDLE_SEC = 120
WAIT_SEC = 45
_HLS_COPY = frozenset({"h264"})

_sessions: dict[str, "HlsSession"] = {}
_media_by_url: dict[str, tuple[str, float]] = {}
_root_ready = False


def hls_root() -> Path:
    base = Path("/var/tmp") if Path("/var/tmp").is_dir() else Path(tempfile.gettempdir())
    return base / "iptv-hls"


def _ensure_root() -> Path:
    global _root_ready
    root = hls_root()
    if not _root_ready:
        # Leftovers from before a restart belong to dead ffmpegs.
        shutil.rmtree(root, ignore_errors=True)
        _root_ready = True
    root.mkdir(parents=True, exist_ok=True)
    return root


@dataclass
class HlsSession:
    key: str
    url: str
    folder: Path
    copy_video: bool
    codec: str
    proc: asyncio.subprocess.Process | None = None
    start_seg: int = 0
    last_req: int = 0
    touched: float = field(default_factory=time.monotonic)
    paused: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    monitor: asyncio.Task | None = None

    def alive(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    def finished(self) -> bool:
        return self.proc is not None and self.proc.returncode == 0

    def seg_path(self, n: int) -> Path:
        return self.folder / f"seg_{n}.m4s"

    def init_path(self) -> Path:
        return self.folder / "init.mp4"

    def produced(self) -> int:
        best = -1
        try:
            for entry in os.scandir(self.folder):
                name = entry.name
                if name.startswith("seg_") and name.endswith(".m4s"):
                    try:
                        best = max(best, int(name[4:-4]))
                    except ValueError:
                        continue
        except OSError:
            return -1
        return best


async def probe_vod_media(url: str) -> tuple[str, float]:
    """Video codec + container duration in one ffprobe (one Magnum connection)."""
    hit = _media_by_url.get(url)
    if hit:
        return hit
    probe = shutil.which("ffprobe")
    if not probe:
        return "", 0.0
    args = [probe, "-v", "error", "-user_agent", _STREAM_UA]
    if url.startswith("https://"):
        args.extend(["-tls_verify", "0"])
    args.extend(
        [
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name:format=duration",
            "-of",
            "json",
            url,
        ]
    )
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError:
        return "", 0.0
    try:
        async with asyncio.timeout(15):
            out, _err = await proc.communicate()
    except TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return "", 0.0
    try:
        data = json.loads((out or b"{}").decode("utf-8", "replace"))
    except ValueError:
        data = {}
    streams = data.get("streams") or [{}]
    codec = str((streams[0] or {}).get("codec_name") or "").strip().lower()
    if codec == "h265":
        codec = "hevc"
    try:
        duration = float((data.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    if not math.isfinite(duration) or duration < 0:
        duration = 0.0
    if codec:
        if len(_media_by_url) >= 80:
            _media_by_url.pop(next(iter(_media_by_url)))
        _media_by_url[url] = (codec, duration)
    return codec, duration


def _session_key(sid: str, kind: str, stream_id: str, allow_hevc: bool) -> str:
    return f"{sid}|{kind}|{stream_id}|{int(allow_hevc)}"


def _copy_for_hls(codec: str, allow_hevc: bool) -> bool:
    # Apple HLS: H.264 always; HEVC only in fMP4 and only if the device said it decodes it.
    if codec in _HLS_COPY:
        return True
    return codec in {"hevc", "h265"} and allow_hevc


def _ffmpeg_args(binary: str, sess: HlsSession, start_seg: int) -> list[str]:
    url = sess.url
    args = [
        binary,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-user_agent",
        _STREAM_UA,
        "-seekable",
        "1",
        "-multiple_requests",
        "1",
        "-reconnect",
        "1",
        "-reconnect_streamed",
        "1",
        "-reconnect_delay_max",
        "2",
    ]
    if url.startswith("https://"):
        args.extend(["-tls_verify", "0"])
    start_sec = start_seg * SEG_SEC
    if start_sec >= 1:
        args.extend(["-noaccurate_seek", "-ss", str(start_sec)])
    args.extend(
        [
            "-probesize",
            "5000000",
            "-analyzeduration",
            "5000000",
            "-fflags",
            "+genpts",
            "-i",
            url,
            "-map",
            "0:V:0",
            "-map",
            "0:a:0?",
        ]
    )
    if sess.copy_video:
        args.extend(["-c:v", "copy", "-tag:v", "hvc1" if sess.codec in {"hevc", "h265"} else "avc1"])
    else:
        args.extend(
            [
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-threads",
                "2",
                "-pix_fmt",
                "yuv420p",
                "-profile:v",
                "main",
                "-crf",
                "23",
                "-bf",
                "0",
                "-force_key_frames",
                f"expr:gte(t,n_forced*{SEG_SEC})",
                "-vf",
                r"scale=-2:min(720\,ih)",
            ]
        )
    folder = sess.folder
    args.extend(
        [
            "-c:a",
            "aac",
            "-ac",
            "2",
            "-ar",
            "48000",
            "-b:a",
            "160k",
            "-copyts",
            "-start_at_zero",
            "-avoid_negative_ts",
            "disabled",
            "-max_muxing_queue_size",
            "4096",
            "-max_delay",
            "5000000",
            "-hls_segment_options",
            "movflags=+frag_discont",
            "-f",
            "hls",
            "-hls_time",
            str(SEG_SEC),
            "-hls_segment_type",
            "fmp4",
            "-hls_fmp4_init_filename",
            "init.mp4",
            "-start_number",
            str(start_seg),
            "-hls_segment_filename",
            str(folder / "seg_%d.m4s"),
            "-hls_flags",
            "temp_file",
            "-hls_playlist_type",
            "vod",
            "-hls_list_size",
            "0",
            str(folder / "ffmpeg.m3u8"),
        ]
    )
    return args


def _signal(proc: asyncio.subprocess.Process | None, sig: int) -> None:
    if proc is None or proc.returncode is not None:
        return
    try:
        os.kill(proc.pid, sig)
    except (OSError, AttributeError):
        pass


def _clear_segments(folder: Path) -> None:
    try:
        for entry in os.scandir(folder):
            if entry.name.startswith("seg_"):
                try:
                    os.unlink(entry.path)
                except OSError:
                    pass
    except OSError:
        pass


async def _drain(proc: asyncio.subprocess.Process) -> None:
    if proc.stderr is None:
        return
    try:
        while True:
            line = await proc.stderr.readline()
            if not line:
                return
            text = line.decode("utf-8", "replace").strip()
            if text:
                logger.warning("VOD HLS: %s", text[:180])
    except Exception:
        return


async def _start(sess: HlsSession, start_seg: int) -> None:
    binary = player_proxy.ffmpeg_bin()
    if not binary:
        raise HTTPException(status_code=503, detail="ffmpeg is not installed on the server.")
    async with player_proxy._vod_run:
        old = sess.proc
        if old is not None and old.returncode is None:
            # Must be gone before the folder is cleared, or it keeps renaming segments in.
            _signal(old, signal.SIGCONT)
            try:
                old.kill()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(old.wait(), 3)
            except TimeoutError:
                pass
            player_proxy._vod_procs.discard(old)
        # One Magnum VOD pull at a time, same rule as the desktop remux.
        await player_proxy._stop_all_vod()
        sess.folder.mkdir(parents=True, exist_ok=True)
        _clear_segments(sess.folder)
        args = _ffmpeg_args(binary, sess, start_seg)
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        player_proxy._vod_procs.add(proc)
    asyncio.create_task(_drain(proc))
    sess.proc = proc
    sess.start_seg = start_seg
    sess.last_req = start_seg
    sess.paused = False
    logger.info(
        "VOD HLS %s (%s) from segment %d",
        "copy" if sess.copy_video else "libx264",
        sess.codec or "unknown",
        start_seg,
    )
    if sess.monitor is None or sess.monitor.done():
        sess.monitor = asyncio.create_task(_watch(sess))


async def _watch(sess: HlsSession) -> None:
    """Throttle ffmpeg to the player, trim old segments, reap idle sessions."""
    try:
        while True:
            await asyncio.sleep(0.5)
            if time.monotonic() - sess.touched > IDLE_SEC:
                break
            if not sess.alive():
                if sess.proc is not None and sess.proc.returncode is not None:
                    player_proxy._vod_procs.discard(sess.proc)
                sess.paused = False
            else:
                ahead = sess.produced() - sess.last_req
                if not sess.paused and ahead >= AHEAD:
                    _signal(sess.proc, signal.SIGSTOP)
                    sess.paused = True
                elif sess.paused and ahead <= AHEAD - 3:
                    _signal(sess.proc, signal.SIGCONT)
                    sess.paused = False
            floor = sess.last_req - BEHIND
            try:
                for entry in os.scandir(sess.folder):
                    name = entry.name
                    if name.startswith("seg_") and name.endswith(".m4s"):
                        try:
                            idx = int(name[4:-4])
                        except ValueError:
                            continue
                        if idx < floor:
                            os.unlink(entry.path)
            except OSError:
                pass
    finally:
        await _close(sess)


async def _close(sess: HlsSession) -> None:
    proc = sess.proc
    if proc is not None and proc.returncode is None:
        _signal(proc, signal.SIGCONT)
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(proc.wait(), 3)
        except TimeoutError:
            pass
    if proc is not None:
        player_proxy._vod_procs.discard(proc)
    if _sessions.get(sess.key) is sess:
        _sessions.pop(sess.key, None)
    shutil.rmtree(sess.folder, ignore_errors=True)


def _session(sid: str, kind: str, stream_id: str, url: str, codec: str, allow_hevc: bool) -> HlsSession:
    key = _session_key(sid, kind, stream_id, allow_hevc)
    sess = _sessions.get(key)
    if sess is None or sess.url != url:
        root = _ensure_root()
        sess = HlsSession(
            key=key,
            url=url,
            folder=root / secrets.token_hex(8),
            copy_video=_copy_for_hls(codec, allow_hevc),
            codec=codec,
        )
        _sessions[key] = sess
    sess.touched = time.monotonic()
    return sess


async def _wait_for(sess: HlsSession, path: Path, n: int | None) -> Path | None:
    deadline = time.monotonic() + WAIT_SEC
    while time.monotonic() < deadline:
        if path.exists():
            return path
        if not sess.alive():
            return None
        if n is not None and sess.paused and sess.produced() - n < AHEAD - 3:
            _signal(sess.proc, signal.SIGCONT)
            sess.paused = False
        sess.touched = time.monotonic()
        await asyncio.sleep(0.15)
    return None


async def hls_file(
    *,
    sid: str,
    kind: str,
    stream_id: str,
    url: str,
    allow_hevc: bool,
    name: str,
    start_hint: int = 0,
) -> Path:
    codec, _duration = await probe_vod_media(url)
    sess = _session(sid, kind, stream_id, url, codec, allow_hevc)
    if name == "init.mp4":
        async with sess.lock:
            if not sess.alive() and not sess.init_path().exists():
                await _start(sess, max(0, start_hint))
        path = await _wait_for(sess, sess.init_path(), None)
        if path is None and sess.init_path().exists():
            path = sess.init_path()
        if path is None:
            raise HTTPException(status_code=502, detail="Could not start this title.")
        # init.mp4 is not covered by temp_file; give ffmpeg a beat to finish the tiny write.
        if time.time() - path.stat().st_mtime < 0.3:
            await asyncio.sleep(0.3)
        return path

    if not name.endswith(".m4s"):
        raise HTTPException(status_code=404, detail="Unknown segment.")
    try:
        n = int(name[:-4])
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Unknown segment.") from exc
    if n < 0:
        raise HTTPException(status_code=404, detail="Unknown segment.")
    for attempt in range(2):
        async with sess.lock:
            path = sess.seg_path(n)
            if path.exists():
                sess.last_req = n
                return path
            produced = sess.produced()
            window_end = max(produced, sess.start_seg) + JUMP
            # Only segments this run has not written yet are "coming"; anything at or
            # below `produced` that is missing was trimmed and needs a restart.
            coming = sess.alive() and n >= sess.start_seg and n > produced and n <= window_end
            if not coming:
                if sess.finished() and n > produced >= 0 and n >= sess.start_seg:
                    raise HTTPException(status_code=404, detail="End of title.")
                await _start(sess, n)
            sess.last_req = n
        found = await _wait_for(sess, sess.seg_path(n), n)
        if found is not None:
            return found
        if sess.finished():
            raise HTTPException(status_code=404, detail="End of title.")
        if attempt == 0 and not sess.alive():
            # Killed (another VOD started, or Magnum dropped). One restart here.
            continue
        break
    raise HTTPException(status_code=504, detail="The title is taking too long to load.")


def vod_playlist(
    *,
    kind: str,
    stream_id: str,
    sid: str,
    access_token: str,
    src_ext: str,
    video_caps: str,
    duration_sec: float,
    start_sec: float,
) -> Response:
    total = max(1, math.ceil(duration_sec / SEG_SEC))
    params: dict[str, str] = {"sid": sid}
    if access_token:
        params["k"] = access_token
    if src_ext:
        params["src"] = src_ext
    caps = "".join(ch for ch in (video_caps or "").lower() if ch.isalnum() or ch == ",")[:32]
    if caps:
        params["vc"] = caps
    query = urlencode(params)
    base = f"/api/player/hls/{quote(kind, safe='')}/{quote(stream_id, safe='')}"
    hint = max(0, min(total - 1, int(max(0.0, start_sec) // SEG_SEC)))
    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:7",
        f"#EXT-X-TARGETDURATION:{SEG_SEC}",
        "#EXT-X-MEDIA-SEQUENCE:0",
        "#EXT-X-PLAYLIST-TYPE:VOD",
        "#EXT-X-INDEPENDENT-SEGMENTS",
        f'#EXT-X-MAP:URI="{base}/init.mp4?{query}&s={hint}"',
    ]
    if hint:
        # Resume: AVPlayer asks for the resume segment first instead of 0 then seeking.
        lines.insert(6, f"#EXT-X-START:TIME-OFFSET={hint * SEG_SEC},PRECISE=NO")
    for n in range(total):
        length = SEG_SEC if n < total - 1 else max(0.5, duration_sec - SEG_SEC * (total - 1))
        lines.append(f"#EXTINF:{length:.3f},")
        lines.append(f"{base}/{n}.m4s?{query}")
    lines.append("#EXT-X-ENDLIST")
    return Response(
        content="\n".join(lines) + "\n",
        media_type="application/vnd.apple.mpegurl",
        headers={"Cache-Control": "no-store"},
    )


async def vod_duration(url: str, fallback: float) -> float:
    if url not in _media_by_url:
        async with player_proxy._vod_run:
            # A new title: free the Magnum VOD line before probing it.
            await player_proxy._stop_all_vod()
            _codec, duration = await probe_vod_media(url)
    else:
        _codec, duration = _media_by_url[url]
    if duration <= 1 and fallback > 1:
        duration = fallback
    return duration if duration > 1 else 0.0
