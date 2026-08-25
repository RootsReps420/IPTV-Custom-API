"""Shared live channel + EPG store for /watch.

Background sync writes state/watch_live.json and state/watch_epg.json.
All site users read this; category clicks do not hit the panel.
Now/next is computed at read time from the XMLTV window.
"""

from __future__ import annotations

import base64
import html
import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from iptv_monitor.config import resolve_paths

logger = logging.getLogger("iptv_monitor.player_guide")

LIVE_NAME = "watch_live.json"
VOD_NAME = "watch_vod.json"
SERIES_NAME = "watch_series.json"
EPG_NAME = "watch_epg.json"
META_NAME = "watch_sync.json"
_B64 = re.compile(r"^[A-Za-z0-9+/]{8,}={0,2}$")
_NOT_ALNUM = re.compile(r"[^a-z0-9]+")
_UK_GROUP = re.compile(r"^uk\s*\|", re.I)
_ARABIC_SCRIPT = re.compile(r"[\u0600-\u06FF]")
_SKIP_LIBRARY = re.compile(
    r"("
    r"\b(mena|osn|turkish|turksih|turkce|turk|arabic|hindi|urdu|farsi|persian|kurdish)\b"
    r"|netflix\s*asia"
    r"|disney\+?\s*asia"
    r"|arab(?:ic)?[\s\-_/]*audio"
    r"|audio[\s\-_/]*arab(?:ic)?"
    r")",
    re.I,
)


def is_uk_live_group(name: str) -> bool:
    """Live groups we sync: panel names like 'UK| Sky Sports'. US/IE/4K/PPV-without-UK are out."""
    return bool(_UK_GROUP.match((name or "").strip()))


def is_wanted_library_group(name: str) -> bool:
    """Movies/Shows: English/Western catalogues. No Arabic/Turkish/MENA, Netflix/Disney+ Asia, or Arabic audio."""
    text = (name or "").strip()
    if not text:
        return False
    if _ARABIC_SCRIPT.search(text):
        return False
    if _SKIP_LIBRARY.search(text):
        return False
    return True


_SEARCH_SPLIT = re.compile(r"[^a-z0-9]+")
_SEARCH_STOP = frozenset({"a", "an", "the", "of", "and", "or", "to", "in", "on"})
_SEARCH_NUM = {
    "1": "one",
    "2": "two",
    "3": "three",
    "4": "four",
    "5": "five",
    "6": "six",
    "7": "seven",
    "8": "eight",
    "9": "nine",
    "10": "ten",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
}


def search_norm(value: str) -> str:
    return _SEARCH_SPLIT.sub(" ", (value or "").lower()).strip()


def search_tokens(value: str) -> list[str]:
    tokens = [part for part in search_norm(value).split() if part]
    useful = [part for part in tokens if part not in _SEARCH_STOP]
    return useful or tokens


def _expand_tokens(tokens: list[str]) -> set[str]:
    out = set(tokens)
    for token in tokens:
        mapped = _SEARCH_NUM.get(token)
        if mapped:
            out.add(mapped)
    return out


def _name_for_match(name: str) -> str:
    text = search_norm(name)
    if text.startswith("uk "):
        text = text[3:]
    return text


def score_search(query: str, name: str, extras: list[str]) -> tuple[int, str]:
    """Rank a title. Higher is better; 0 means no match. extras are plot/genre/EPG/group."""
    q_tokens = search_tokens(query)
    if not q_tokens:
        return 0, ""
    q_norm = " ".join(q_tokens)
    q_compact = "".join(q_tokens)
    q_exp = _expand_tokens(q_tokens)
    name_n = _name_for_match(name)
    name_c = name_n.replace(" ", "")
    name_set = set(name_n.split())
    if not name_n and not any(extras):
        return 0, ""
    if name_n == q_norm:
        return 100, "Title"
    if name_n.startswith(q_norm):
        return 94, "Title"
    if q_compact and len(q_compact) >= 2 and q_compact in name_c:
        return 90, "Title"
    if q_exp <= name_set or all(token in name_n for token in q_tokens):
        return 84, "Title"
    if any(token in name_set for token in q_exp if len(token) >= 2):
        return 76 if len(q_tokens) == 1 else 58, "Title"
    extra_bits = [search_norm(item) for item in extras if item]
    extra_n = " ".join(extra_bits)
    extra_c = extra_n.replace(" ", "")
    extra_set = set(extra_n.split())
    if not extra_n:
        return 0, ""
    if q_compact and len(q_compact) >= 3 and q_compact in extra_c:
        return 42, "Details"
    if all(token in extra_n for token in q_tokens):
        return 38, "Details"
    if any(token in extra_set for token in q_exp if len(token) >= 3):
        return 24, "Details"
    return 0, ""


def listings_to_guide_rows(listings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Xtream get_short_epg rows → the start/stop/title shape decorate() expects."""
    rows: list[dict[str, Any]] = []
    for item in listings:
        if not isinstance(item, dict):
            continue
        start = item.get("start_timestamp")
        if start in (None, "", 0, "0"):
            start = item.get("start")
        stop = item.get("stop_timestamp")
        if stop in (None, "", 0, "0"):
            stop = item.get("end") or item.get("stop")
        try:
            start_i = int(float(str(start)))
            stop_i = int(float(str(stop)))
        except (TypeError, ValueError):
            continue
        if stop_i <= start_i:
            continue
        rows.append(
            {
                "start": start_i,
                "stop": stop_i,
                "title": decode_xtream_text(str(item.get("title") or "")),
                "desc": decode_xtream_text(str(item.get("description") or item.get("desc") or ""))[:400],
            }
        )
    rows.sort(key=lambda row: int(row["start"]))
    return rows


def norm_epg_key(value: str) -> str:
    """Collapse XMLTV ids, display-names, and stream names for matching."""
    return _NOT_ALNUM.sub("", (value or "").lower())


def epg_alias_keys(raw: str) -> list[str]:
    """Variants: full id, id without a trailing .uk/.com-style suffix."""
    text = (raw or "").strip()
    if not text:
        return []
    keys = [norm_epg_key(text)]
    if "." in text:
        keys.append(norm_epg_key(text.rsplit(".", 1)[0]))
    return [key for key in keys if key]


def decode_xtream_text(value: str | None) -> str:
    """Xtream XMLTV titles/descriptions are often base64. Plain text is left as-is."""
    raw = html.unescape((value or "").strip())
    if not raw or not _B64.match(raw):
        return raw
    try:
        pad = "=" * ((4 - len(raw) % 4) % 4)
        out = base64.b64decode(raw + pad).decode("utf-8")
    except Exception:
        return raw
    if not out or "\x00" in out:
        return raw
    return html.unescape(out).strip() or raw


def _state_dir(root: Path | None) -> Path:
    path = resolve_paths(root).root / "state"
    path.mkdir(parents=True, exist_ok=True)
    return path


def atomic_write_json(path: Path, payload: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def load_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Could not read %s", path.name)
        return None


def category_ids_of(stream: dict[str, Any]) -> list[str]:
    """Xtream may send category_id as int, string, CSV, or category_ids list."""
    raw = stream.get("category_ids")
    if isinstance(raw, list) and raw:
        return [str(item).strip() for item in raw if str(item).strip()]
    raw = stream.get("category_id")
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    text = str(raw or "").strip()
    if not text:
        return []
    if "," in text:
        return [part.strip() for part in text.split(",") if part.strip()]
    return [text]


@dataclass
class GuideData:
    categories: list[dict[str, Any]] = field(default_factory=list)
    streams: list[dict[str, Any]] = field(default_factory=list)
    by_cat: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    by_id: dict[str, dict[str, Any]] = field(default_factory=dict)
    epg: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)
    updated_at: float = 0.0
    epg_updated_at: float = 0.0


def index_items(
    items: list[dict[str, Any]], id_key: str
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]]]:
    by_cat: dict[str, list[dict[str, Any]]] = {}
    by_id: dict[str, dict[str, Any]] = {}
    for item in items:
        sid = str(item.get(id_key) or "").strip()
        if sid:
            by_id[sid] = item
        for cid in category_ids_of(item):
            by_cat.setdefault(cid, []).append(item)
    return by_cat, by_id


def index_streams(streams: list[dict[str, Any]]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]]]:
    return index_items(streams, "stream_id")


@dataclass
class ItemLibrary:
    categories: list[dict[str, Any]] = field(default_factory=list)
    items: list[dict[str, Any]] = field(default_factory=list)
    by_cat: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    by_id: dict[str, dict[str, Any]] = field(default_factory=dict)
    updated_at: float = 0.0


def with_counts(categories: list[dict[str, Any]], by_cat: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in categories:
        item = dict(row)
        cid = str(item.get("category_id") or "")
        item["stream_count"] = len(by_cat.get(cid, []))
        out.append(item)
    return out


class WatchGuide:
    """In-memory snapshot of the last successful live + EPG sync."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root
        self.data = GuideData()
        self.running = False
        self.progress = ""
        self.last_error = ""
        self.interval_seconds = 14400
        self.library_interval_seconds = 28800
        self.vod = ItemLibrary()
        self.series = ItemLibrary()
        self._lock = threading.Lock()
        self.sync_started_at = 0.0
        self.phase = ""
        self.phase_started_at = 0.0
        self.phase_done = 0
        self.phase_total = 0
        self.phase_item = ""
        self.inflight: list[str] = []
        self.epg_bytes = 0
        self.epg_size = 0
        self._finished_phases: set[str] = set()
        self._last_meta = 0.0
        self.load_disk()

    def paths(self) -> tuple[Path, Path, Path, Path, Path]:
        folder = _state_dir(self.root)
        return (
            folder / LIVE_NAME,
            folder / VOD_NAME,
            folder / SERIES_NAME,
            folder / EPG_NAME,
            folder / META_NAME,
        )

    def _load_library(self, path: Path, id_key: str) -> ItemLibrary:
        raw = load_json(path)
        lib = ItemLibrary()
        if not isinstance(raw, dict):
            return lib
        lib.categories = [row for row in (raw.get("categories") or []) if isinstance(row, dict)]
        lib.items = [row for row in (raw.get("items") or raw.get("streams") or raw.get("series") or []) if isinstance(row, dict)]
        lib.updated_at = float(raw.get("updated_at") or 0)
        lib.by_cat, lib.by_id = index_items(lib.items, id_key)
        lib.categories = with_counts(lib.categories, lib.by_cat)
        return lib

    def load_disk(self) -> None:
        live_path, vod_path, series_path, epg_path, _meta = self.paths()
        live = load_json(live_path)
        epg_raw = load_json(epg_path)
        streams: list[dict[str, Any]] = []
        categories: list[dict[str, Any]] = []
        updated = 0.0
        if isinstance(live, dict):
            categories = [row for row in (live.get("categories") or []) if isinstance(row, dict)]
            streams = [row for row in (live.get("streams") or []) if isinstance(row, dict)]
            updated = float(live.get("updated_at") or 0)
        epg: dict[str, list[dict[str, Any]]] = {}
        aliases: dict[str, str] = {}
        epg_updated = 0.0
        if isinstance(epg_raw, dict):
            epg_updated = float(epg_raw.get("updated_at") or 0)
            channels = epg_raw.get("channels") or {}
            if isinstance(channels, dict):
                for key, rows in channels.items():
                    if not isinstance(rows, list):
                        continue
                    cleaned = [row for row in rows if isinstance(row, dict) and "start" in row]
                    if cleaned:
                        epg[str(key)] = cleaned
            raw_alias = epg_raw.get("aliases") or {}
            if isinstance(raw_alias, dict):
                aliases = {
                    str(key): str(val)
                    for key, val in raw_alias.items()
                    if str(key).strip() and str(val).strip()
                }
        by_cat, by_id = index_streams(streams)
        self.data = GuideData(
            categories=with_counts(categories, by_cat),
            streams=streams,
            by_cat=by_cat,
            by_id=by_id,
            epg=epg,
            aliases=aliases,
            updated_at=updated,
            epg_updated_at=epg_updated,
        )
        self.link_stream_aliases(persist=False)
        self.vod = self._load_library(vod_path, "stream_id")
        self.series = self._load_library(series_path, "series_id")
        logger.info(
            "Watch guide loaded: %s live, %s movies, %s series, %s EPG channels",
            len(self.data.streams),
            len(self.vod.items),
            len(self.series.items),
            len(self.data.epg),
        )

    def replace_live(self, categories: list[dict[str, Any]], streams: list[dict[str, Any]]) -> None:
        by_cat, by_id = index_streams(streams)
        now = time.time()
        self.data = GuideData(
            categories=with_counts(categories, by_cat),
            streams=streams,
            by_cat=by_cat,
            by_id=by_id,
            epg=self.data.epg,
            aliases=self.data.aliases,
            updated_at=now,
            epg_updated_at=self.data.epg_updated_at,
        )
        self.link_stream_aliases(persist=True)
        live_path, _vod, _series, _epg, _meta = self.paths()
        atomic_write_json(
            live_path,
            {"updated_at": now, "categories": self.data.categories, "streams": streams},
        )

    def _replace_library(
        self, lib: ItemLibrary, path: Path, categories: list[dict[str, Any]], items: list[dict[str, Any]], id_key: str
    ) -> ItemLibrary:
        now = time.time()
        by_cat, by_id = index_items(items, id_key)
        lib = ItemLibrary(
            categories=with_counts(categories, by_cat),
            items=items,
            by_cat=by_cat,
            by_id=by_id,
            updated_at=now,
        )
        atomic_write_json(
            path,
            {"updated_at": now, "categories": lib.categories, "items": items},
        )
        return lib

    def replace_vod(self, categories: list[dict[str, Any]], items: list[dict[str, Any]]) -> None:
        _live, vod_path, _series, _epg, _meta = self.paths()
        self.vod = self._replace_library(self.vod, vod_path, categories, items, "stream_id")

    def replace_series(self, categories: list[dict[str, Any]], items: list[dict[str, Any]]) -> None:
        _live, _vod, series_path, _epg, _meta = self.paths()
        self.series = self._replace_library(self.series, series_path, categories, items, "series_id")

    def replace_epg(
        self,
        channels: dict[str, list[dict[str, Any]]],
        aliases: dict[str, str] | None = None,
    ) -> None:
        now = time.time()
        self.data.epg = channels
        if aliases is not None:
            self.data.aliases = dict(aliases)
        self.data.epg_updated_at = now
        self.link_stream_aliases(persist=True)

    def ingest_short_epg(self, stream: dict[str, Any], rows: list[dict[str, Any]], *, persist: bool = False) -> None:
        """Store now/next for one live stream from get_short_epg (no xmltv.php)."""
        sid = str(stream.get("stream_id") or "").strip()
        if not sid or not rows:
            return
        epg_id = str(stream.get("epg_channel_id") or "").strip()
        with self._lock:
            self.data.epg[sid] = rows
            if epg_id:
                self.data.epg.setdefault(epg_id, rows)
            for raw in (sid, epg_id, str(stream.get("name") or "").strip()):
                for key in epg_alias_keys(raw):
                    self.data.aliases.setdefault(key, sid)
            self.data.epg_updated_at = time.time()
        if persist:
            self._write_epg()

    def persist_epg(self) -> None:
        if self.data.epg_updated_at:
            self._write_epg()

    def _write_epg(self) -> None:
        _live, _vod, _series, epg_path, _meta = self.paths()
        atomic_write_json(
            epg_path,
            {
                "updated_at": self.data.epg_updated_at,
                "channels": self.data.epg,
                "aliases": self.data.aliases,
            },
        )

    def link_stream_aliases(self, *, persist: bool) -> None:
        """Map stream names / epg_channel_id / stream_id onto XMLTV channel ids."""
        if not self.data.epg:
            return
        aliases = dict(self.data.aliases)
        for stream in self.data.streams:
            candidates = [
                str(stream.get("epg_channel_id") or "").strip(),
                str(stream.get("stream_id") or "").strip(),
                str(stream.get("name") or "").strip(),
            ]
            canon = None
            for cand in candidates:
                if not cand:
                    continue
                if cand in self.data.epg or cand.lower() in self.data.epg:
                    canon = cand if cand in self.data.epg else cand.lower()
                    break
                mapped = aliases.get(norm_epg_key(cand))
                if mapped and (mapped in self.data.epg or mapped.lower() in self.data.epg):
                    canon = mapped if mapped in self.data.epg else mapped.lower()
                    break
            if not canon:
                continue
            for cand in candidates:
                for key in epg_alias_keys(cand):
                    aliases.setdefault(key, canon)
        self.data.aliases = aliases
        if persist and self.data.epg_updated_at:
            self._write_epg()

    def write_meta(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_meta < 1.0:
            return
        self._last_meta = now
        *_rest, meta_path = self.paths()
        atomic_write_json(meta_path, self.status())

    def begin_sync(self) -> None:
        with self._lock:
            self.running = True
            self.sync_started_at = time.time()
            self.phase = ""
            self.phase_started_at = 0.0
            self.phase_done = 0
            self.phase_total = 0
            self.phase_item = ""
            self.inflight = []
            self.epg_bytes = 0
            self.epg_size = 0
            self._finished_phases = set()
            self.last_error = ""
            self.progress = "Starting guide sync…"
        self.write_meta(force=True)

    def finish_sync(self) -> None:
        with self._lock:
            self.running = False
            self.progress = ""
            self.phase = ""
            self.phase_item = ""
            self.inflight = []
        self.write_meta(force=True)

    def set_phase(self, phase: str, *, message: str = "", total: int = 0, item: str = "") -> None:
        with self._lock:
            if self.phase and self.phase != phase:
                self._finished_phases.add(self.phase)
            self.phase = phase
            self.phase_started_at = time.time()
            self.phase_done = 0
            self.phase_total = total
            self.phase_item = item
            self.inflight = []
            if phase != "epg":
                self.epg_bytes = 0
                self.epg_size = 0
            self.progress = message or self._progress_line_unlocked()
        self.write_meta(force=True)

    def group_start(self, name: str, phase: str, total: int) -> None:
        label = (name or "").strip()
        with self._lock:
            if label and label not in self.inflight:
                self.inflight.append(label)
            self.phase = phase
            self.phase_total = total
            self.phase_item = label
            self.progress = self._progress_line_unlocked()
        self.write_meta()

    def group_done(self, name: str, done: int, total: int, phase: str) -> None:
        label = (name or "").strip()
        with self._lock:
            self.inflight = [item for item in self.inflight if item != label]
            self.phase = phase
            self.phase_done = done
            self.phase_total = total
            self.progress = self._progress_line_unlocked()
        self.write_meta()

    def set_epg_bytes(self, written: int, total: int = 0) -> None:
        with self._lock:
            self.epg_bytes = max(0, int(written))
            if total:
                self.epg_size = max(0, int(total))
            self.progress = self._progress_line_unlocked()
        self.write_meta()

    def note(self, item: str, message: str | None = None) -> None:
        with self._lock:
            self.phase_item = (item or "").strip()
            self.progress = message or self._progress_line_unlocked()
        self.write_meta(force=True)

    def _progress_line_unlocked(self) -> str:
        phase = self.phase or "sync"
        if phase in {"live", "movies", "series"}:
            label = {"live": "Live", "movies": "Movies", "series": "Shows"}[phase]
            counts = f"{self.phase_done}/{self.phase_total} groups" if self.phase_total else label
            current = ", ".join(self.inflight[-4:]) or self.phase_item
            if current:
                return f"{label} {counts} · {current}"
            return f"{label} {counts}"
        if phase == "epg":
            if self.phase_total:
                counts = f"{self.phase_done}/{self.phase_total} channels"
                current = self.phase_item
                if current:
                    return f"EPG {counts} · {current}"
                return f"EPG {counts}"
            if self.phase_item:
                return self.phase_item
            mb = self.epg_bytes / 1_000_000
            if self.epg_size:
                return f"EPG {mb:.1f}/{self.epg_size / 1_000_000:.1f} MB"
            if self.epg_bytes:
                return f"EPG {mb:.1f} MB downloaded"
            return "Downloading EPG…"
        return self.progress or "Syncing…"

    def _fraction_unlocked(self) -> float:
        weights = {"live": 0.35, "movies": 0.25, "series": 0.20, "epg": 0.20}
        done_w = sum(weights[name] for name in self._finished_phases if name in weights)
        if self.phase in weights:
            frac = 0.0
            if self.phase_total > 0:
                frac = self.phase_done / self.phase_total
            elif self.phase == "epg":
                if self.epg_size > 0 and self.epg_bytes:
                    frac = min(0.95, self.epg_bytes / self.epg_size)
                elif self.epg_bytes > 0:
                    frac = min(0.7, 0.12 + self.epg_bytes / 80_000_000)
            done_w += weights[self.phase] * frac
        return min(0.99, max(0.0, done_w))

    def _eta_unlocked(self) -> int | None:
        if not self.running or not self.phase_started_at:
            return None
        phase_elapsed = max(0.1, time.time() - self.phase_started_at)
        remain: float | None = None
        if self.phase in {"live", "movies", "series", "epg"}:
            if self.phase_done >= 2 and self.phase_total:
                rate = phase_elapsed / self.phase_done
                remain = max(0.0, (self.phase_total - self.phase_done) * rate)
        if remain is None:
            return None
        hints = {"movies": 240, "series": 240, "epg": 180}
        seen = False
        extra = 0
        for name in ("live", "movies", "series", "epg"):
            if name == self.phase:
                seen = True
                continue
            if seen:
                extra += hints.get(name, 120)
        return min(int(remain + extra), 4 * 3600)

    def has_live(self) -> bool:
        return bool(self.data.streams)

    def age_seconds(self) -> float | None:
        if not self.data.updated_at:
            return None
        return max(0.0, time.time() - self.data.updated_at)

    def library_age_seconds(self, lib: ItemLibrary) -> float | None:
        if not lib.items or not lib.updated_at:
            return None
        return max(0.0, time.time() - lib.updated_at)

    def status(self) -> dict[str, Any]:
        age = self.age_seconds()
        last_ok = None
        if self.data.updated_at:
            last_ok = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.data.updated_at))
        with self._lock:
            elapsed = None
            if self.running and self.sync_started_at:
                elapsed = int(max(0, time.time() - self.sync_started_at))
            percent = int(round(self._fraction_unlocked() * 100)) if self.running else None
            eta = self._eta_unlocked() if self.running else None
            return {
                "ready": self.has_live(),
                "running": self.running,
                "progress": self.progress,
                "phase": self.phase or None,
                "phase_done": self.phase_done,
                "phase_total": self.phase_total,
                "phase_item": self.phase_item or None,
                "inflight": list(self.inflight),
                "elapsed_seconds": elapsed,
                "eta_seconds": eta,
                "percent": percent,
                "epg_bytes": self.epg_bytes,
                "last_ok": last_ok,
                "age_seconds": None if age is None else int(age),
                "categories": len(self.data.categories),
                "streams": len(self.data.streams),
                "movies": len(self.vod.items),
                "series": len(self.series.items),
                "epg_channels": len(self.data.epg),
                "interval_seconds": int(self.interval_seconds),
                "library_interval_seconds": int(self.library_interval_seconds),
                "last_error": self.last_error or None,
            }

    def live_categories(self) -> list[dict[str, Any]] | None:
        if not self.has_live():
            return None
        return [
            row
            for row in self.data.categories
            if is_uk_live_group(str(row.get("category_name") or ""))
        ]

    def live_streams(self, category_id: str) -> list[dict[str, Any]] | None:
        if not self.has_live():
            return None
        cid = str(category_id or "").strip()
        if not cid:
            return []
        cat = next(
            (
                row
                for row in self.data.categories
                if str(row.get("category_id") or "") == cid
            ),
            None,
        )
        if not cat or not is_uk_live_group(str(cat.get("category_name") or "")):
            return []
        rows = self.data.by_cat.get(cid, [])
        return [self.decorate(stream) for stream in rows]

    def _library_categories(self, lib: ItemLibrary) -> list[dict[str, Any]] | None:
        if not lib.items:
            return None
        return [
            row
            for row in lib.categories
            if is_wanted_library_group(str(row.get("category_name") or ""))
        ]

    def _library_items(self, lib: ItemLibrary, category_id: str) -> list[dict[str, Any]] | None:
        if not lib.items:
            return None
        cid = str(category_id or "").strip()
        if not cid:
            return []
        cat = next(
            (row for row in lib.categories if str(row.get("category_id") or "") == cid),
            None,
        )
        if not cat or not is_wanted_library_group(str(cat.get("category_name") or "")):
            return []
        return list(lib.by_cat.get(cid, []))

    def vod_categories(self) -> list[dict[str, Any]] | None:
        return self._library_categories(self.vod)

    def vod_streams(self, category_id: str) -> list[dict[str, Any]] | None:
        return self._library_items(self.vod, category_id)

    def series_categories(self) -> list[dict[str, Any]] | None:
        return self._library_categories(self.series)

    def series_list(self, category_id: str) -> list[dict[str, Any]] | None:
        return self._library_items(self.series, category_id)

    def decorate(self, stream: dict[str, Any]) -> dict[str, Any]:
        out = dict(stream)
        current, nxt = self.now_next_for_stream(out)
        title = (current or {}).get("title") or ""
        if not title:
            extra = decode_xtream_text(str(out.get("title") or ""))
            name = str(out.get("name") or "").strip()
            if extra and extra.lower() != name.lower():
                title = extra
        out["now_title"] = title
        out["next_title"] = (nxt or {}).get("title") or ""
        if current:
            if current.get("start"):
                out["now_start"] = current["start"]
            if current.get("stop"):
                out["now_stop"] = current["stop"]
            if current.get("desc"):
                out["now_desc"] = current["desc"]
        return out

    def now_next_for_stream(
        self, stream: dict[str, Any], now: int | None = None
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        rows = self._epg_rows_for_stream(stream)
        if not rows:
            return None, None
        current, nxt = self._now_next_from_rows(rows, now)
        if current:
            return current, nxt
        stamp = int(now or time.time())
        rest: list[dict[str, Any]] = []
        for row in rows:
            try:
                if int(row["stop"]) > stamp:
                    rest.append(row)
            except (KeyError, TypeError, ValueError):
                continue
        if not rest:
            return None, None
        return rest[0], rest[1] if len(rest) > 1 else None

    def now_next(self, epg_id: str, now: int | None = None) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        rows = self._epg_rows(epg_id)
        if not rows:
            return None, None
        return self._now_next_from_rows(rows, now)

    def _epg_rows_for_stream(self, stream: dict[str, Any]) -> list[dict[str, Any]] | None:
        return self._epg_rows(
            str(stream.get("epg_channel_id") or ""),
            str(stream.get("stream_id") or ""),
            str(stream.get("name") or ""),
        )

    def _epg_rows(self, *keys: str) -> list[dict[str, Any]] | None:
        for raw in keys:
            key = str(raw or "").strip()
            if not key:
                continue
            rows = self.data.epg.get(key) or self.data.epg.get(key.lower())
            if rows:
                return rows
            mapped = self.data.aliases.get(norm_epg_key(key))
            if not mapped and "." in key:
                mapped = self.data.aliases.get(norm_epg_key(key.rsplit(".", 1)[0]))
            if mapped:
                rows = self.data.epg.get(mapped) or self.data.epg.get(mapped.lower())
                if rows:
                    return rows
        return None

    def _now_next_from_rows(
        self, rows: list[dict[str, Any]], now: int | None = None
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        stamp = int(now or time.time())
        current = None
        nxt = None
        for row in rows:
            try:
                start = int(row["start"])
                stop = int(row["stop"])
            except (KeyError, TypeError, ValueError):
                continue
            if start <= stamp < stop:
                current = row
            elif start >= stamp:
                nxt = row
                break
        return current, nxt

    def listings_for_stream(self, stream_id: str, *, limit: int = 8) -> list[dict[str, Any]] | None:
        if not self.data.epg:
            return None
        stream = self.data.by_id.get(str(stream_id).strip())
        if not stream:
            return None
        rows = self._epg_rows_for_stream(stream)
        if not rows:
            return None
        stamp = int(time.time()) - 60
        out: list[dict[str, Any]] = []
        for row in rows:
            try:
                stop = int(row["stop"])
                start = int(row["start"])
            except (KeyError, TypeError, ValueError):
                continue
            if stop <= stamp:
                continue
            out.append(
                {
                    "title": row.get("title") or "",
                    "description": row.get("desc") or "",
                    "start_timestamp": start,
                    "stop_timestamp": stop,
                    "start": start,
                    "end": stop,
                }
            )
            if len(out) >= limit:
                break
        return out or None

    def _category_names(self, categories: list[dict[str, Any]]) -> dict[str, str]:
        return {
            str(row.get("category_id") or ""): str(row.get("category_name") or "").strip()
            for row in categories
            if str(row.get("category_id") or "").strip()
        }

    def _group_label(self, item: dict[str, Any], names: dict[str, str]) -> str:
        labels: list[str] = []
        for cid in category_ids_of(item):
            label = names.get(cid)
            if label and label not in labels:
                labels.append(label)
        return labels[0] if labels else ""

    def _take_hits(
        self, ranked: list[tuple[int, str, dict[str, Any]]], limit: int
    ) -> list[dict[str, Any]]:
        ranked.sort(key=lambda row: (-row[0], row[1]))
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for _score, key, item in ranked:
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
            if len(out) >= limit:
                break
        return out

    def search(self, query: str, *, per_kind: int = 40) -> dict[str, Any]:
        """Live + movies + shows. Ranked; does not hit the panel."""
        text = (query or "").strip()
        live_names = self._category_names(self.data.categories)
        vod_names = self._category_names(self.vod.categories)
        series_names = self._category_names(self.series.categories)
        live_hits: list[tuple[int, str, dict[str, Any]]] = []
        movie_hits: list[tuple[int, str, dict[str, Any]]] = []
        series_hits: list[tuple[int, str, dict[str, Any]]] = []
        if len(text) < 2:
            return {"query": text, "live": [], "movies": [], "series": []}

        for stream in self.data.streams:
            decorated = self.decorate(stream)
            group = self._group_label(stream, live_names)
            score, why = score_search(
                text,
                str(decorated.get("name") or ""),
                [
                    str(decorated.get("now_title") or ""),
                    str(decorated.get("next_title") or ""),
                    group,
                ],
            )
            if score <= 0:
                continue
            sid = str(stream.get("stream_id") or "")
            if why == "Details" and decorated.get("now_title"):
                match = str(decorated.get("now_title") or "")
            else:
                match = group or why
            live_hits.append(
                (
                    score,
                    str(decorated.get("name") or "").lower(),
                    {
                        "kind": "live",
                        "stream_id": sid,
                        "name": decorated.get("name") or "",
                        "stream_icon": decorated.get("stream_icon") or "",
                        "num": decorated.get("num"),
                        "now_title": decorated.get("now_title") or "",
                        "next_title": decorated.get("next_title") or "",
                        "now_start": decorated.get("now_start"),
                        "now_stop": decorated.get("now_stop"),
                        "category_name": group,
                        "match": match,
                    },
                )
            )

        for item in self.vod.items:
            group = self._group_label(item, vod_names)
            name = str(item.get("name") or "")
            plot = str(item.get("plot") or "")[:240]
            genre = str(item.get("genre") or "")
            score, why = score_search(text, name, [plot, genre, group, str(item.get("director") or "")])
            if score <= 0:
                continue
            sid = str(item.get("stream_id") or "")
            match = group or genre or why
            if why == "Details" and plot:
                match = plot[:90]
            movie_hits.append(
                (
                    score,
                    name.lower(),
                    {
                        "kind": "movie",
                        "stream_id": sid,
                        "name": name,
                        "stream_icon": item.get("stream_icon") or item.get("cover_big") or "",
                        "container_extension": item.get("container_extension") or "mp4",
                        "plot": plot,
                        "genre": genre,
                        "category_name": group,
                        "match": match,
                    },
                )
            )

        for item in self.series.items:
            group = self._group_label(item, series_names)
            name = str(item.get("name") or "")
            plot = str(item.get("plot") or "")[:240]
            genre = str(item.get("genre") or "")
            score, why = score_search(
                text,
                name,
                [plot, genre, group, str(item.get("cast") or ""), str(item.get("director") or "")],
            )
            if score <= 0:
                continue
            sid = str(item.get("series_id") or "")
            match = group or genre or why
            if why == "Details" and plot:
                match = plot[:90]
            series_hits.append(
                (
                    score,
                    name.lower(),
                    {
                        "kind": "series",
                        "series_id": sid,
                        "name": name,
                        "cover": item.get("cover") or "",
                        "plot": plot,
                        "genre": genre,
                        "category_name": group,
                        "match": match,
                    },
                )
            )

        return {
            "query": text,
            "live": self._take_hits(live_hits, per_kind),
            "movies": self._take_hits(movie_hits, per_kind),
            "series": self._take_hits(series_hits, per_kind),
        }
