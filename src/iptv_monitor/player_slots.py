"""In-memory concurrent playback slots for the shared Xtream account.

One slot per browser tab (play_id in sessionStorage), not per logged-in idle user.
Heartbeats refresh last_seen; stale slots expire so a crashed tab frees a seat.
The panel max_connections is still the hard limit — this is the friendly 409.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass


@dataclass
class Slot:
    username: str
    play_id: str
    last_seen: float


class SlotTracker:
    def __init__(self, *, max_concurrent: int = 5, ttl_seconds: float = 60) -> None:
        self.max_concurrent = max(1, int(max_concurrent))
        self.ttl_seconds = max(15.0, float(ttl_seconds))
        self._slots: dict[str, Slot] = {}
        self._lock = asyncio.Lock()

    def _prune_unlocked(self, now: float) -> None:
        expired = [
            key
            for key, slot in self._slots.items()
            if now - slot.last_seen > self.ttl_seconds
        ]
        for key in expired:
            self._slots.pop(key, None)

    async def snapshot(self) -> dict[str, int]:
        async with self._lock:
            self._prune_unlocked(time.monotonic())
            return {"used": len(self._slots), "max": self.max_concurrent}

    async def heartbeat(self, username: str, play_id: str) -> tuple[bool, int, int]:
        """Acquire or refresh a slot. Returns (ok, used, max). Same play_id reuses its seat."""
        play_id = (play_id or "").strip()
        if not play_id:
            return False, len(self._slots), self.max_concurrent
        now = time.monotonic()
        async with self._lock:
            self._prune_unlocked(now)
            existing = self._slots.get(play_id)
            if existing:
                existing.username = username
                existing.last_seen = now
                return True, len(self._slots), self.max_concurrent
            if len(self._slots) >= self.max_concurrent:
                return False, len(self._slots), self.max_concurrent
            self._slots[play_id] = Slot(username=username, play_id=play_id, last_seen=now)
            return True, len(self._slots), self.max_concurrent

    async def release(self, play_id: str) -> dict[str, int]:
        async with self._lock:
            self._slots.pop((play_id or "").strip(), None)
            self._prune_unlocked(time.monotonic())
            return {"used": len(self._slots), "max": self.max_concurrent}

    async def has(self, play_id: str) -> bool:
        play_id = (play_id or "").strip()
        now = time.monotonic()
        async with self._lock:
            self._prune_unlocked(now)
            slot = self._slots.get(play_id)
            if not slot:
                return False
            slot.last_seen = now
            return True
