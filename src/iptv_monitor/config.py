"""Load settings, playlists, standby URLs, Watch configs, and .env secrets.

YAML under config/ is re-read every monitor cycle (and Watch re-reads player.yaml
per request), so playlist / URL / settings edits apply without a restart.
Python code changes still need `systemctl restart iptv-monitor`.

Gitignored live files: playlists.yaml, urls.yaml, player.yaml, watch_users.yaml, .env
Examples in this folder are safe to commit.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field
from ruamel.yaml import YAML

DEFAULT_POOL = "strong8k"


def normalize_pool(value: str | None) -> str:
    """Magnum vs Strong 8K. Unknown / missing values are Strong 8K."""
    compact = "".join(ch for ch in (value or "").lower() if ch.isalnum())
    if compact == "magnum":
        return "magnum"
    return DEFAULT_POOL


def pool_label(value: str | None) -> str:
    return "Magnum" if normalize_pool(value) == "magnum" else "Strong 8K"


class Settings(BaseModel):
    """Knobs from config/settings.yaml."""

    check_interval_seconds: int = 10
    consecutive_failures_to_swap: int = 3
    # Prefer a standby that has been healthy this many cycles; otherwise any healthy one.
    min_consecutive_successes_for_swap: int = 2
    dns_check_enabled: bool = True
    tcp_check_enabled: bool = True
    http_check_enabled: bool = False
    stream_check_enabled: bool = True
    dns_timeout_seconds: float = 5
    tcp_timeout_seconds: float = 5
    http_timeout_seconds: float = 10
    stream_timeout_seconds: float = 10
    allow_insecure_tls: bool = True
    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8787
    # How often to refresh the Discord status-board timestamp when nothing changed.
    # Health changes (down/up, fail count, DNS swap) still edit immediately. 0 = every cycle.
    discord_status_min_interval_seconds: int = 60
    # Dashboard "Frequent failure" on standbys: this many separate down events in the window.
    frequent_failure_down_events: int = 3
    frequent_failure_window_hours: int = 24
    history_retention_days: int = 90
    # How often Watch re-downloads live channels + EPG into state/ (seconds).
    watch_sync_seconds: int = 14400
    # Movies/Shows catalogue. Same 4-hour cadence as live + EPG.
    watch_library_sync_seconds: int = 14400


class Playlist(BaseModel):
    """One EPGenius playlist / IPTV account."""

    name: str
    discord_id: str
    playlist_id: str
    username: str
    password: str
    current_dns: str
    # Set on a dashboard manual switch; Switch back returns here after a health check.
    manual_from_dns: str | None = None
    # False = no automatic EPGenius swap. Manual Switch is still allowed within this pool.
    failover: bool = True
    # strong8k and magnum never share standbys — different provider credentials.
    pool: str = DEFAULT_POOL


class PoolUrl(BaseModel):
    """One standby URL, tagged so Magnum and Strong 8K cannot cross-failover."""

    url: str
    pool: str = DEFAULT_POOL


class Secrets(BaseModel):
    epgenius_api_key: str
    discord_webhook_swaps: str
    discord_webhook_alerts: str
    discord_webhook_status: str | None = None
    epgenius_url: str = "https://epgenius.org/api/public/update_creds"


class Paths(BaseModel):
    root: Path
    config_dir: Path
    settings: Path
    playlists: Path
    urls: Path
    player: Path
    watch_users: Path
    env: Path


class AppConfig(BaseModel):
    paths: Paths
    settings: Settings
    secrets: Secrets
    playlists: list[Playlist]
    available_pool: list[PoolUrl] = Field(default_factory=list)

    @property
    def available_urls(self) -> list[str]:
        return [item.url for item in self.available_pool]

    def urls_in_pool(self, pool: str | None) -> list[str]:
        wanted = normalize_pool(pool)
        return [item.url for item in self.available_pool if normalize_pool(item.pool) == wanted]


def _yaml() -> YAML:
    """Round-trip YAML so we can rewrite current_dns without scrambling the file."""
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.default_flow_style = False
    return yaml


def _safe_yaml() -> YAML:
    """Load-only YAML (no round-trip). Used for settings / playlists / urls reads."""
    return YAML(typ="safe")


def resolve_paths(root: Path | None = None) -> Paths:
    """Canonical paths under the project root (cwd if root is None)."""
    base = Path(root) if root else Path.cwd()
    config_dir = base / "config"
    return Paths(
        root=base,
        config_dir=config_dir,
        settings=config_dir / "settings.yaml",
        playlists=config_dir / "playlists.yaml",
        urls=config_dir / "urls.yaml",
        player=config_dir / "player.yaml",
        watch_users=config_dir / "watch_users.yaml",
        env=base / ".env",
    )


def ensure_runtime_configs(paths: Paths) -> None:
    """On first run, copy the example playlists/urls files into the gitignored copies."""
    pairs = (
        (paths.playlists, paths.config_dir / "playlists.example.yaml"),
        (paths.urls, paths.config_dir / "urls.example.yaml"),
        (paths.player, paths.config_dir / "player.example.yaml"),
        (paths.watch_users, paths.config_dir / "watch_users.example.yaml"),
    )
    for dest, example in pairs:
        if not dest.exists() and example.exists():
            shutil.copy(example, dest)


def load_settings(path: Path) -> Settings:
    data = _safe_yaml().load(path.read_text(encoding="utf-8")) or {}
    return Settings.model_validate(data)


def load_playlists(path: Path) -> list[Playlist]:
    data = _safe_yaml().load(path.read_text(encoding="utf-8")) or {}
    raw = data.get("playlists") or []
    return [Playlist.model_validate(item) for item in raw]


def load_available_pool(path: Path) -> list[PoolUrl]:
    """Standby pool with provider tags. Plain strings default to Strong 8K."""
    data = _safe_yaml().load(path.read_text(encoding="utf-8")) or {}
    urls = data.get("available") or []
    unique: list[PoolUrl] = []
    seen: set[str] = set()
    for item in urls:
        pool = DEFAULT_POOL
        if isinstance(item, dict):
            value = str(item.get("url") or item.get("dns") or "").strip()
            pool = normalize_pool(item.get("pool") or item.get("label"))
        else:
            value = str(item).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        unique.append(PoolUrl(url=value, pool=pool))
    return unique


def load_available_urls(path: Path) -> list[str]:
    """Standby pool URLs only (order preserved)."""
    return [item.url for item in load_available_pool(path)]


def load_secrets(env_path: Path) -> Secrets:
    """Read .env. EPGenius + Discord webhooks are required; status webhook is optional."""
    load_dotenv(env_path, override=False)
    missing = [
        name
        for name in (
            "EPGENIUS_API_KEY",
            "DISCORD_WEBHOOK_SWAPS",
            "DISCORD_WEBHOOK_ALERTS",
        )
        if not os.getenv(name)
    ]
    if missing:
        joined = ", ".join(missing)
        raise RuntimeError(f"Missing environment variables in {env_path}: {joined}")
    status = os.getenv("DISCORD_WEBHOOK_STATUS", "").strip() or None
    return Secrets(
        epgenius_api_key=os.environ["EPGENIUS_API_KEY"].strip(),
        discord_webhook_swaps=os.environ["DISCORD_WEBHOOK_SWAPS"].strip(),
        discord_webhook_alerts=os.environ["DISCORD_WEBHOOK_ALERTS"].strip(),
        discord_webhook_status=status,
        epgenius_url=os.getenv(
            "EPGENIUS_URL", "https://epgenius.org/api/public/update_creds"
        ).strip(),
    )


def load_config(root: Path | None = None) -> AppConfig:
    """Full runtime config. Copies example YAML into gitignored files on first run."""
    paths = resolve_paths(root)
    if not paths.settings.exists():
        raise FileNotFoundError(f"Missing settings file: {paths.settings}")
    ensure_runtime_configs(paths)
    if not paths.playlists.exists():
        raise FileNotFoundError(f"Missing playlists file: {paths.playlists}")
    if not paths.urls.exists():
        raise FileNotFoundError(f"Missing URLs file: {paths.urls}")
    if not paths.env.exists():
        raise FileNotFoundError(f"Missing .env file: {paths.env} (copy .env.example)")
    return AppConfig(
        paths=paths,
        settings=load_settings(paths.settings),
        secrets=load_secrets(paths.env),
        playlists=load_playlists(paths.playlists),
        available_pool=load_available_pool(paths.urls),
    )


_UNSET = object()


def update_playlist_dns(
    playlists_path: Path,
    playlist_id: str,
    new_dns: str,
    *,
    manual_from_dns: str | None | object = _UNSET,
) -> None:
    """Write the new live URL into playlists.yaml after EPGenius accepts the swap."""
    yaml = _yaml()
    with playlists_path.open(encoding="utf-8") as handle:
        data = yaml.load(handle)
    found = False
    for item in data.get("playlists") or []:
        if str(item.get("playlist_id")) == str(playlist_id):
            item["current_dns"] = new_dns
            if manual_from_dns is not _UNSET:
                if manual_from_dns:
                    item["manual_from_dns"] = manual_from_dns
                else:
                    item.pop("manual_from_dns", None)
            found = True
    if not found:
        raise KeyError(f"playlist_id {playlist_id!r} not found in {playlists_path}")
    tmp = playlists_path.with_suffix(".yaml.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        yaml.dump(data, handle)
    tmp.replace(playlists_path)
