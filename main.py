from pathlib import Path
import sys

src = Path(__file__).resolve().parent / "src"
sys.path.insert(0, str(src))

from iptv_monitor.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
