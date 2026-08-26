"""Dry-run commands: probe URLs, preview failover, test Discord, run the UI with swaps off."""

from __future__ import annotations

import asyncio
from pathlib import Path

from iptv_monitor.config import load_config, normalize_pool, update_player_dns, update_playlist_dns
from iptv_monitor.dashboard import serve_dashboard
from iptv_monitor.epgenius import update_creds
from iptv_monitor.health import normalize_url
from iptv_monitor.monitor import Monitor
from iptv_monitor.notify import notify_no_standby, notify_swap, notify_url_down, notify_url_up, publish_status_board


async def run_url_check(monitor: Monitor) -> int:
    """One cycle, print the table. No EPGenius, no Discord."""
    monitor.shared.dry_run = True
    await monitor.run_cycle(swap=False, notify=False)
    print(monitor.format_table())
    print()
    print("Failover preview for this cycle (needs 3 consecutive failures to swap; no API calls):")
    print(monitor.format_failover_preview())
    return 0


async def run_failover_preview(monitor: Monitor) -> int:
    """Show what would swap if the 3-failure threshold were already met."""
    monitor.shared.dry_run = True
    await monitor.run_cycle(swap=False, notify=False)
    print(monitor.format_table())
    print()
    print("Simulated failover if the failure threshold were already met (no EPGenius, no Discord, no file writes):")
    plans = monitor.simulated_failover_plans()
    print(monitor.format_failover_preview(plans))
    return 0


async def run_discord_test(root: Path | None) -> int:
    """Send [TEST] webhook payloads. Never calls EPGenius."""
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
    if cfg.secrets.discord_webhook_status:
        snapshot = {
            "last_cycle_at": None,
            "check_interval_seconds": cfg.settings.check_interval_seconds,
            "live": [
                {
                    "url": live,
                    "healthy": True,
                    "dns_ok": True,
                    "tcp_ok": True,
                    "stream_ok": True,
                    "fail_reason": None,
                    "consecutive_successes": 2,
                    "consecutive_failures": 0,
                    "cloudflare_proxied": False,
                    "cloudflare": False,
                    "nameserver": None,
                }
            ],
            "available": [
                {
                    "url": standby,
                    "healthy": False,
                    "dns_ok": True,
                    "tcp_ok": True,
                    "stream_ok": False,
                    "fail_reason": "demo_forced_down",
                    "consecutive_successes": 0,
                    "consecutive_failures": 1,
                    "cloudflare_proxied": False,
                    "cloudflare": False,
                    "nameserver": None,
                }
            ],
            "playlists": [
                {
                    "name": playlist.name,
                    "playlist_id": playlist.playlist_id,
                    "current_dns": live,
                    "healthy": True,
                    "cloudflare_proxied": False,
                    "cloudflare": False,
                    "nameserver": None,
                }
            ],
            "counts": {"live_up": 1, "live_total": 1, "available_up": 0, "available_total": 1},
            "error": None,
        }
        await publish_status_board(
            cfg.secrets,
            snapshot,
            root=cfg.paths.root,
            test=True,
            persist=False,
        )
        print("  status: posted a [TEST] board message (does not replace the live board)")
    else:
        print("  status: skipped (DISCORD_WEBHOOK_STATUS not set)")
    print("Done. Check the Discord channels for messages titled [TEST].")
    return 0


def _find_playlist(cfg, selector: str):
    sel = selector.strip().lower()
    hits = [
        item
        for item in cfg.playlists
        if sel == str(item.playlist_id).lower() or sel in item.name.lower()
    ]
    if not hits:
        names = ", ".join(f"{item.name} ({item.playlist_id})" for item in cfg.playlists) or "(none)"
        raise RuntimeError(f"No playlist matched {selector!r}. Loaded: {names}")
    if len(hits) > 1:
        names = ", ".join(f"{item.name} ({item.playlist_id})" for item in hits)
        raise RuntimeError(f"{selector!r} matched more than one playlist: {names}")
    return hits[0]


async def run_apply(
    root: Path | None,
    selector: str,
    *,
    dns: str | None = None,
    from_url: str | None = None,
) -> int:
    """Push a playlist DNS to EPGenius and send the same Discord swap alert as automatic failover."""
    cfg = load_config(root)
    playlist = _find_playlist(cfg, selector)
    old_url = normalize_url(from_url or playlist.current_dns)
    new_url = normalize_url(dns or playlist.current_dns)
    print(f"Applying {playlist.name} ({playlist.playlist_id})")
    print(f"  {old_url} -> {new_url}")
    await update_creds(cfg.secrets, playlist, new_url)
    update_playlist_dns(cfg.paths.playlists, playlist.playlist_id, new_url)
    if normalize_pool(playlist.pool) == "magnum":
        update_player_dns(cfg.paths.player, new_url)
        from iptv_monitor.player_sync import queue_watch_force

        queue_watch_force(root, "playlist")
    await notify_swap(cfg.secrets, playlist, old_url, new_url, manual=True)
    print("EPGenius accepted. Discord swap alert sent.")
    return 0


async def run_dashboard_test(
    monitor: Monitor,
    *,
    demo_down: bool,
    host: str,
    port: int,
) -> int:
    """Serve the UI with dry_run on so Switch / EPGenius cannot fire."""
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
    await asyncio.gather(loop(), serve_dashboard(monitor, host, port))
    return 0
