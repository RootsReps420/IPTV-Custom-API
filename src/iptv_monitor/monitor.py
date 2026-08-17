from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from iptv_monitor.config import AppConfig, Playlist, load_config, load_settings, resolve_paths, update_playlist_dns
from iptv_monitor.epgenius import EpgeniusError, update_creds
from iptv_monitor.health import HealthResult, check_urls, normalize_url
from iptv_monitor.notify import (
    notify_epgenius_error,
    notify_no_standby,
    notify_swap,
    notify_url_down,
    notify_url_up,
)

logger = logging.getLogger("iptv_monitor.monitor")

DEMO_DOWN_URL = "http://dry-run-demo.invalid"


@dataclass
class UrlStats:
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    last_healthy: bool | None = None
    last_result: HealthResult | None = None


@dataclass
class FailoverPlan:
    failed_url: str
    fail_reason: str | None
    failures: int
    threshold: int
    playlists: list[Playlist]
    candidate: str | None
    status: str


@dataclass
class SharedState:
    last_cycle_at: datetime | None = None
    check_interval_seconds: int = 30
    live: list[dict[str, Any]] = field(default_factory=list)
    available: list[dict[str, Any]] = field(default_factory=list)
    playlists: list[dict[str, Any]] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    dry_run: bool = False

    def add_event(self, kind: str, message: str) -> None:
        self.events.insert(
            0,
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "kind": kind,
                "message": message,
            },
        )
        self.events = self.events[:40]

    def snapshot(self) -> dict[str, Any]:
        live_up = sum(1 for row in self.live if row.get("healthy"))
        avail_up = sum(1 for row in self.available if row.get("healthy"))
        return {
            "last_cycle_at": self.last_cycle_at.isoformat() if self.last_cycle_at else None,
            "check_interval_seconds": self.check_interval_seconds,
            "live": self.live,
            "available": self.available,
            "playlists": self.playlists,
            "alerts": self.alerts,
            "events": self.events,
            "error": self.error,
            "dry_run": self.dry_run,
            "counts": {
                "live_up": live_up,
                "live_total": len(self.live),
                "available_up": avail_up,
                "available_total": len(self.available),
                "playlists": len(self.playlists),
            },
        }


def _role(url: str, live: set[str], available: set[str]) -> str:
    in_live = url in live
    in_avail = url in available
    if in_live and in_avail:
        return "both"
    if in_live:
        return "live"
    return "available"


def _url_view(
    url: str,
    role: str,
    result: HealthResult | None,
    stats: UrlStats,
    playlist_names: list[str],
) -> dict[str, Any]:
    return {
        "url": url,
        "role": role,
        "healthy": bool(result.healthy) if result else False,
        "dns_ok": bool(result.dns_ok) if result else False,
        "tcp_ok": bool(result.tcp_ok) if result else False,
        "http_ok": result.http_ok if result else None,
        "fail_reason": result.fail_reason if result else "not_checked",
        "resolved_ips": list(result.resolved_ips) if result else [],
        "consecutive_failures": stats.consecutive_failures,
        "consecutive_successes": stats.consecutive_successes,
        "last_checked": result.checked_at.isoformat() if result else None,
        "playlists": playlist_names,
    }


class Monitor:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root
        self.stats: dict[str, UrlStats] = {}
        self.shared = SharedState()
        self._last_results: dict[str, HealthResult] = {}
        self._last_live: set[str] = set()
        self._last_available: set[str] = set()
        self._last_available_keys: list[str] = []
        self._last_live_keys: list[str] = []
        self._last_cfg: AppConfig | None = None
        self.last_plans: list[FailoverPlan] = []

    def _stat(self, url: str) -> UrlStats:
        if url not in self.stats:
            self.stats[url] = UrlStats()
        return self.stats[url]

    async def run_forever(self) -> None:
        while True:
            try:
                await self.run_cycle(swap=True, notify=True)
                self.shared.error = None
            except Exception as exc:  # noqa: BLE001
                logger.exception("Monitor cycle failed")
                self.shared.error = str(exc)
            try:
                interval = load_settings(resolve_paths(self.root).settings).check_interval_seconds
            except Exception:  # noqa: BLE001
                interval = 30
            await asyncio.sleep(interval)

    async def run_cycle(self, *, swap: bool, notify: bool) -> None:
        cfg = load_config(self.root)
        settings = cfg.settings
        self.shared.check_interval_seconds = settings.check_interval_seconds

        live_keys = [normalize_url(item.current_dns) for item in cfg.playlists]
        available_keys = [normalize_url(url) for url in cfg.available_urls]
        results = await check_urls(live_keys + available_keys, settings)

        live_set = set(live_keys)
        available_set = set(available_keys)

        for url, result in results.items():
            stats = self._stat(url)
            stats.last_result = result
            if result.healthy:
                stats.consecutive_failures = 0
                stats.consecutive_successes += 1
            else:
                stats.consecutive_failures += 1
                stats.consecutive_successes = 0

            role = _role(url, live_set, available_set)
            if notify:
                await self._emit_transition(cfg, url, role, result, stats)
            stats.last_healthy = result.healthy

        self._last_cfg = cfg
        self._last_results = results
        self._last_live_keys = live_keys
        self._last_available_keys = available_keys
        self.last_plans = self._build_plans(
            cfg, results, live_keys, available_keys, assume_threshold=False
        )

        if swap:
            await self._execute_plans(cfg, self.last_plans)
            live_keys = [normalize_url(item.current_dns) for item in cfg.playlists]
            live_set = set(live_keys)

        current = live_set | available_set
        self.stats = {url: stats for url, stats in self.stats.items() if url in current}
        self._last_live = live_set
        self._last_available = available_set
        self._publish_snapshot(cfg, results, live_set, available_set)

        live_up = sum(1 for url in live_set if results.get(url) and results[url].healthy)
        avail_up = sum(1 for url in available_set if results.get(url) and results[url].healthy)
        logger.info(
            "Cycle complete: live %s/%s healthy, available %s/%s healthy",
            live_up,
            len(live_set),
            avail_up,
            len(available_set),
        )

    async def _emit_transition(
        self,
        cfg: AppConfig,
        url: str,
        role: str,
        result: HealthResult,
        stats: UrlStats,
    ) -> None:
        previous = stats.last_healthy
        if previous is None:
            if not result.healthy:
                self.shared.add_event(
                    "down",
                    f"{role} {url} down ({result.fail_reason or 'unknown'})",
                )
                await notify_url_down(
                    cfg.secrets, url, role, result.fail_reason, result.error_detail
                )
            return
        if previous and not result.healthy:
            self.shared.add_event(
                "down",
                f"{role} {url} down ({result.fail_reason or 'unknown'})",
            )
            await notify_url_down(
                cfg.secrets, url, role, result.fail_reason, result.error_detail
            )
        elif not previous and result.healthy:
            self.shared.add_event("up", f"{role} {url} recovered")
            await notify_url_up(cfg.secrets, url, role)

    def _build_plans(
        self,
        cfg: AppConfig,
        results: dict[str, HealthResult],
        live_keys: list[str],
        available_keys: list[str],
        *,
        assume_threshold: bool = False,
    ) -> list[FailoverPlan]:
        threshold = cfg.settings.consecutive_failures_to_swap
        min_successes = cfg.settings.min_consecutive_successes_for_swap
        plans: list[FailoverPlan] = []
        seen: set[str] = set()
        for live_url in live_keys:
            if live_url in seen:
                continue
            seen.add(live_url)
            result = results.get(live_url)
            if result is None or result.healthy:
                continue
            failures = self._stat(live_url).consecutive_failures
            affected = [
                playlist
                for playlist in cfg.playlists
                if normalize_url(playlist.current_dns) == live_url
            ]
            candidate = self._pick_candidate(
                available_keys, live_url, results, min_successes
            )
            ready = assume_threshold or failures >= threshold
            if not ready:
                status = "waiting"
            elif candidate:
                status = "swap"
            else:
                status = "no_standby"
            plans.append(
                FailoverPlan(
                    failed_url=live_url,
                    fail_reason=result.fail_reason,
                    failures=failures,
                    threshold=threshold,
                    playlists=affected,
                    candidate=candidate,
                    status=status,
                )
            )
        return plans

    def simulated_failover_plans(self) -> list[FailoverPlan]:
        if self._last_cfg is None:
            return []
        return self._build_plans(
            self._last_cfg,
            self._last_results,
            self._last_live_keys,
            self._last_available_keys,
            assume_threshold=True,
        )

    def format_failover_preview(self, plans: list[FailoverPlan] | None = None) -> str:
        items = plans if plans is not None else self.last_plans
        if not items:
            return "No live URLs are down — nothing to fail over."
        lines = []
        for plan in items:
            names = ", ".join(item.name for item in plan.playlists) or "(none)"
            if plan.status == "waiting":
                lines.append(
                    f"  WAIT  {plan.failed_url}  {plan.fail_reason or 'down'}  "
                    f"{plan.failures}/{plan.threshold} failures  playlists: {names}"
                )
            elif plan.status == "no_standby":
                lines.append(
                    f"  SKIP  {plan.failed_url}  no healthy standby  playlists: {names}"
                )
            else:
                lines.append(
                    f"  SWAP  {plan.failed_url} -> {plan.candidate}  playlists: {names}"
                )
        return "\n".join(lines)

    async def _execute_plans(self, cfg: AppConfig, plans: list[FailoverPlan]) -> None:
        for plan in plans:
            if plan.status == "waiting":
                logger.info(
                    "Live URL %s is down (%s), %s/%s failures",
                    plan.failed_url,
                    plan.fail_reason,
                    plan.failures,
                    plan.threshold,
                )
                continue
            if plan.status == "no_standby":
                logger.warning("No healthy standby for failed live URL %s", plan.failed_url)
                self.shared.add_event(
                    "warn",
                    f"No healthy standby for {plan.failed_url}",
                )
                await notify_no_standby(cfg.secrets, plan.failed_url, plan.playlists)
                continue
            if plan.candidate is None:
                continue
            for playlist in plan.playlists:
                await self._swap_playlist(cfg, playlist, plan.failed_url, plan.candidate)

    def _pick_candidate(
        self,
        available_keys: list[str],
        failed_url: str,
        results: dict[str, HealthResult],
        min_successes: int,
    ) -> str | None:
        healthy: list[str] = []
        for url in available_keys:
            if url == failed_url:
                continue
            result = results.get(url)
            if result is None or not result.healthy:
                continue
            healthy.append(url)
        preferred = [
            url for url in healthy if self._stat(url).consecutive_successes >= min_successes
        ]
        pool = preferred or healthy
        return pool[0] if pool else None

    async def _swap_playlist(
        self,
        cfg: AppConfig,
        playlist: Playlist,
        old_url: str,
        new_url: str,
    ) -> None:
        try:
            await update_creds(cfg.secrets, playlist, new_url)
        except EpgeniusError as exc:
            logger.error("EPGenius swap failed for %s: %s", playlist.name, exc)
            self.shared.add_event(
                "down",
                f"EPGenius failed for {playlist.name}: {exc}",
            )
            await notify_epgenius_error(cfg.secrets, playlist, old_url, new_url, str(exc))
            return
        try:
            update_playlist_dns(cfg.paths.playlists, playlist.playlist_id, new_url)
        except Exception:
            logger.exception("API succeeded but failed to persist current_dns for %s", playlist.name)
        playlist.current_dns = new_url
        logger.info("Swapped %s from %s to %s", playlist.name, old_url, new_url)
        self.shared.add_event("swap", f"{playlist.name}: {old_url} -> {new_url}")
        await notify_swap(cfg.secrets, playlist, old_url, new_url)

    def _publish_snapshot(
        self,
        cfg: AppConfig,
        results: dict[str, HealthResult],
        live_set: set[str],
        available_set: set[str],
    ) -> None:
        names_by_url: dict[str, list[str]] = {}
        for playlist in cfg.playlists:
            key = normalize_url(playlist.current_dns)
            names_by_url.setdefault(key, []).append(playlist.name)

        live_rows = []
        for url in sorted(live_set):
            live_rows.append(
                _url_view(
                    url,
                    _role(url, live_set, available_set),
                    results.get(url),
                    self._stat(url),
                    names_by_url.get(url, []),
                )
            )
        available_rows = []
        for url in cfg.available_urls:
            key = normalize_url(url)
            available_rows.append(
                _url_view(
                    key,
                    _role(key, live_set, available_set),
                    results.get(key),
                    self._stat(key),
                    names_by_url.get(key, []),
                )
            )

        self.shared.last_cycle_at = datetime.now(timezone.utc)
        self.shared.live = live_rows
        self.shared.available = available_rows
        self.shared.playlists = [
            {
                "name": playlist.name,
                "playlist_id": playlist.playlist_id,
                "username": playlist.username,
                "current_dns": normalize_url(playlist.current_dns),
                "healthy": bool(
                    results.get(normalize_url(playlist.current_dns))
                    and results[normalize_url(playlist.current_dns)].healthy
                ),
            }
            for playlist in cfg.playlists
        ]
        self._refresh_alerts()

    def _refresh_alerts(self) -> None:
        alerts: list[str] = []
        if self.shared.dry_run:
            alerts.append("DRY RUN — EPGenius swaps and Discord alerts are disabled.")
        if self.shared.error:
            alerts.append(self.shared.error)
        down_live = [row["url"] for row in self.shared.live if not row.get("healthy")]
        down_avail = [row["url"] for row in self.shared.available if not row.get("healthy")]
        if down_live:
            alerts.append(f"{len(down_live)} live URL(s) down: {', '.join(down_live)}")
        if down_avail:
            alerts.append(f"{len(down_avail)} standby URL(s) down: {', '.join(down_avail)}")
        if self.shared.last_cycle_at and not down_live and not down_avail and not self.shared.error:
            alerts.append("All portal URLs are up.")
        self.shared.alerts = alerts

    def inject_demo_down(self) -> None:
        """Force a clearly fake down live URL so the dashboard banner can be reviewed."""
        stats = self._stat(DEMO_DOWN_URL)
        stats.consecutive_failures = max(stats.consecutive_failures, 3)
        demo_result = HealthResult(
            url=DEMO_DOWN_URL,
            host="dry-run-demo.invalid",
            port=80,
            dns_ok=False,
            tcp_ok=False,
            http_ok=None,
            fail_reason="demo_forced_down",
            healthy=False,
        )
        demo_row = _url_view(DEMO_DOWN_URL, "live", demo_result, stats, ["(demo)"])
        self.shared.live = [demo_row, *self.shared.live]
        self.shared.playlists = [
            {
                "name": "(demo)",
                "playlist_id": "dry-run",
                "username": "demo",
                "current_dns": DEMO_DOWN_URL,
                "healthy": False,
            },
            *self.shared.playlists,
        ]
        self._refresh_alerts()

    def format_table(self) -> str:
        all_urls = list(
            dict.fromkeys(
                [row["url"] for row in self.shared.live]
                + [row["url"] for row in self.shared.available]
            )
        )
        by_url = {row["url"]: row for row in self.shared.available}
        by_url.update({row["url"]: row for row in self.shared.live})
        lines = [
            f"{'URL':<48} {'ROLE':<10} {'DNS':<6} {'TCP':<6} {'FAILS':<6} {'REASON'}",
            "-" * 90,
        ]
        for url in all_urls:
            row = by_url.get(url)
            if not row:
                continue
            lines.append(
                f"{row['url']:<48} {row['role']:<10} "
                f"{_flag(row['dns_ok']):<6} {_flag(row['tcp_ok']):<6} "
                f"{row['consecutive_failures']:<6} {row['fail_reason'] or ''}"
            )
        if len(lines) == 2:
            lines.append("(no URLs checked)")
        return "\n".join(lines)


def _flag(ok: bool) -> str:
    return "ok" if ok else "FAIL"
