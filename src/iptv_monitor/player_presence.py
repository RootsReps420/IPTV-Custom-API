"""In-memory /watch presence for the owner dashboard.

One row per browser tab (session cookie + play_id). Idle signed-in users show
up from /api/watch/me; now-playing is filled from media / heartbeat.
Nothing here is on the playback hot path beyond a dict update under a lock.
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


def _key(session_id: str, play_id: str = "") -> str:
    sid = (session_id or "").strip()
    pid = (play_id or "").strip()
    if pid:
        return f"{sid}:{pid}"
    return sid


class PresenceTracker:
    def __init__(self, *, ttl_seconds: float = 180) -> None:
        self.ttl_seconds = max(60.0, float(ttl_seconds))
        self._rows: dict[str, Presence] = {}
        self._lock = asyncio.Lock()

    def _prune_unlocked(self, now: float) -> None:
        expired = [
            key
            for key, row in self._rows.items()
            if now - row.last_seen > self.ttl_seconds
        ]
        for key in expired:
            self._rows.pop(key, None)

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
    ) -> None:
        name = (username or "").strip()
        sid = (session_id or "").strip() or name
        if not name or not sid:
            return
        pid = (play_id or "").strip()
        now_mono = time.monotonic()
        now_wall = time.time()
        async with self._lock:
            self._prune_unlocked(now_mono)
            key = _key(sid, pid)
            row = self._rows.get(key)
            if row is None and pid:
                bare = self._rows.pop(sid, None)
                if bare is not None:
                    bare.play_id = pid
                    self._rows[key] = bare
                    row = bare
            if row is None:
                row = Presence(
                    username=name,
                    session_id=sid,
                    play_id=pid,
                    ip=(ip or "")[:64],
                    issued_at=float(issued_at or now_wall),
                    first_seen=now_wall,
                    last_seen=now_mono,
                )
                self._rows[key] = row
            row.username = name
            row.session_id = sid
            if pid:
                row.play_id = pid
            if ip:
                row.ip = ip[:64]
            if issued_at and (not row.issued_at or issued_at < row.issued_at):
                row.issued_at = float(issued_at)
            row.last_seen = now_mono
            if playing is True:
                row.playing = True
                if kind:
                    row.kind = kind[:16]
                if stream_id:
                    row.stream_id = stream_id[:80]
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

    async def drop(self, *, session_id: str = "", play_id: str = "") -> None:
        sid = (session_id or "").strip()
        pid = (play_id or "").strip()
        async with self._lock:
            if pid:
                suffix = f":{pid}"
                for key in [item for item in self._rows if item.endswith(suffix) or self._rows[item].play_id == pid]:
                    self._rows.pop(key, None)
            if sid:
                for key in [item for item in self._rows if item == sid or item.startswith(f"{sid}:")]:
                    self._rows.pop(key, None)

    async def snapshot(self) -> dict[str, Any]:
        now_mono = time.monotonic()
        now_wall = time.time()
        async with self._lock:
            self._prune_unlocked(now_mono)
            rows = list(self._rows.values())
        sessions = []
        playing = 0
        for row in sorted(rows, key=lambda item: (-item.playing, item.username.lower(), item.first_seen)):
            if row.playing:
                playing += 1
            started = row.issued_at or row.first_seen
            sessions.append(
                {
                    "username": row.username,
                    "ip": row.ip,
                    "logged_in_seconds": max(0, int(now_wall - started)),
                    "idle_seconds": max(0, int(now_mono - row.last_seen)),
                    "playing": row.playing,
                    "kind": row.kind,
                    "stream_id": row.stream_id,
                    "title": row.title,
                    "detail": row.detail,
                }
            )
        return {
            "online": len(sessions),
            "playing": playing,
            "sessions": sessions,
        }
