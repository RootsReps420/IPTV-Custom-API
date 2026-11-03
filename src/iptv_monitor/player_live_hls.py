"""Live HLS for Safari, iPhone/iPad and AirPlay.

Magnum ignores `.m3u8` on live paths and answers with raw MPEG-TS. AVPlayer
cannot play an endless TS response as live: it buffers ~30s, re-opens the URL,
lands on a stream whose clock starts again, jumps back and stalls.

So the server builds the HLS itself. One ffmpeg per playback reads the `.ts`
stream on a single Magnum connection (video copied, audio to AAC) and writes
~2s MPEG-TS segments to disk. The playlist is ours, not ffmpeg's: a rolling
window whose media sequence keeps counting across ffmpeg restarts, with an
EXT-X-DISCONTINUITY where each new run starts, so a dropped upstream (or a
resume after the session idled out) carries on instead of jumping back.
"""

from __future__ import annotations

import asyncio
import logging
import re
import secrets
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, urlencode

from fastapi import HTTPException
from fastapi.responses import Response

from iptv_monitor import player_proxy
from iptv_monitor.stream import _STREAM_UA

logger = logging.getLogger("iptv_monitor.player_live_hls")

SEG_SEC = 2
WINDOW = 8
KEEP = 6
READY_SEGS = 3
READY_SEC = 6.0
IDLE_SEC = 30
WAIT_SEC = 20
FAILED_RUNS = 4

_SEG_NAME = re.compile(r"^r\d{1,4}_\d{1,7}\.ts$")
_sessions: dict[str, "LiveSession"] = {}
# sid|stream_id -> (next media sequence, discontinuities so far) after a session closes.
_resume: dict[str, tuple[int, int]] = {}
_lock = asyncio.Lock()
_root_ready = False


def live_hls_root() -> Path:
    base = Path("/var/tmp") if Path("/var/tmp").is_dir() else Path(tempfile.gettempdir())
    return base / "iptv-live-hls"


def _ensure_root() -> Path:
    global _root_ready
    root = live_hls_root()
    if not _root_ready:
        # Leftovers from before a restart belong to dead ffmpegs.
        shutil.rmtree(root, ignore_errors=True)
        _root_ready = True
    root.mkdir(parents=True, exist_ok=True)
    return root


@dataclass
class Segment:
    seq: int
    name: str
    duration: float
    disc: bool


@dataclass
class LiveSession:
    sid: str
    stream_id: str
    url: str
    folder: Path
    next_seq: int = 0
    discs: int = 0
    proc: asyncio.subprocess.Process | None = None
    run: int = -1
    run_segments: int = 0
    failed_runs: int = 0
    pending_disc: bool = False
    segments: list[Segment] = field(default_factory=list)
    seen: set[str] = field(default_factory=set)
    dropped_discs: int = 0
    target: int = SEG_SEC
    ready: bool = False
    error: str = ""
    closed: bool = False
    touched: float = field(default_factory=time.monotonic)
    monitor: asyncio.Task | None = None

    @property
    def key(self) -> str:
        return f"{self.sid}|{self.stream_id}"

    def alive(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    def playlist_path(self) -> Path:
        return self.folder / f"r{self.run}.m3u8"


def _ffmpeg_args(binary: str, sess: LiveSession) -> list[str]:
    args = [
        binary,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-user_agent",
        _STREAM_UA,
        "-reconnect",
        "1",
        "-reconnect_streamed",
        "1",
        "-reconnect_delay_max",
        "2",
    ]
    if sess.url.startswith("https://"):
        args.extend(["-tls_verify", "0"])
    args.extend(
        [
            "-fflags",
            "+genpts+discardcorrupt",
            "-probesize",
            "2000000",
            "-analyzeduration",
            "2000000",
            "-i",
            sess.url,
            "-map",
            "0:V:0",
            "-map",
            "0:a:0?",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-ac",
            "2",
            "-ar",
            "48000",
            "-b:a",
            "160k",
            "-af",
            "aresample=async=1",
            "-max_muxing_queue_size",
            "4096",
            "-f",
            "hls",
            "-hls_time",
            str(SEG_SEC),
            "-hls_list_size",
            "12",
            "-hls_segment_type",
            "mpegts",
            "-hls_flags",
            "temp_file",
            "-hls_segment_filename",
            str(sess.folder / f"r{sess.run}_%d.ts"),
            str(sess.playlist_path()),
        ]
    )
    return args


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
                logger.warning("Live HLS: %s", text[:180])
    except Exception:
        return


async def _start_run(sess: LiveSession) -> None:
    binary = player_proxy.ffmpeg_bin()
    if not binary:
        sess.error = "ffmpeg is not installed on the server."
        return
    sess.run += 1
    sess.run_segments = 0
    sess.seen.clear()
    # Every run after the first (and a resumed session) restarts the media clock.
    sess.pending_disc = bool(sess.segments) or sess.next_seq > 0
    sess.folder.mkdir(parents=True, exist_ok=True)
    proc = await asyncio.create_subprocess_exec(
        *_ffmpeg_args(binary, sess),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    # Registered as live so a VOD start (_stop_all_vod) does not sweep it.
    player_proxy._live_procs.add(proc)
    asyncio.create_task(_drain(proc))
    sess.proc = proc
    logger.info("Live HLS started for stream %s (run %d)", sess.stream_id, sess.run)


def _read_run_playlist(sess: LiveSession) -> list[tuple[str, float]]:
    try:
        text = sess.playlist_path().read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    found: list[tuple[str, float]] = []
    duration: float | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#EXTINF:"):
            try:
                duration = float(line[8:].split(",", 1)[0])
            except ValueError:
                duration = None
        elif line and not line.startswith("#"):
            if duration is not None and duration > 0:
                found.append((Path(line).name, duration))
            duration = None
    return found


def _collect(sess: LiveSession) -> None:
    """Append segments the current run has finished to our window."""
    for name, duration in _read_run_playlist(sess):
        if name in sess.seen or not _SEG_NAME.match(name):
            continue
        if not (sess.folder / name).exists():
            continue
        sess.seen.add(name)
        disc = sess.pending_disc
        sess.pending_disc = False
        if disc:
            sess.discs += 1
        sess.segments.append(Segment(seq=sess.next_seq, name=name, duration=duration, disc=disc))
        sess.next_seq += 1
        sess.run_segments += 1
        sess.failed_runs = 0
    while len(sess.segments) > WINDOW + KEEP:
        old = sess.segments.pop(0)
        if old.disc:
            sess.dropped_discs += 1
        try:
            (sess.folder / old.name).unlink()
        except OSError:
            pass
    window = sess.segments[-WINDOW:]
    if not window:
        return
    if not sess.ready:
        total = sum(seg.duration for seg in window)
        sess.ready = len(window) >= READY_SEGS or total >= READY_SEC
    # Apple: no EXTINF (rounded) may exceed it, and it should never shrink.
    sess.target = max(sess.target, max(int(seg.duration + 0.5) for seg in window))


async def _monitor(sess: LiveSession) -> None:
    """Pick up new segments, restart ffmpeg if Magnum drops, reap idle sessions."""
    try:
        while not sess.closed:
            await asyncio.sleep(0.4)
            if time.monotonic() - sess.touched > IDLE_SEC:
                logger.info("Live HLS idle for stream %s; closing", sess.stream_id)
                break
            _collect(sess)
            if sess.alive() or sess.error:
                continue
            proc = sess.proc
            if proc is not None:
                player_proxy._live_procs.discard(proc)
                _collect(sess)
                if sess.run_segments == 0:
                    sess.failed_runs += 1
                logger.info(
                    "Live HLS ffmpeg for stream %s exited (%s) after %d segments",
                    sess.stream_id,
                    proc.returncode,
                    sess.run_segments,
                )
            if sess.failed_runs >= FAILED_RUNS:
                sess.error = "Could not start this channel."
                continue
            if sess.failed_runs:
                await asyncio.sleep(min(4.0, 1.0 * sess.failed_runs))
                if sess.closed:
                    break
            async with _lock:
                if not sess.closed:
                    await _start_run(sess)
    finally:
        if not sess.closed:
            async with _lock:
                await _close(sess)


async def _close(sess: LiveSession) -> None:
    """Caller holds _lock. Kills ffmpeg (frees the Magnum line) and removes the files."""
    if sess.closed:
        return
    sess.closed = True
    proc = sess.proc
    if proc is not None and proc.returncode is None:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(proc.wait(), 3)
        except TimeoutError:
            pass
    if proc is not None:
        player_proxy._live_procs.discard(proc)
    if _sessions.get(sess.sid) is sess:
        _sessions.pop(sess.sid, None)
    if sess.next_seq:
        if len(_resume) >= 200:
            _resume.pop(next(iter(_resume)))
        _resume[sess.key] = (sess.next_seq, sess.discs)
    shutil.rmtree(sess.folder, ignore_errors=True)
    monitor = sess.monitor
    if monitor is not None and monitor is not asyncio.current_task():
        monitor.cancel()


async def stop_live_hls(sid: str) -> None:
    """Free the tab's live line: slot released, another channel, or a film started."""
    async with _lock:
        sess = _sessions.get(sid)
        if sess is not None:
            await _close(sess)


async def _session(sid: str, stream_id: str, url: str) -> LiveSession:
    async with _lock:
        sess = _sessions.get(sid)
        if sess is not None and not sess.closed and sess.stream_id == stream_id and sess.url == url:
            sess.touched = time.monotonic()
            return sess
        if sess is not None:
            # One Magnum line per tab: the old channel must be gone before the new one opens.
            await _close(sess)
        next_seq, discs = _resume.pop(f"{sid}|{stream_id}", (0, 0))
        sess = LiveSession(
            sid=sid,
            stream_id=stream_id,
            url=url,
            folder=_ensure_root() / secrets.token_hex(8),
            next_seq=next_seq,
            discs=discs,
            dropped_discs=discs,
        )
        _sessions[sid] = sess
        await _start_run(sess)
        sess.monitor = asyncio.create_task(_monitor(sess))
        return sess


def _render(sess: LiveSession, query: str) -> str:
    window = sess.segments[-WINDOW:]
    first = window[0]
    hidden = sess.segments[: len(sess.segments) - len(window)]
    dropped = sess.dropped_discs + sum(1 for seg in hidden if seg.disc)
    # A discontinuity on the first listed segment is folded into the sequence number
    # rather than tagged, so every client agrees on that segment's discontinuity number.
    disc_seq = dropped + (1 if first.disc else 0)
    base = f"/api/player/live-hls/{quote(sess.stream_id, safe='')}"
    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        f"#EXT-X-TARGETDURATION:{sess.target}",
        f"#EXT-X-MEDIA-SEQUENCE:{first.seq}",
        f"#EXT-X-DISCONTINUITY-SEQUENCE:{disc_seq}",
    ]
    for index, seg in enumerate(window):
        if seg.disc and index > 0:
            lines.append("#EXT-X-DISCONTINUITY")
        lines.append(f"#EXTINF:{seg.duration:.3f},")
        lines.append(f"{base}/{seg.name}?{query}")
    return "\n".join(lines) + "\n"


async def live_playlist(*, sid: str, stream_id: str, url: str, access_token: str) -> Response:
    sess = await _session(sid, stream_id, url)
    deadline = time.monotonic() + WAIT_SEC
    while True:
        sess.touched = time.monotonic()
        _collect(sess)
        if sess.ready:
            break
        if sess.error or sess.closed:
            raise HTTPException(status_code=502, detail=sess.error or "Live stream stopped.")
        if time.monotonic() > deadline:
            break
        await asyncio.sleep(0.2)
    if not sess.segments:
        raise HTTPException(status_code=504, detail="The channel is taking too long to start.")
    params = {"sid": sid}
    if access_token:
        params["k"] = access_token
    return Response(
        content=_render(sess, urlencode(params)),
        media_type="application/vnd.apple.mpegurl",
        headers={"Cache-Control": "no-store"},
    )


def live_segment(*, sid: str, stream_id: str, name: str) -> Path:
    sess = _sessions.get(sid)
    if sess is None or sess.closed or sess.stream_id != stream_id or not _SEG_NAME.match(name):
        raise HTTPException(status_code=404, detail="Unknown segment.")
    path = sess.folder / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Unknown segment.")
    sess.touched = time.monotonic()
    return path
