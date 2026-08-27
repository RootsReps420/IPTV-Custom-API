"""In-memory /watch presence for the owner dashboard.

One row per browser tab (play_id). Idle signed-in users without a tab id share
one row per username+IP so cookie remints do not clone the same person.
Byte counts are incremented on the media proxy without taking the async lock.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Presence:
    username: str
    session_id: str
    play_id: str = ""
    ip: str = ""
    issued_at: float = 0.0
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.monotonic)
    playing: bool = False
    kind: str = ""
    stream_id: str = ""
    title: str = ""
    detail: str = ""
    watch_started: float = 0.0
    bytes_total: int = 0
    bytes_mark: int = 0
    kbps_at: float = 0.0
    kbps: int = 0
    buffer_s: float = 0.0
    width: int = 0
    height: int = 0
    audio: str = ""
    dropped: int = 0
    decoded: int = 0
    stall_at: list[float] = field(default_factory=list)


def _clamp(value: float, lo: float, hi: float) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return lo
    return max(lo, min(hi, n))


class PresenceTracker:
    def __init__(self, *, ttl_seconds: float = 180) -> None:
        self.ttl_seconds = max(60.0, float(ttl_seconds))
        self._rows: dict[str, Presence] = {}
        self._lock = asyncio.Lock()
        self._byte_add: dict[str, int] = {}

    def add_bytes(self, play_id: str, n: int) -> None:
        """Called from the media proxy on each chunk. No await / no lock."""
        pid = (play_id or "").strip()
        if not pid or n <= 0:
            return
        self._byte_add[pid] = self._byte_add.get(pid, 0) + int(n)

    def _drain_bytes_unlocked(self, now: float) -> None:
        pending = self._byte_add
        if not pending:
            return
        self._byte_add = {}
        by_pid = {row.play_id: row for row in self._rows.values() if row.play_id}
        for pid, n in pending.items():
            row = by_pid.get(pid)
            if row is None:
                self._byte_add[pid] = self._byte_add.get(pid, 0) + n
                continue
            row.bytes_total += n
            if not row.kbps_at:
                row.kbps_at = now
                row.bytes_mark = row.bytes_total
                continue
            dt = now - row.kbps_at
            if dt >= 2.0:
                delta = max(0, row.bytes_total - row.bytes_mark)
                row.kbps = int(delta * 8 / dt / 1000)
                row.bytes_mark = row.bytes_total
                row.kbps_at = now

    def _prune_unlocked(self, now: float) -> None:
        expired = [
            key
            for key, slot in self._rows.items()
            if now - slot.last_seen > self.ttl_seconds
        ]
        for key in expired:
            self._rows.pop(key, None)

    def _canonical(self, sid: str, pid: str, username: str, ip: str) -> str:
        if pid:
            return f"tab:{pid}"
        return f"idle:{sid or username}:{ip}"

    def _find_key_unlocked(
        self, *, sid: str, pid: str, username: str, ip: str
    ) -> str | None:
        if pid:
            want = f"tab:{pid}"
            if want in self._rows:
                return want
            for key, row in self._rows.items():
                if row.play_id == pid:
                    return key
        if sid:
            idle = f"idle:{sid}:{ip}"
            if idle in self._rows:
                return idle
            for key, row in self._rows.items():
                if row.session_id == sid and not row.play_id:
                    return key
        for key, row in self._rows.items():
            if (
                not row.play_id
                and row.username == username
                and (not ip or row.ip == ip)
            ):
                return key
        return None

    def _drop_idle_unlocked(self, username: str, ip: str, keep: str | None) -> None:
        for key in [
            item
            for item, row in self._rows.items()
            if item != keep
            and not row.play_id
            and row.username == username
            and (not ip or row.ip == ip)
        ]:
            self._rows.pop(key, None)

    async def reuse_sid(self, username: str, ip: str) -> str:
        """Keep one session id when the cookie is missing sid (avoids clone rows)."""
        name = (username or "").strip()
        addr = (ip or "").strip()
        async with self._lock:
            self._prune_unlocked(time.monotonic())
            for row in self._rows.values():
                if row.username == name and (not addr or row.ip == addr) and row.session_id:
                    return row.session_id
        return ""

    async def touch(
        self,
        *,
        username: str,
        session_id: str,
        ip: str = "",
        issued_at: float = 0.0,
        play_id: str = "",
        playing: bool | None = None,
        kind: str = "",
        stream_id: str = "",
        title: str = "",
        detail: str = "",
        buffer_s: float = 0.0,
        stalls: int = 0,
        dropped: int = 0,
        decoded: int = 0,
        width: int = 0,
        height: int = 0,
        audio: str = "",
    ) -> None:
        name = (username or "").strip()
        sid = (session_id or "").strip()
        pid = (play_id or "").strip()
        addr = (ip or "").strip()[:64]
        if not name:
            return
        if not sid:
            sid = pid or name
        now_mono = time.monotonic()
        now_wall = time.time()
        async with self._lock:
            self._prune_unlocked(now_mono)
            self._drain_bytes_unlocked(now_mono)
            old_key = self._find_key_unlocked(sid=sid, pid=pid, username=name, ip=addr)
            new_key = self._canonical(sid, pid, name, addr)
            row = self._rows.pop(old_key, None) if old_key else None
            if row is None:
                row = Presence(
                    username=name,
                    session_id=sid,
                    play_id=pid,
                    ip=addr,
                    issued_at=float(issued_at or now_wall),
                    first_seen=now_wall,
                    last_seen=now_mono,
                )
            self._rows[new_key] = row
            if pid:
                self._drop_idle_unlocked(name, addr, new_key)
            row.username = name
            row.session_id = sid
            if pid:
                row.play_id = pid
            if addr:
                row.ip = addr
            if issued_at and (not row.issued_at or issued_at < row.issued_at):
                row.issued_at = float(issued_at)
            row.last_seen = now_mono
            if playing is True:
                row.playing = True
                new_stream = (stream_id or "").strip()
                if new_stream and new_stream != row.stream_id:
                    row.watch_started = now_mono
                    row.stall_at = []
                if not row.watch_started:
                    row.watch_started = now_mono
                if kind:
                    row.kind = kind[:16]
                if new_stream:
                    row.stream_id = new_stream[:80]
                if title:
                    row.title = title[:200]
                if detail:
                    row.detail = detail[:200]
            elif playing is False:
                row.playing = False
                row.kind = ""
                row.stream_id = ""
                row.title = ""
                row.detail = ""
                row.watch_started = 0.0
                row.kbps = 0
                row.buffer_s = 0.0
                row.width = 0
                row.height = 0
                row.audio = ""
            if playing is not False:
                if buffer_s:
                    row.buffer_s = _clamp(buffer_s, 0, 120)
                if stalls:
                    for _ in range(min(20, int(stalls))):
                        row.stall_at.append(now_mono)
                    row.stall_at = [stamp for stamp in row.stall_at if now_mono - stamp <= 60]
                if dropped:
                    row.dropped = max(row.dropped, int(dropped))
                if decoded:
                    row.decoded = max(row.decoded, int(decoded))
                if width:
                    row.width = int(width)
                if height:
                    row.height = int(height)
                if audio:
                    cleaned = "".join(
                        ch for ch in str(audio).strip()[:40] if ch.isalnum() or ch in " .+/-"
                    )
                    if cleaned:
                        row.audio = cleaned

    async def drop(self, *, session_id: str = "", play_id: str = "") -> None:
        sid = (session_id or "").strip()
        pid = (play_id or "").strip()
        async with self._lock:
            if pid:
                for key in [
                    item
                    for item, row in self._rows.items()
                    if row.play_id == pid or item == f"tab:{pid}"
                ]:
                    self._rows.pop(key, None)
            if sid:
                for key in [
                    item
                    for item, row in self._rows.items()
                    if row.session_id == sid or item.startswith(f"idle:{sid}:")
                ]:
                    self._rows.pop(key, None)

    async def drop_user(self, username: str) -> int:
        name = (username or "").strip()
        if not name:
            return 0
        async with self._lock:
            keys = [key for key, row in self._rows.items() if row.username == name]
            for key in keys:
                self._rows.pop(key, None)
            return len(keys)

    def _quality(self, row: Presence, now: float) -> str:
        if not row.playing:
            return ""
        stalls = sum(1 for stamp in row.stall_at if now - stamp <= 60)
        drop_pct = (100.0 * row.dropped / row.decoded) if row.decoded >= 80 else 0.0
        if stalls >= 3 or drop_pct >= 8 or (row.kbps and row.kbps < 400 and row.kind == "live"):
            return "poor"
        if stalls >= 1 or drop_pct >= 3 or row.buffer_s < 0.8:
            return "ok"
        return "good"

    async def snapshot(self) -> dict[str, Any]:
        now_mono = time.monotonic()
        now_wall = time.time()
        async with self._lock:
            self._prune_unlocked(now_mono)
            self._drain_bytes_unlocked(now_mono)
            rows = list(self._rows.values())
        best: dict[tuple[str, str], Presence] = {}
        for row in rows:
            key = (row.username, row.play_id or f"idle:{row.ip}")
            prev = best.get(key)
            if prev is None:
                best[key] = row
                continue
            if row.playing and not prev.playing:
                best[key] = row
            elif row.last_seen >= prev.last_seen:
                best[key] = row
        sessions = []
        playing = 0
        for row in sorted(
            best.values(),
            key=lambda item: (-item.playing, item.username.lower(), item.first_seen),
        ):
            if row.playing:
                playing += 1
            started = row.issued_at or row.first_seen
            watching = (
                max(0, int(now_mono - row.watch_started)) if row.playing and row.watch_started else 0
            )
            stalls = sum(1 for stamp in row.stall_at if now_mono - stamp <= 60)
            drop_pct = round(100.0 * row.dropped / row.decoded, 1) if row.decoded >= 80 else 0.0
            sessions.append(
                {
                    "username": row.username,
                    "ip": row.ip,
                    "logged_in_seconds": max(0, int(now_wall - started)),
                    "idle_seconds": max(0, int(now_mono - row.last_seen)),
                    "watching_seconds": watching,
                    "playing": row.playing,
                    "kind": row.kind,
                    "stream_id": row.stream_id,
                    "title": row.title,
                    "detail": row.detail,
                    "kbps": row.kbps if row.playing else 0,
                    "buffer_s": round(row.buffer_s, 1) if row.playing else 0,
                    "width": row.width if row.playing else 0,
                    "height": row.height if row.playing else 0,
                    "audio": row.audio if row.playing else "",
                    "stalls_60s": stalls if row.playing else 0,
                    "drop_pct": drop_pct if row.playing else 0,
                    "quality": self._quality(row, now_mono),
                }
            )
        return {
            "online": len(sessions),
            "playing": playing,
            "sessions": sessions,
        }
