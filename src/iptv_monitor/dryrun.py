"""Dry-run commands: probe URLs, preview failover, test Discord, run the UI with swaps off."""

from __future__ import annotations

import asyncio
from pathlib import Path

from iptv_monitor.config import load_config
from iptv_monitor.dashboard import serve_dashboard
from iptv_monitor.health import normalize_url
from iptv_monitor.monitor import Monitor
from iptv_monitor.notify import notify_no_standby, notify_swap, notify_url_down, notify_url_up


async def run_url_check(monitor: Monitor) -> int:
    monitor.shared.dry_run = True
    await monitor.run_cycle(swap=False, notify=False)
    print(monitor.format_table())
    print()
    print("Failover preview for this cycle (needs 3 consecutive failures to swap; no API calls):")
    print(monitor.format_failover_preview())
    return 0


async def run_failover_preview(monitor: Monitor) -> int:
    monitor.shared.dry_run = True
    await monitor.run_cycle(swap=False, notify=False)
    print(monitor.format_table())
    print()
    print("Simulated failover if the failure threshold were already met (no EPGenius, no Discord, no file writes):")
    plans = monitor.simulated_failover_plans()
    print(monitor.format_failover_preview(plans))
    return 0


async def run_discord_test(root: Path | None) -> int:
    cfg = load_config(root)
    if not cfg.playlists:
        raise RuntimeError("config/playlists.yaml has no playlists")
    playlist = cfg.playlists[0]
    live = normalize_url(playlist.current_dns)
    standby = (
        normalize_url(cfg.available_urls[0])
        if cfg.available_urls
        else "http://standby.example.com"
    )
    print("Sending [TEST] Discord messages (no EPGenius calls)...")
    await notify_url_down(
        cfg.secrets,
        live,
        "live",
        "dns_nxdomain",
        "Manual dry-run of the alerts webhook.",
        test=True,
    )
    print("  alerts: URL down")
    await notify_url_up(cfg.secrets, live, "live", test=True)
    print("  alerts: URL recovered")
    await notify_no_standby(cfg.secrets, live, cfg.playlists, test=True)
    print("  alerts: no healthy standby")
    await notify_swap(cfg.secrets, playlist, live, standby, test=True)
    print("  swaps: playlist DNS swapped (test only)")
    print("Done. Check the two Discord channels for messages titled [TEST].")
    return 0


async def run_dashboard_test(
    monitor: Monitor,
    *,
    demo_down: bool,
    host: str,
    port: int,
) -> int:
    monitor.shared.dry_run = True

    async def loop() -> None:
        while True:
            try:
                await monitor.run_cycle(swap=False, notify=False)
                if demo_down:
                    monitor.inject_demo_down()
                monitor.shared.error = None
            except Exception as exc:  # noqa: BLE001
                monitor.shared.error = str(exc)
                monitor._refresh_alerts()
            interval = monitor.shared.check_interval_seconds or 30
            await asyncio.sleep(interval)

    print(f"Dry-run dashboard at http://{host}:{port} (no swaps, no Discord)")
    if demo_down:
        print("A fake down URL (http://dry-run-demo.invalid) is injected so the red banner is visible.")
    await monitor.run_cycle(swap=False, notify=False)
    if demo_down:
        monitor.inject_demo_down()
    await asyncio.gather(loop(), serve_dashboard(monitor.shared, host, port))
    return 0
