"""Repo-root entrypoint for systemd and local runs.

Puts ./src on sys.path so `python main.py` works without `pip install -e .`.
systemd ExecStart points here: /home/ubuntu/iptv-monitor/main.py
"""

from pathlib import Path
import sys

src = Path(__file__).resolve().parent / "src"
sys.path.insert(0, str(src))

from iptv_monitor.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
