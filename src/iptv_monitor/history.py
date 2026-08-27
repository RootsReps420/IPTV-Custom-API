"""90-day per-URL outage history for the History tab.

Stored in state/url_history.json (gitignored). Separate from
state/failure_history.json, which is only the 24h window used for the
Frequent failure badge and failover skip list — do not stretch that prune
window to 90 days or almost every host becomes “frequent”.

Public /api/history omits currently-live hosts that are not in the available pool
so Current DNS does not leak. Counts are separate outages (up→down), not duration.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger("iptv_monitor.history")


def _parse_ts(raw: str) -> datetime | None:
    try:
        stamp = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp


def _host(url: str) -> str:
    parsed = urlparse(url if "://" in url else f"http://{url}")
    return parsed.hostname or url


class UrlHistoryStore:
    def __init__(self, path: Path, days: int = 90) -> None:
        self.path = path
        self.days = max(7, int(days))
        self.events: dict[str, list[dict[str, Any]]] = {}
        self._load()

    def _cutoff(self) -> datetime:
        return datetime.now(timezone.utc) - timedelta(days=self.days)

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Could not read URL history from %s", self.path)
            return
        if not isinstance(raw, dict):
            return
        cutoff = self._cutoff()
        for url, items in raw.items():
            kept: list[dict[str, Any]] = []
            for item in items or []:
                if not isinstance(item, dict):
                    continue
                stamp = _parse_ts(str(item.get("ts") or ""))
                if stamp is None or stamp <= cutoff:
                    continue
                kept.append({"ts": stamp.isoformat(), "reason": item.get("reason")})
            if kept:
                self.events[str(url)] = kept

    def seed_from_stamps(self, stamps_by_url: dict[str, list[datetime]]) -> None:
        """First run: copy the 24h frequent-failure stamps so History is not empty."""
        if self.events:
            return
        cutoff = self._cutoff()
        for url, stamps in stamps_by_url.items():
            kept = [
                {"ts": stamp.isoformat(), "reason": None}
                for stamp in stamps
                if stamp > cutoff
            ]
            if kept:
                self.events[str(url)] = kept
        if self.events:
            self.save()

    def record(self, url: str, reason: str | None) -> None:
        now = datetime.now(timezone.utc)
        self.events.setdefault(url, []).append(
            {"ts": now.isoformat(), "reason": reason}
        )
        self._prune_url(url)

    def _prune_url(self, url: str) -> None:
        cutoff = self._cutoff()
        kept: list[dict[str, Any]] = []
        for item in self.events.get(url) or []:
            stamp = _parse_ts(str(item.get("ts") or ""))
            if stamp is None or stamp <= cutoff:
                continue
            kept.append(item)
        if kept:
            self.events[url] = kept
        else:
            self.events.pop(url, None)

    def prune_all(self) -> None:
        for url in list(self.events):
            self._prune_url(url)

    def save(self) -> None:
        """Atomic replace so a crash mid-write cannot leave truncated JSON."""
        self.prune_all()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.events, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.path)

    def snapshot(
        self,
        *,
        available: set[str],
        live: set[str],
        views: dict[str, dict[str, Any]],
        owner: bool,
    ) -> dict[str, Any]:
        """Aggregated 90-day view. Public omits currently-live hosts that are not in the pool."""
        now = datetime.now(timezone.utc)
        start = (now - timedelta(days=self.days - 1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        hidden = set() if owner else (live - available)
        rows: list[dict[str, Any]] = []
        urls = set(self.events) | available
        if owner:
            urls |= live
        for url in urls:
            if url in hidden:
                continue
            events = self.events.get(url) or []
            parsed: list[tuple[datetime, str | None]] = []
            for item in events:
                stamp = _parse_ts(str(item.get("ts") or ""))
                if stamp is None:
                    continue
                parsed.append((stamp, item.get("reason")))
            parsed.sort(key=lambda item: item[0])
            by_day = [0] * self.days
            last_at = parsed[-1][0] if parsed else None
            last_reason = parsed[-1][1] if parsed else None
            week_cutoff = now - timedelta(days=7)
            day_cutoff = now - timedelta(days=1)
            downs_7d = 0
            downs_24h = 0
            for stamp, _reason in parsed:
                if stamp >= week_cutoff:
                    downs_7d += 1
                if stamp >= day_cutoff:
                    downs_24h += 1
                offset = (stamp.astimezone(timezone.utc).replace(
                    hour=0, minute=0, second=0, microsecond=0
                ) - start).days
                if 0 <= offset < self.days:
                    by_day[offset] += 1
            view = views.get(url) or {}
            rows.append(
                {
                    "url": url,
                    "host": _host(url),
                    "in_pool": url in available,
                    "healthy": view.get("healthy"),
                    "cloudflare_proxied": bool(view.get("cloudflare_proxied")),
                    "cloudflare": bool(view.get("cloudflare")),
                    "nameserver": view.get("nameserver"),
                    "downs_90d": len(parsed),
                    "downs_7d": downs_7d,
                    "downs_24h": downs_24h,
                    "last_down_at": last_at.isoformat() if last_at else None,
                    "last_reason": last_reason,
                    "by_day": by_day,
                }
            )
        rows.sort(key=lambda row: (-int(row["downs_90d"]), str(row["host"])))
        return {
            "window_days": self.days,
            "generated_at": now.isoformat(),
            "url_count": len(rows),
            "total_downs": sum(int(row["downs_90d"]) for row in rows),
            "urls": rows,
        }
