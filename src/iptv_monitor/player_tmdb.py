"""TMDB metadata for /watch movies and series. The API key never leaves the server.

Magnum titles are messy (quality tags, dots, years). We clean them, search
TMDB, and cache poster/backdrop/plot against stream_id / series_id so the
shelf does not hit TMDB on every browse.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

import httpx

from iptv_monitor.config import resolve_paths

logger = logging.getLogger("iptv_monitor.player_tmdb")

TMDB_NAME = "watch_tmdb.json"
TMDB_API = "https://api.themoviedb.org/3"
TMDB_IMG = "https://image.tmdb.org/t/p"
NEGATIVE_TTL = 7 * 24 * 3600
SAVE_EVERY = 20
SLEEP_S = 0.35
_YEAR = re.compile(r"(?:^|[.\s(\[_])((?:19|20)\d{2})(?:[.\s)\]_]|$)")
_YEAR_PAREN = re.compile(r"\(((?:19|20)\d{2})\)")
_TAG = re.compile(
    r"\b("
    r"4k|2160p|1080p|720p|480p|hdr10|hdr|dolby|vision|dv|"
    r"hevc|x265|x264|h265|h264|10bit|8bit|"
    r"webrip|web[- ]?dl|bluray|blu[- ]?ray|remux|hdtv|pdtv|"
    r"proper|repack|extended|unrated|directors?\s*cut|"
    r"multi|aac|dts|atmos|ac3|eac3|truehd|"
    r"amzn|nf|dsnp|hulu|itunes"
    r")\b",
    re.I,
)
_SEP = re.compile(r"[._]+")
_SPACE = re.compile(r"\s+")


def tmdb_api_key() -> str:
    return (os.getenv("TMDB_API_KEY") or "").strip()


def image_url(path: object, size: str) -> str:
    raw = str(path or "").strip()
    if not raw:
        return ""
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    if not raw.startswith("/"):
        raw = f"/{raw}"
    return f"{TMDB_IMG}/{size}{raw}"


def clean_title(raw: str) -> tuple[str, int | None]:
    """Strip quality junk and pull a year if the Magnum name has one."""
    name = _SEP.sub(" ", str(raw or ""))
    year: int | None = None
    found = _YEAR_PAREN.search(name)
    if found:
        year = int(found.group(1))
        name = f"{name[: found.start()]} {name[found.end() :]}"
    else:
        found = _YEAR.search(name)
        if found:
            year = int(found.group(1))
            name = f"{name[: found.start()]} {name[found.end() :]}"
    name = _TAG.sub(" ", name)
    name = _SPACE.sub(" ", name).strip(" -|:")
    return name, year


def cache_key(kind: str, item_id: str) -> str:
    prefix = "series" if kind == "series" else "movie"
    return f"{prefix}:{str(item_id).strip()}"


def _state_path(root: Path | None) -> Path:
    folder = resolve_paths(root).root / "state"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / TMDB_NAME


def _load_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Could not read %s", path.name)
        return None


def _atomic_write_json(path: Path, payload: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
        encoding="utf-8",
    )
    tmp.replace(path)


class TmdbStore:
    def __init__(self, root: Path | None = None) -> None:
        self.path = _state_path(root)
        self.rows: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._dirty = 0
        self._enriching = False
        self.load()

    def load(self) -> None:
        raw = _load_json(self.path)
        rows = raw.get("items") if isinstance(raw, dict) else None
        if not isinstance(rows, dict):
            self.rows = {}
            return
        cleaned: dict[str, dict[str, Any]] = {}
        for key, value in rows.items():
            if isinstance(value, dict):
                cleaned[str(key)] = value
        self.rows = cleaned

    def save(self, *, force: bool = False) -> None:
        if not force and self._dirty < SAVE_EVERY:
            return
        payload = {"updated_at": time.time(), "items": self.rows}
        try:
            _atomic_write_json(self.path, payload)
            self._dirty = 0
        except Exception:
            logger.warning("Could not write %s", self.path.name)

    def get(self, kind: str, item_id: str) -> dict[str, Any] | None:
        row = self.rows.get(cache_key(kind, item_id))
        return dict(row) if row else None

    def put(self, kind: str, item_id: str, row: dict[str, Any]) -> None:
        self.put_raw(cache_key(kind, item_id), row)

    def put_raw(self, key: str, row: dict[str, Any]) -> None:
        with self._lock:
            self.rows[str(key)] = row
            self._dirty += 1
            self.save()

    def needs_fetch(self, kind: str, item_id: str) -> bool:
        row = self.rows.get(cache_key(kind, item_id))
        if not row:
            return True
        if row.get("matched"):
            return False
        checked = float(row.get("checked_at") or 0)
        return checked <= 0 or (time.time() - checked) >= NEGATIVE_TTL

    def paint(self, item: dict[str, Any], kind: str) -> dict[str, Any]:
        """Copy Magnum row and overlay cached TMDB art/text."""
        out = dict(item)
        sid = str(out.get("series_id") if kind == "series" else out.get("stream_id") or "")
        meta = self.get(kind, sid) if sid else None
        poster = str(out.get("stream_icon") or out.get("cover") or out.get("cover_big") or "")
        backdrop = ""
        raw_bd = out.get("backdrop_path")
        if isinstance(raw_bd, list) and raw_bd:
            backdrop = str(raw_bd[0] or "")
        elif raw_bd:
            backdrop = str(raw_bd)
        backdrop = backdrop or str(out.get("cover_big") or "")
        title = str(out.get("name") or "")
        year = _year_from_item(out)
        plot = str(out.get("plot") or "")
        rating = out.get("rating")
        if meta and meta.get("matched"):
            poster = str(meta.get("poster") or "") or poster
            backdrop = str(meta.get("backdrop") or "") or backdrop
            title = str(meta.get("title") or "") or title
            year = meta.get("year") if meta.get("year") else year
            plot = str(meta.get("plot") or "") or plot
            if meta.get("rating") not in (None, ""):
                rating = meta.get("rating")
            out["tmdb_id"] = meta.get("tmdb_id")
            out["tmdb"] = True
        else:
            out["tmdb"] = False
        out["display_name"] = title
        out["poster"] = poster
        out["backdrop"] = backdrop
        out["year"] = year
        if plot:
            out["plot"] = plot
        if rating not in (None, ""):
            out["tmdb_rating"] = rating
        return out

    def lookup(self, kind: str, name: str, api_key: str) -> dict[str, Any]:
        query, year = clean_title(name)
        now = time.time()
        empty = {
            "matched": False,
            "tmdb_id": None,
            "title": query,
            "year": year,
            "plot": "",
            "rating": None,
            "poster": "",
            "backdrop": "",
            "checked_at": now,
        }
        if not api_key or len(query) < 2:
            return empty
        endpoint = "search/tv" if kind == "series" else "search/movie"
        params: dict[str, str | int] = {
            "api_key": api_key,
            "query": query,
            "include_adult": "false",
        }
        if year:
            params["first_air_date_year" if kind == "series" else "year"] = year
        try:
            with httpx.Client(timeout=12.0, follow_redirects=True) as client:
                response = client.get(f"{TMDB_API}/{endpoint}", params=params)
                if response.status_code >= 400:
                    logger.warning("TMDB %s HTTP %s", endpoint, response.status_code)
                    return empty
                payload = response.json()
        except Exception as exc:
            logger.debug("TMDB lookup failed for %s: %s", query, exc)
            return empty
        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, list) or not results:
            return empty
        picked = _pick_result(results, year, kind)
        if not picked:
            return empty
        date_key = "first_air_date" if kind == "series" else "release_date"
        date = str(picked.get(date_key) or "")
        found_year = int(date[:4]) if len(date) >= 4 and date[:4].isdigit() else year
        return {
            "matched": True,
            "tmdb_id": picked.get("id"),
            "title": picked.get("name") if kind == "series" else picked.get("title"),
            "year": found_year,
            "plot": str(picked.get("overview") or "").strip(),
            "rating": picked.get("vote_average"),
            "poster": image_url(picked.get("poster_path"), "w342"),
            "backdrop": image_url(picked.get("backdrop_path"), "w1280"),
            "checked_at": now,
        }

    def details_lookup(self, kind: str, tmdb_id: object, api_key: str) -> dict[str, Any]:
        """Genres, runtime, cast photos, directors. Cached after the first open."""
        tid = str(tmdb_id or "").strip()
        empty: dict[str, Any] = {
            "genres": [],
            "runtime": None,
            "status": "",
            "countries": [],
            "cast": [],
            "directors": [],
            "writers": [],
            "creators": [],
        }
        if not api_key or not tid:
            return empty
        media = "tv" if kind == "series" else "movie"
        cache_id = f"details:{media}:{tid}"
        cached = self.rows.get(cache_id)
        if isinstance(cached, dict) and cached.get("matched"):
            return {key: cached.get(key, empty[key]) for key in empty}
        try:
            with httpx.Client(timeout=12.0, follow_redirects=True) as client:
                response = client.get(
                    f"{TMDB_API}/{media}/{tid}",
                    params={"api_key": api_key, "append_to_response": "credits"},
                )
                if response.status_code >= 400:
                    self.put_raw(cache_id, {**empty, "matched": False, "checked_at": time.time()})
                    return empty
                payload = response.json()
        except Exception as exc:
            logger.debug("TMDB details lookup failed for %s %s: %s", media, tid, exc)
            return empty
        if not isinstance(payload, dict):
            return empty
        credits = payload.get("credits") if isinstance(payload.get("credits"), dict) else {}
        cast_in = credits.get("cast") if isinstance(credits.get("cast"), list) else []
        crew_in = credits.get("crew") if isinstance(credits.get("crew"), list) else []
        cast: list[dict[str, Any]] = []
        for row in cast_in[:14]:
            if not isinstance(row, dict) or not row.get("name"):
                continue
            cast.append(
                {
                    "id": row.get("id"),
                    "name": str(row.get("name") or "").strip(),
                    "character": str(row.get("character") or "").strip(),
                    "photo": image_url(row.get("profile_path"), "w185"),
                }
            )
        directors = _crew_names(crew_in, {"director"})
        writers = _crew_names(crew_in, {"writer", "screenplay", "novel", "story"})
        creators: list[str] = []
        for row in payload.get("created_by") or []:
            if isinstance(row, dict) and row.get("name"):
                creators.append(str(row["name"]).strip())
        genres = [
            str(row.get("name") or "").strip()
            for row in (payload.get("genres") or [])
            if isinstance(row, dict) and row.get("name")
        ]
        runtime = payload.get("runtime")
        if kind == "series":
            runtimes = payload.get("episode_run_time")
            if isinstance(runtimes, list) and runtimes:
                runtime = runtimes[0]
        countries: list[str] = []
        prod = payload.get("production_countries")
        if isinstance(prod, list):
            for row in prod:
                if isinstance(row, dict) and row.get("name"):
                    countries.append(str(row["name"]).strip())
        if not countries:
            origin = payload.get("origin_country")
            if isinstance(origin, list):
                countries = [str(code).strip() for code in origin if code]
        out = {
            "matched": True,
            "genres": genres,
            "runtime": runtime,
            "status": str(payload.get("status") or "").strip(),
            "countries": [row for row in countries if row],
            "cast": cast,
            "directors": directors,
            "writers": writers,
            "creators": creators,
            "checked_at": time.time(),
        }
        self.put_raw(cache_id, out)
        self.save(force=True)
        return {key: out.get(key, empty[key]) for key in empty}

    def season_lookup(self, tmdb_id: object, season: object, api_key: str) -> dict[str, dict[str, Any]]:
        """Episode stills/plots for one season. Cached so opening a show is cheap after the first hit."""
        tid = str(tmdb_id or "").strip()
        sid = str(season or "").strip()
        if not api_key or not tid or not sid:
            return {}
        cache_id = f"tvseason:{tid}:{sid}"
        cached = self.rows.get(cache_id)
        if isinstance(cached, dict) and cached.get("matched") and isinstance(cached.get("episodes"), dict):
            return dict(cached["episodes"])
        empty: dict[str, dict[str, Any]] = {}
        try:
            with httpx.Client(timeout=12.0, follow_redirects=True) as client:
                response = client.get(
                    f"{TMDB_API}/tv/{tid}/season/{sid}",
                    params={"api_key": api_key},
                )
                if response.status_code >= 400:
                    self.put_raw(cache_id, {"matched": False, "episodes": {}, "checked_at": time.time()})
                    return empty
                payload = response.json()
        except Exception as exc:
            logger.debug("TMDB season lookup failed for %s S%s: %s", tid, sid, exc)
            return empty
        rows = payload.get("episodes") if isinstance(payload, dict) else None
        episodes: dict[str, dict[str, Any]] = {}
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                num = row.get("episode_number")
                if num is None:
                    continue
                episodes[str(num)] = {
                    "still": image_url(row.get("still_path"), "w500"),
                    "title": str(row.get("name") or "").strip(),
                    "plot": str(row.get("overview") or "").strip(),
                    "rating": row.get("vote_average"),
                    "air_date": str(row.get("air_date") or ""),
                }
        self.put_raw(
            cache_id,
            {"matched": True, "episodes": episodes, "checked_at": time.time()},
        )
        self.save(force=True)
        return episodes

    def schedule(self, guide, api_key: str) -> None:
        if not api_key or self._enriching:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self.enrich(guide, api_key), name="watch-tmdb-enrich")

    async def enrich(self, guide, api_key: str) -> None:
        if not api_key or self._enriching:
            return
        self._enriching = True
        try:
            jobs = _pending_jobs(guide, self)
            if not jobs:
                return
            logger.info("TMDB enricher: %s titles to match", len(jobs))
            done = 0
            for kind, item_id, name in jobs:
                if not tmdb_api_key():
                    break
                if not self.needs_fetch(kind, item_id):
                    continue
                row = await asyncio.to_thread(self.lookup, kind, name, api_key)
                self.put(kind, item_id, row)
                done += 1
                if done % 50 == 0:
                    logger.info("TMDB enricher: %s/%s", done, len(jobs))
                await asyncio.sleep(SLEEP_S)
            self.save(force=True)
            logger.info("TMDB enricher finished (%s looked up)", done)
        except Exception:
            logger.exception("TMDB enricher failed")
            self.save(force=True)
        finally:
            self._enriching = False


def _year_from_item(item: dict[str, Any]) -> int | None:
    for key in ("year", "releasedate", "releaseDate", "release_date"):
        raw = str(item.get(key) or "")
        found = re.search(r"((?:19|20)\d{2})", raw)
        if found:
            return int(found.group(1))
    _title, year = clean_title(str(item.get("name") or ""))
    return year


def _crew_names(rows: list[Any], jobs: set[str]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        job = str(row.get("job") or "").strip().lower()
        name = str(row.get("name") or "").strip()
        if job not in jobs or not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names[:8]


def _pick_result(results: list[Any], year: int | None, kind: str) -> dict[str, Any] | None:
    date_key = "first_air_date" if kind == "series" else "release_date"
    rows = [row for row in results if isinstance(row, dict)]
    if not rows:
        return None
    if year:
        for row in rows[:8]:
            date = str(row.get(date_key) or "")
            if date.startswith(str(year)):
                return row
    return rows[0]


def _pending_jobs(guide, store: TmdbStore) -> list[tuple[str, str, str]]:
    jobs: list[tuple[str, str, str]] = []
    for item in getattr(guide.vod, "items", []) or []:
        sid = str(item.get("stream_id") or "").strip()
        name = str(item.get("name") or "").strip()
        if sid and name and store.needs_fetch("movie", sid):
            jobs.append(("movie", sid, name))
    for item in getattr(guide.series, "items", []) or []:
        sid = str(item.get("series_id") or "").strip()
        name = str(item.get("name") or "").strip()
        if sid and name and store.needs_fetch("series", sid):
            jobs.append(("series", sid, name))
    return jobs
