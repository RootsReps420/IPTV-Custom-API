"""Owner-toggled Live TV groups for /watch.

config/watch_live_groups.yaml is the override list. Names not listed still use
the built-in Magnum filter (current /watch ON set). /owner writes this file;
/watch re-reads it by mtime, so toggles apply without a process restart.
"""

from __future__ import annotations

import logging
import re
import threading
from io import StringIO
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import DoubleQuotedScalarString

logger = logging.getLogger("iptv_monitor.player_live_groups")

_lock = threading.Lock()
# (path, mtime, {norm_name: enabled})
_cache: tuple[str, float, dict[str, bool]] | None = None

_HEADER = (
    "# Live TV groups on /watch. Edited from /owner. Reloads without a restart.\n"
    "# true = shown, false = hidden. Names not listed follow the built-in Magnum filter.\n"
)


def _yaml_rt() -> YAML:
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.default_flow_style = False
    yaml.width = 4096
    return yaml


def _yaml_safe() -> YAML:
    return YAML(typ="safe")


def norm_live_group(name: str) -> str:
    """Stable key for Magnum group-title strings (spacing / punctuation)."""
    text = (name or "").replace("\u00a0", " ")
    text = re.sub(r"[^\w|+/]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip().lower()


def _parse_groups(raw: object) -> dict[str, bool]:
    """Map display name -> enabled. Last write wins if two names share a key."""
    if not isinstance(raw, dict):
        return {}
    payload = raw.get("groups")
    out: dict[str, bool] = {}
    if isinstance(payload, dict):
        for key, value in payload.items():
            name = str(key or "").strip()
            if not name:
                continue
            out[name] = bool(value)
        return out
    if isinstance(payload, list):
        for row in payload:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or row.get("group") or "").strip()
            if not name or "enabled" not in row:
                continue
            out[name] = bool(row.get("enabled"))
    return out


def _index(groups: dict[str, bool]) -> dict[str, bool]:
    """Normalized name -> enabled."""
    indexed: dict[str, bool] = {}
    for name, enabled in groups.items():
        key = norm_live_group(name)
        if key:
            indexed[key] = enabled
    return indexed


def _load_unlocked(path: Path) -> dict[str, bool]:
    if not path.exists():
        return {}
    try:
        raw = _yaml_safe().load(path.read_text(encoding="utf-8")) or {}
    except OSError:
        logger.warning("Could not read %s", path)
        return {}
    return _parse_groups(raw)


def _cached_index(path: Path) -> dict[str, bool]:
    global _cache
    resolved = str(path)
    mtime = 0.0
    try:
        mtime = path.stat().st_mtime
    except OSError:
        pass
    hit = _cache
    if hit and hit[0] == resolved and hit[1] == mtime:
        return hit[2]
    indexed = _index(_load_unlocked(path))
    _cache = (resolved, mtime, indexed)
    return indexed


def live_group_enabled(path: Path, name: str, default: bool) -> bool:
    """YAML override for this group, else the built-in Magnum / Xtream default."""
    key = norm_live_group(name)
    if not key:
        return False
    with _lock:
        indexed = _cached_index(path)
    if key in indexed:
        return indexed[key]
    return default


def set_live_group_enabled(path: Path, name: str, enabled: bool) -> None:
    """Write one Magnum group-title as shown/hidden. Creates the file if needed."""
    display = (name or "").strip()
    key = norm_live_group(display)
    if not key:
        raise ValueError("Missing live group name")
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        groups = _load_unlocked(path)
        kept: dict[str, bool] = {}
        for existing, value in groups.items():
            if norm_live_group(existing) == key:
                continue
            kept[existing] = value
        kept[display] = bool(enabled)
        ordered = {
            DoubleQuotedScalarString(key): bool(value)
            for key, value in sorted(kept.items(), key=lambda item: item[0].lower())
        }
        tmp = path.with_name(path.name + ".tmp")
        handle = _yaml_rt()
        buf = StringIO()
        buf.write(_HEADER)
        handle.dump({"groups": ordered}, buf)
        tmp.write_text(buf.getvalue(), encoding="utf-8", newline="\n")
        tmp.replace(path)
        global _cache
        _cache = None
    logger.info("Watch live group %s -> %s", display, "on" if enabled else "off")
