from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from iptv_monitor.config import load_config
from iptv_monitor.dashboard import serve_dashboard
from iptv_monitor.dryrun import (
    run_dashboard_test,
    run_discord_test,
    run_failover_preview,
    run_url_check,
)
from iptv_monitor.monitor import Monitor


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Health-check IPTV portal URLs and fail over via EPGenius."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Project root containing .env and config/. Defaults to the current directory.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Alias for 'check': one URL probe, no swaps, no Discord.",
    )
    parser.add_argument(
        "--no-dashboard",
        action="store_true",
        help="Run the live checker without the local status UI.",
    )

    sub = parser.add_subparsers(dest="command")
    sub.add_parser("check", help="Probe live and standby URLs once. No swaps, no Discord.")
    test = sub.add_parser("test", help="Dry-run a single component.")
    test.add_argument(
        "component",
        choices=["urls", "failover", "discord", "dashboard"],
        help="urls: DNS/TCP table. failover: print would-swap plan. discord: [TEST] webhooks. dashboard: local UI with down banners.",
    )
    test.add_argument(
        "--demo-down",
        action="store_true",
        help="For 'test dashboard': inject a fake down URL so the red banner is visible even if all real URLs are up.",
    )
    return parser


def _dashboard_bind(root: Path | None) -> tuple[str, int]:
    try:
        cfg = load_config(root)
        return cfg.settings.dashboard_host, cfg.settings.dashboard_port
    except Exception:  # noqa: BLE001
        return "127.0.0.1", 8787


async def _run(args: argparse.Namespace) -> int:
    root = args.root
    command = args.command
    if args.once:
        command = "check"

    monitor = Monitor(root)
    component = getattr(args, "component", None)
    demo_down = bool(getattr(args, "demo_down", False))

    if command == "check" or component == "urls":
        return await run_url_check(monitor)

    if component == "failover":
        return await run_failover_preview(monitor)

    if component == "discord":
        return await run_discord_test(root)

    if component == "dashboard":
        host, port = _dashboard_bind(root)
        return await run_dashboard_test(
            monitor,
            demo_down=demo_down,
            host=host,
            port=port,
        )

    if args.no_dashboard:
        await monitor.run_forever()
        return 0

    host, port = _dashboard_bind(root)
    await asyncio.gather(
        monitor.run_forever(),
        serve_dashboard(monitor.shared, host, port),
    )
    return 0


def configure_logging(root: Path | None) -> None:
    base = Path(root) if root else Path.cwd()
    log_dir = base / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    if root_logger.handlers:
        return
    file_handler = RotatingFileHandler(
        log_dir / "monitor.log",
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)
    if sys.stderr is not None:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        root_logger.addHandler(stream_handler)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.root)
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        logging.getLogger("iptv_monitor").info("Stopped")
        return 0
    except Exception as exc:  # noqa: BLE001
        logging.getLogger("iptv_monitor").error("%s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
