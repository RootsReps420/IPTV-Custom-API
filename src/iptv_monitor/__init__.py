"""IPTV portal health monitor, EPGenius failover, public dashboard, and /watch player.

This package is the whole service:
- monitor.py probes live + standby URLs and swaps playlists when a live host dies
- dashboard.py serves the public status site, owner Switch UI, History, and Watch
Watch uses a dedicated Xtream account (config/player.yaml). Magnum playlist
failover updates that DNS so /watch follows the new Magnum host.
The VPS runs GitHub main: deploy/update.sh pulls, restarts, and health-checks it.
"""

__version__ = "0.1.0"
