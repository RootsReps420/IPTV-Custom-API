from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from iptv_monitor.config import load_config
from iptv_monitor.dashboard import serve_dashboard
from iptv_monitor.monitor import Monitor


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Health-check IPTV portal URLs and fail over via EPGenius."
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single observe-only cycle (no swaps, no Discord) and print a table.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Project root containing .env and config/. Defaults to the current directory.",
    )
    parser.add_argument(
        "--no-dashboard",
        action="store_true",
        help="Run the checker without the local status UI.",
    )
    return parser


async def _run(args: argparse.Namespace) -> int:
    monitor = Monitor(args.root)
    if args.once:
        await monitor.run_cycle(swap=False, notify=False)
        print(monitor.format_table())
        if monitor.shared.error:
            print(f"error: {monitor.shared.error}", file=sys.stderr)
            return 1
        return 0

    if args.no_dashboard:
        await monitor.run_forever()
        return 0

    try:
        cfg = load_config(args.root)
        host = cfg.settings.dashboard_host
        port = cfg.settings.dashboard_port
    except Exception:  # noqa: BLE001
        host, port = "127.0.0.1", 8787

    await asyncio.gather(
        monitor.run_forever(),
        serve_dashboard(monitor.shared, host, port),
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        logging.getLogger("iptv_monitor").info("Stopped")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
