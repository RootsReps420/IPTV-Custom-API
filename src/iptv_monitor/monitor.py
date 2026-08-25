"""Main loop: probe URLs, count failures, swap via EPGenius, feed the dashboard.

Each cycle reloads YAML, health-checks every live + standby host, records
healthy→down edges (24h frequent-failure file AND 90-day History store), then
auto-fails live playlists after 3 consecutive downs. Manual Switch / Choose URL /
Switch back share `_swap_lock` with auto failover so they cannot race.

This module never auto-swaps a playlist with failover: false (Magnum / Watch).
Manual Switch is allowed only onto URLs in the same provider pool.
Strong 8K and Magnum credentials are never mixed on health checks or failovers.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from iptv_monitor.config import (
    AppConfig,
    Playlist,
    load_config,
    load_settings,
    normalize_pool,
    pool_label,
    resolve_paths,
    update_player_dns,
    update_playlist_dns,
    DEFAULT_POOL,
)
from iptv_monitor.epgenius import EpgeniusError, update_creds
from iptv_monitor.health import HealthResult, check_url, check_urls, normalize_url
from iptv_monitor.history import UrlHistoryStore
from iptv_monitor.notify import (
    DiscordStatusBoard,
    notify_epgenius_error,
    notify_no_standby,
    notify_swap,
    notify_url_down,
    notify_url_up,
)

logger = logging.getLogger("iptv_monitor.monitor")

# Only used by `test dashboard --demo-down` so the red banner can be reviewed.
DEMO_DOWN_URL = "http://dry-run-demo.invalid"


class SwitchError(Exception):
    """Owner dashboard asked for a manual swap that cannot run."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass
class UrlStats:
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    last_healthy: bool | None = None
    last_result: HealthResult | None = None
    # Timestamps of healthy → down transitions (pruned to the frequent-failure window).
    down_at: list[datetime] = field(default_factory=list)


@dataclass
class FailoverPlan:
    failed_url: str
    fail_reason: str | None
    failures: int
    threshold: int
    playlists: list[Playlist]
    candidate: str | None
    status: str  # waiting | swap | no_standby


@dataclass
class SharedState:
    """In-memory dashboard snapshot. Public vs owner is a filter, not a second store."""
    """Snapshot the dashboard polls. Keep passwords off this object."""

    last_cycle_at: datetime | None = None
    check_interval_seconds: int = 10
    live: list[dict[str, Any]] = field(default_factory=list)
    available: list[dict[str, Any]] = field(default_factory=list)
    playlists: list[dict[str, Any]] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    dry_run: bool = False

    def add_event(self, kind: str, message: str) -> None:
        """Prepend a dashboard event. Keep 40 so the public page stays small."""
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
        """Full owner payload including live DNS and playlists."""
        live_up = sum(1 for row in self.live if row.get("healthy"))
        avail_up = sum(1 for row in self.available if row.get("healthy"))
        return {
            "owner": True,
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

    def public_snapshot(self) -> dict[str, Any]:
        """Standby pool health only — no playlists or currently-live DNS."""
        data = self.snapshot()
        data["owner"] = False
        data["playlists"] = []
        data["live"] = []
        data["counts"] = {
            **data["counts"],
            "playlists": 0,
            "live_up": 0,
            "live_total": 0,
        }
        data["available"] = [_public_url_row(row) for row in data.get("available") or []]
        data["events"] = [
            item for item in data.get("events") or [] if _public_event(item)
        ]
        data["alerts"] = [
            text for text in data.get("alerts") or [] if "live URL" not in text
        ]
        return data


def _public_url_row(row: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(row)
    cleaned["playlists"] = []
    return cleaned


def _public_event(item: dict[str, Any]) -> bool:
    if item.get("kind") not in {"down", "up"}:
        return False
    message = str(item.get("message") or "")
    return not (message.startswith("live ") or message.startswith("both "))


def _pool_for_url(cfg: AppConfig, url: str) -> str:
    """Provider pool for a host: urls.yaml tag, else the playlist that currently lives there."""
    try:
        key = normalize_url(url)
    except ValueError:
        return DEFAULT_POOL
    for item in cfg.available_pool:
        try:
            if normalize_url(item.url) == key:
                return normalize_pool(item.pool)
        except ValueError:
            continue
    for playlist in cfg.playlists:
        try:
            if normalize_url(playlist.current_dns) == key:
                return normalize_pool(playlist.pool)
        except ValueError:
            continue
    return DEFAULT_POOL


def _role(url: str, live: set[str], available: set[str]) -> str:
    in_live = url in live
    in_avail = url in available
    if in_live and in_avail:
        return "both"
    if in_live:
        return "live"
    return "available"


def _cloudflare_flag(result: HealthResult | None) -> tuple[bool, bool]:
    """(proxied, any Cloudflare — proxy or NS)."""
    if result is None:
        return False, False
    proxied = bool(result.cloudflare_proxied)
    any_cf = proxied or (result.nameserver or "") == "cloudflare"
    return proxied, any_cf


def _url_view(
    url: str,
    role: str,
    result: HealthResult | None,
    stats: UrlStats,
    playlist_names: list[str],
    *,
    frequent_threshold: int = 3,
    pool: str = DEFAULT_POOL,
) -> dict[str, Any]:
    proxied, any_cf = _cloudflare_flag(result)
    down_events = len(stats.down_at)
    tagged = normalize_pool(pool)
    return {
        "url": url,
        "role": role,
        "pool": tagged,
        "pool_label": pool_label(tagged),
        "healthy": bool(result.healthy) if result else False,
        "dns_ok": bool(result.dns_ok) if result else False,
        "tcp_ok": bool(result.tcp_ok) if result else False,
        "http_ok": result.http_ok if result else None,
        "stream_ok": result.stream_ok if result else None,
        "fail_reason": result.fail_reason if result else "not_checked",
        "resolved_ips": list(result.resolved_ips) if result else [],
        "nameserver": result.nameserver if result else None,
        "nameserver_hosts": list(result.nameserver_hosts) if result else [],
        "cloudflare_proxied": proxied,
        "cloudflare": any_cf,
        "consecutive_failures": stats.consecutive_failures,
        "consecutive_successes": stats.consecutive_successes,
        "last_checked": result.checked_at.isoformat() if result else None,
        "playlists": playlist_names,
        "down_events_24h": down_events,
        "frequent_failure": down_events >= frequent_threshold,
    }


class Monitor:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root
        self.stats: dict[str, UrlStats] = {}
        self.shared = SharedState()
        self._last_results: dict[str, HealthResult] = {}
        self._last_available_keys: list[str] = []
        self._last_live_keys: list[str] = []
        self._last_cfg: AppConfig | None = None
        self.last_plans: list[FailoverPlan] = []
        self.status_board = DiscordStatusBoard()
        self._swap_lock = asyncio.Lock()
        self.watch_syncer = None
        self.watch_service = None
        self._load_failure_history()
        days = 90
        try:
            days = load_settings(resolve_paths(self.root).settings).history_retention_days
        except Exception:  # noqa: BLE001
            pass
        self.url_history = UrlHistoryStore(self._url_history_path(), days=days)
        self.url_history.seed_from_stamps(
            {url: list(stats.down_at) for url, stats in self.stats.items()}
        )

    def _stat(self, url: str) -> UrlStats:
        if url not in self.stats:
            self.stats[url] = UrlStats()
        return self.stats[url]

    def _url_history_path(self) -> Path:
        return resolve_paths(self.root).root / "state" / "url_history.json"

    def _failure_history_path(self) -> Path:
        return resolve_paths(self.root).root / "state" / "failure_history.json"

    def _failure_window(self, settings: Any | None = None) -> timedelta:
        hours = 24
        if settings is not None:
            hours = max(1, int(settings.frequent_failure_window_hours))
        return timedelta(hours=hours)

    def _prune_down_events(self, stats: UrlStats, window: timedelta) -> None:
        cutoff = datetime.now(timezone.utc) - window
        stats.down_at = [stamp for stamp in stats.down_at if stamp > cutoff]

    def _load_failure_history(self) -> None:
        path = self._failure_history_path()
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Could not read failure history from %s", path)
            return
        if not isinstance(raw, dict):
            return
        window = self._failure_window()
        for url, stamps in raw.items():
            stats = self._stat(str(url))
            parsed: list[datetime] = []
            for item in stamps or []:
                try:
                    stamp = datetime.fromisoformat(str(item))
                except ValueError:
                    continue
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=timezone.utc)
                parsed.append(stamp)
            stats.down_at = parsed
            self._prune_down_events(stats, window)

    def _save_failure_history(self, window: timedelta) -> None:
        path = self._failure_history_path()
        payload: dict[str, list[str]] = {}
        for url, stats in self.stats.items():
            self._prune_down_events(stats, window)
            if stats.down_at:
                payload[url] = [stamp.isoformat() for stamp in stats.down_at]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def _record_down_event(self, stats: UrlStats, result: HealthResult, window: timedelta) -> bool:
        """Count a separate outage when a URL goes from up (or unknown) to down."""
        self._prune_down_events(stats, window)
        if result.healthy:
            return False
        previous = stats.last_healthy
        if previous is True:
            stats.down_at.append(datetime.now(timezone.utc))
            return True
        if previous is None and not stats.down_at:
            stats.down_at.append(datetime.now(timezone.utc))
            return True
        return False

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
        """One probe of every live + standby URL, then optional failover + Discord."""
        cfg = load_config(self.root)
        settings = cfg.settings
        self.shared.check_interval_seconds = settings.check_interval_seconds

        live_keys = [normalize_url(item.current_dns) for item in cfg.playlists]
        available_keys = [normalize_url(url) for url in cfg.available_urls]
        grouped: dict[str, list[str]] = {}
        claimed: dict[str, str] = {}
        for playlist in cfg.playlists:
            key = normalize_url(playlist.current_dns)
            pool = normalize_pool(playlist.pool)
            grouped.setdefault(pool, [])
            if key not in claimed:
                claimed[key] = pool
                grouped[pool].append(key)
        for item in cfg.available_pool:
            key = normalize_url(item.url)
            pool = normalize_pool(item.pool)
            grouped.setdefault(pool, [])
            if key not in claimed:
                claimed[key] = pool
                grouped[pool].append(key)
            elif claimed[key] != pool:
                logger.warning(
                    "URL %s is tagged %s and %s; health-checking as %s",
                    key,
                    claimed[key],
                    pool,
                    claimed[key],
                )
        results: dict[str, HealthResult] = {}
        for pool, urls in grouped.items():
            creds = [
                (item.username, item.password)
                for item in cfg.playlists
                if normalize_pool(item.pool) == pool and item.username and item.password
            ]
            batch = await check_urls(urls, settings, creds or None)
            results.update(batch)

        live_set = set(live_keys)
        available_set = set(available_keys)

        window = self._failure_window(settings)
        self.url_history.days = max(7, int(settings.history_retention_days))
        for url, result in results.items():
            stats = self._stat(url)
            stats.last_result = result
            if self._record_down_event(stats, result, window):
                self.url_history.record(url, result.fail_reason)
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

        # Drop stats for URLs that left the config so counters cannot leak forever.
        current = live_set | available_set
        self.stats = {url: stats for url, stats in self.stats.items() if url in current}
        self._save_failure_history(window)
        self.url_history.save()
        self._publish_snapshot(cfg, results, live_set, available_set)
        if notify:
            await self.status_board.sync(cfg, self.shared.snapshot())

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
        """Discord + event log only when health changes (or on first sight of a down URL)."""
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
                if playlist.failover and normalize_url(playlist.current_dns) == live_url
            ]
            if not affected:
                continue
            pool_keys = [
                normalize_url(url) for url in cfg.urls_in_pool(affected[0].pool)
            ]
            candidate = self._pick_candidate(
                pool_keys,
                live_url,
                results,
                min_successes,
                frequent_threshold=max(2, int(cfg.settings.frequent_failure_down_events)),
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
        """What would swap if the 3-failure threshold were already met (dry-run)."""
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
        async with self._swap_lock:
            fresh = load_config(self.root)
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
                    await notify_no_standby(fresh.secrets, plan.failed_url, plan.playlists)
                    continue
                if plan.candidate is None:
                    continue
                affected = [
                    playlist
                    for playlist in fresh.playlists
                    if playlist.failover
                    and normalize_url(playlist.current_dns) == plan.failed_url
                ]
                if not affected:
                    continue
                for playlist in affected:
                    await self._swap_playlist(
                        fresh, playlist, plan.failed_url, plan.candidate
                    )

    def _pick_candidate(
        self,
        available_keys: list[str],
        failed_url: str,
        results: dict[str, HealthResult],
        min_successes: int,
        *,
        frequent_threshold: int = 3,
        log: bool = True,
    ) -> str | None:
        """Pick a healthy standby.

        Prefer hosts that are not Frequent failure, then the usual Cloudflare order:
        no Cloudflare → CF NS → CF proxy. Frequent-failure standbys are only used
        when every other healthy option is already out.
        """
        picked = self._pick_from_healthy(
            available_keys,
            failed_url,
            results,
            min_successes,
            allow_frequent=False,
            frequent_threshold=frequent_threshold,
            log=log,
        )
        if picked:
            return picked
        return self._pick_from_healthy(
            available_keys,
            failed_url,
            results,
            min_successes,
            allow_frequent=True,
            frequent_threshold=frequent_threshold,
            log=log,
        )

    def _is_frequent_failure(self, url: str, threshold: int) -> bool:
        return len(self._stat(url).down_at) >= threshold

    def _pick_from_healthy(
        self,
        available_keys: list[str],
        failed_url: str,
        results: dict[str, HealthResult],
        min_successes: int,
        *,
        allow_frequent: bool,
        frequent_threshold: int,
        log: bool = True,
    ) -> str | None:
        # 0 = no Cloudflare, 1 = Cloudflare nameservers only, 2 = orange-cloud proxy
        buckets: list[list[str]] = [[], [], []]
        for url in available_keys:
            if url == failed_url:
                continue
            result = results.get(url)
            if result is None or not result.healthy:
                continue
            frequent = self._is_frequent_failure(url, frequent_threshold)
            if frequent and not allow_frequent:
                continue
            if not frequent and allow_frequent:
                continue
            if result.cloudflare_proxied:
                tier = 2
            elif (result.nameserver or "") == "cloudflare":
                tier = 1
            else:
                tier = 0
            buckets[tier].append(url)

        labels = ("origin", "cf-ns", "cf-proxy")
        for tier, bucket in enumerate(buckets):
            preferred = [
                url for url in bucket if self._stat(url).consecutive_successes >= min_successes
            ]
            pool = preferred or bucket
            if pool:
                tag = labels[tier]
                if allow_frequent:
                    tag = f"{tag}+frequent"
                if log:
                    logger.info("Standby candidate %s (preference %s)", pool[0], tag)
                return pool[0]
        return None

    def _candidate_for(self, cfg: AppConfig, playlist: Playlist, *, log: bool = False) -> str | None:
        if not self._last_results:
            return None
        current = normalize_url(playlist.current_dns)
        pool_keys = [normalize_url(url) for url in cfg.urls_in_pool(playlist.pool)]
        return self._pick_candidate(
            pool_keys,
            current,
            self._last_results,
            cfg.settings.min_consecutive_successes_for_swap,
            frequent_threshold=max(2, int(cfg.settings.frequent_failure_down_events)),
            log=log,
        )

    def _find_playlist(self, cfg: AppConfig, playlist_id: str) -> Playlist:
        wanted = str(playlist_id).strip()
        playlist = next(
            (item for item in cfg.playlists if str(item.playlist_id) == wanted),
            None,
        )
        if playlist is None:
            raise SwitchError(f"Playlist {wanted} was not found.", 404)
        return playlist

    def _publish_after_manual(self, cfg: AppConfig) -> None:
        live_keys = [normalize_url(item.current_dns) for item in cfg.playlists]
        self._last_cfg = cfg
        self._last_live_keys = live_keys
        self._publish_snapshot(
            cfg,
            self._last_results,
            set(live_keys),
            set(normalize_url(url) for url in cfg.available_urls),
        )

    async def manual_switch(
        self,
        playlist_id: str,
        target_url: str | None = None,
    ) -> dict[str, Any]:
        """Swap one playlist now. Optional target_url must be a healthy pool URL."""
        if self.shared.dry_run:
            raise SwitchError("Dry run — manual switches are disabled.", 409)
        if not self._last_results:
            raise SwitchError("No health snapshot yet — wait for the first check cycle.", 503)

        async with self._swap_lock:
            cfg = load_config(self.root)
            playlist = self._find_playlist(cfg, playlist_id)
            old_url = normalize_url(playlist.current_dns)
            if target_url:
                candidate = self._resolve_chosen_url(cfg, playlist, target_url)
            else:
                candidate = self._candidate_for(cfg, playlist, log=True)
            if not candidate:
                raise SwitchError("No healthy standby to switch to.", 409)
            await self._swap_playlist(
                cfg, playlist, old_url, candidate, manual=True
            )
            self._publish_after_manual(cfg)
            return {
                "ok": True,
                "playlist_id": playlist.playlist_id,
                "name": playlist.name,
                "from": old_url,
                "to": candidate,
                "mode": "watch" if normalize_pool(playlist.pool) == "magnum" else "epgenius",
            }

    def _resolve_chosen_url(self, cfg: AppConfig, playlist: Playlist, raw: str) -> str:
        """Validate a user-picked URL is in this playlist's provider pool and healthy."""
        try:
            candidate = normalize_url(raw)
        except ValueError as exc:
            raise SwitchError("Invalid target URL.", 400) from exc
        current = normalize_url(playlist.current_dns)
        wanted = normalize_pool(playlist.pool)
        matching = {
            normalize_url(url) for url in cfg.urls_in_pool(playlist.pool)
        }
        if candidate not in matching:
            raise SwitchError(
                f"That URL is not in the {pool_label(wanted)} pool.",
                400,
            )
        if candidate == current:
            raise SwitchError("Playlist is already on that URL.", 409)
        result = self._last_results.get(candidate)
        if result is None:
            raise SwitchError("No health snapshot for that URL yet — wait for a check cycle.", 503)
        if not result.healthy:
            reason = result.fail_reason or "down"
            raise SwitchError(
                f"That URL is down ({reason}). Choose a healthy one from the {pool_label(wanted)} pool.",
                409,
            )
        logger.info("Standby candidate %s (user-selected, pool %s)", candidate, wanted)
        return candidate

    async def manual_revert(self, playlist_id: str) -> dict[str, Any]:
        """Health-check the pre-manual URL, then EPGenius back to it if it is up."""
        if self.shared.dry_run:
            raise SwitchError("Dry run — manual switches are disabled.", 409)

        async with self._swap_lock:
            cfg = load_config(self.root)
            playlist = self._find_playlist(cfg, playlist_id)
            origin = (playlist.manual_from_dns or "").strip()
            if not origin:
                raise SwitchError("No manual switch to revert on this playlist.", 409)
            target = normalize_url(origin)
            current = normalize_url(playlist.current_dns)
            if target == current:
                playlist.manual_from_dns = None
                update_playlist_dns(
                    cfg.paths.playlists,
                    playlist.playlist_id,
                    current,
                    manual_from_dns=None,
                )
                self._publish_after_manual(cfg)
                return {
                    "ok": True,
                    "playlist_id": playlist.playlist_id,
                    "name": playlist.name,
                    "from": current,
                    "to": target,
                    "already": True,
                }

            credentials = [
                (item.username, item.password)
                for item in cfg.playlists
                if normalize_pool(item.pool) == normalize_pool(playlist.pool)
                and item.username
                and item.password
            ]
            result = await check_url(target, cfg.settings, credentials or None)
            self._last_results[result.url] = result
            self._stat(result.url).last_result = result
            if not result.healthy:
                reason = result.fail_reason or "down"
                raise SwitchError(
                    f"Original DNS failed the health check ({reason}). Not switching back.",
                    409,
                )

            await self._swap_playlist(
                cfg, playlist, current, target, revert=True
            )
            self._publish_after_manual(cfg)
            return {
                "ok": True,
                "playlist_id": playlist.playlist_id,
                "name": playlist.name,
                "from": current,
                "to": target,
                "mode": "watch" if normalize_pool(playlist.pool) == "magnum" else "epgenius",
            }

    def _kick_watch_refresh(self) -> None:
        """Reload player.yaml immediately and queue a /watch catalogue pull."""
        from iptv_monitor.player_sync import queue_watch_force

        queue_watch_force(self.root, "playlist")
        watch = getattr(self, "watch_service", None)
        if watch is not None and hasattr(watch, "invalidate_config"):
            watch.invalidate_config()
        syncer = getattr(self, "watch_syncer", None)
        if syncer is not None and hasattr(syncer, "wake"):
            syncer.wake()

    async def _swap_watch_dns(
        self,
        cfg: AppConfig,
        playlist: Playlist,
        old_url: str,
        new_url: str,
        *,
        manual: bool = False,
        revert: bool = False,
    ) -> None:
        """Point /watch at a Magnum DNS by writing player.yaml. No EPGenius call."""
        try:
            update_player_dns(cfg.paths.player, new_url)
        except Exception as exc:
            logger.exception("Could not update player.yaml for %s", playlist.name)
            raise SwitchError(f"Could not update Watch DNS on the VPS: {exc}", 500) from exc

        origin_kw: dict[str, Any] = {}
        if revert:
            playlist.manual_from_dns = None
            origin_kw["manual_from_dns"] = None
        elif manual and not playlist.manual_from_dns:
            playlist.manual_from_dns = old_url
            origin_kw["manual_from_dns"] = old_url

        try:
            update_playlist_dns(
                cfg.paths.playlists, playlist.playlist_id, new_url, **origin_kw
            )
        except Exception:
            logger.exception("player.yaml updated but failed to persist current_dns for %s", playlist.name)
        playlist.current_dns = new_url
        self._kick_watch_refresh()
        logger.info("Watch DNS swapped %s from %s to %s", playlist.name, old_url, new_url)
        prefix = "manual revert " if revert else ("manual " if manual else "")
        self.shared.add_event(
            "swap",
            f"{prefix}{playlist.name}: {old_url} -> {new_url} (Watch DNS, no EPGenius)",
        )
        if manual or revert:
            asyncio.create_task(self._after_manual_notify(cfg, playlist, old_url, new_url))
            return
        await notify_swap(cfg.secrets, playlist, old_url, new_url)

    async def _swap_playlist(
        self,
        cfg: AppConfig,
        playlist: Playlist,
        old_url: str,
        new_url: str,
        *,
        manual: bool = False,
        revert: bool = False,
    ) -> None:
        if normalize_pool(playlist.pool) == "magnum":
            await self._swap_watch_dns(
                cfg, playlist, old_url, new_url, manual=manual, revert=revert
            )
            return
        timeout = 12 if (manual or revert) else 20
        try:
            await update_creds(cfg.secrets, playlist, new_url, timeout_seconds=timeout)
        except EpgeniusError as exc:
            logger.error("EPGenius swap failed for %s: %s", playlist.name, exc)
            self.shared.add_event(
                "error",
                f"EPGenius failed for {playlist.name}: {exc}",
            )
            if manual or revert:
                asyncio.create_task(
                    notify_epgenius_error(
                        cfg.secrets, playlist, old_url, new_url, str(exc)
                    )
                )
                raise SwitchError(str(exc), 502) from exc
            await notify_epgenius_error(cfg.secrets, playlist, old_url, new_url, str(exc))
            return

        origin_kw: dict[str, Any] = {}
        if revert:
            playlist.manual_from_dns = None
            origin_kw["manual_from_dns"] = None
        elif manual and not playlist.manual_from_dns:
            playlist.manual_from_dns = old_url
            origin_kw["manual_from_dns"] = old_url

        try:
            update_playlist_dns(
                cfg.paths.playlists, playlist.playlist_id, new_url, **origin_kw
            )
        except Exception:
            logger.exception("API succeeded but failed to persist current_dns for %s", playlist.name)
        playlist.current_dns = new_url
        logger.info("Swapped %s from %s to %s", playlist.name, old_url, new_url)
        prefix = "manual revert " if revert else ("manual " if manual else "")
        self.shared.add_event("swap", f"{prefix}{playlist.name}: {old_url} -> {new_url}")
        if manual or revert:
            asyncio.create_task(self._after_manual_notify(cfg, playlist, old_url, new_url))
            return
        await notify_swap(cfg.secrets, playlist, old_url, new_url)

    async def _after_manual_notify(
        self,
        cfg: AppConfig,
        playlist: Playlist,
        old_url: str,
        new_url: str,
    ) -> None:
        try:
            await notify_swap(cfg.secrets, playlist, old_url, new_url, manual=True)
        except Exception:
            logger.exception("Discord swap notify failed after manual switch")
        try:
            await self.status_board.sync(cfg, self.shared.snapshot())
        except Exception:
            logger.exception("Status board sync failed after manual switch")

    def _publish_snapshot(
        self,
        cfg: AppConfig,
        results: dict[str, HealthResult],
        live_set: set[str],
        available_set: set[str],
    ) -> None:
        """Refresh SharedState rows the dashboard polls."""
        names_by_url: dict[str, list[str]] = {}
        for playlist in cfg.playlists:
            key = normalize_url(playlist.current_dns)
            names_by_url.setdefault(key, []).append(playlist.name)

        threshold = max(2, int(cfg.settings.frequent_failure_down_events))
        live_rows = []
        for url in sorted(live_set):
            live_rows.append(
                _url_view(
                    url,
                    _role(url, live_set, available_set),
                    results.get(url),
                    self._stat(url),
                    names_by_url.get(url, []),
                    frequent_threshold=threshold,
                    pool=_pool_for_url(cfg, url),
                )
            )
        available_rows = []
        for item in cfg.available_pool:
            key = normalize_url(item.url)
            available_rows.append(
                _url_view(
                    key,
                    _role(key, live_set, available_set),
                    results.get(key),
                    self._stat(key),
                    names_by_url.get(key, []),
                    frequent_threshold=threshold,
                    pool=item.pool,
                )
            )

        self.shared.last_cycle_at = datetime.now(timezone.utc)
        self.shared.live = live_rows
        self.shared.available = available_rows
        self.shared.playlists = []
        for playlist in cfg.playlists:
            dns_key = normalize_url(playlist.current_dns)
            result = results.get(dns_key)
            proxied, any_cf = _cloudflare_flag(result)
            revert_dns = None
            if playlist.manual_from_dns:
                try:
                    revert_dns = normalize_url(playlist.manual_from_dns)
                except ValueError:
                    revert_dns = str(playlist.manual_from_dns).strip()
                if revert_dns == dns_key:
                    revert_dns = None
            self.shared.playlists.append(
                {
                    "name": playlist.name,
                    "playlist_id": playlist.playlist_id,
                    "username": playlist.username,
                    "current_dns": dns_key,
                    "healthy": bool(result and result.healthy),
                    "nameserver": result.nameserver if result else None,
                    "cloudflare_proxied": proxied,
                    "cloudflare": any_cf,
                    "failover": bool(playlist.failover),
                    "pool": normalize_pool(playlist.pool),
                    "pool_label": pool_label(playlist.pool),
                    "next_standby": self._candidate_for(cfg, playlist),
                    "revert_dns": revert_dns,
                }
            )
        self._refresh_alerts()

    def history_snapshot(self, *, owner: bool = False) -> dict[str, Any]:
        """90-day down counts per URL. Public omits currently-live hosts not in the pool."""
        views: dict[str, dict[str, Any]] = {}
        for row in list(self.shared.available) + list(self.shared.live):
            url = row.get("url")
            if url:
                views[str(url)] = row
        available = set(self._last_available_keys)
        live = set(self._last_live_keys)
        if not available and not live:
            available = {str(row.get("url")) for row in self.shared.available if row.get("url")}
            live = {str(row.get("url")) for row in self.shared.live if row.get("url")}
        return self.url_history.snapshot(
            available=available,
            live=live,
            views=views,
            owner=owner,
        )

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
        """Force a fake down live URL so the dashboard banner can be reviewed."""
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
                "nameserver": None,
                "cloudflare_proxied": False,
                "cloudflare": False,
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
            f"{'URL':<48} {'ROLE':<10} {'DNS':<6} {'TCP':<6} {'TS':<6} {'NS':<12} {'FAILS':<6} {'REASON'}",
            "-" * 116,
        ]
        for url in all_urls:
            row = by_url.get(url)
            if not row:
                continue
            ns = row.get("nameserver") or ""
            if row.get("cloudflare_proxied"):
                ns = f"{ns}+proxy" if ns else "cf-proxy"
            ts = row.get("stream_ok")
            ts_flag = "ok" if ts else ("skip" if ts is None else "FAIL")
            lines.append(
                f"{row['url']:<48} {row['role']:<10} "
                f"{_flag(row['dns_ok']):<6} {_flag(row['tcp_ok']):<6} "
                f"{ts_flag:<6} {ns:<12} {row['consecutive_failures']:<6} {row['fail_reason'] or ''}"
            )
        if len(lines) == 2:
            lines.append("(no URLs checked)")
        return "\n".join(lines)


def _flag(ok: bool) -> str:
    return "ok" if ok else "FAIL"
