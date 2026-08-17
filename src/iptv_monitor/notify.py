"""Discord webhooks: alerts, swaps, and an optional one-message status board.

Swap messages include username/password on purpose. Test sends are prefixed [TEST]
and never call EPGenius.

The status board (DISCORD_WEBHOOK_STATUS) is a single embed that is edited in
place. Discord does not notify on edits, so a 15s check cycle will not spam.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from iptv_monitor.config import AppConfig, Playlist, Secrets

logger = logging.getLogger("iptv_monitor.notify")

COLOR_DOWN = 0xFF5C7A
COLOR_UP = 0x3EE08F
COLOR_SWAP = 0xF5A524
COLOR_WARN = 0xF0C14A

_FIELD_LIMIT = 1024
_STATUS_STATE = Path("state") / "discord_status.json"


async def _post_webhook(
    url: str,
    payload: dict[str, Any],
    timeout_seconds: float = 10,
    *,
    strict: bool = False,
) -> None:
    """Live alerts log a warning on failure; `test discord` raises so you notice."""
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(url, json=payload)
        if not response.is_success:
            message = f"Discord webhook HTTP {response.status_code}: {response.text[:300]}"
            logger.warning(message)
            if strict:
                raise RuntimeError(message)
    except httpx.RequestError as exc:
        logger.warning("Discord webhook request failed: %s", exc)
        if strict:
            raise RuntimeError(f"Discord webhook request failed: {exc}") from exc


def _title(base: str, test: bool) -> str:
    return f"[TEST] {base}" if test else base


def _embed(
    title: str,
    color: int,
    fields: list[dict[str, Any]],
    description: str | None = None,
) -> dict[str, Any]:
    embed: dict[str, Any] = {"title": title, "color": color, "fields": fields}
    if description:
        embed["description"] = description
    return {"embeds": [embed]}


async def notify_url_down(
    secrets: Secrets,
    url: str,
    role: str,
    fail_reason: str | None,
    detail: str | None = None,
    *,
    test: bool = False,
) -> None:
    fields = [
        {"name": "URL", "value": url, "inline": False},
        {"name": "Pool", "value": role, "inline": True},
        {"name": "Reason", "value": fail_reason or "unknown", "inline": True},
    ]
    if detail:
        fields.append({"name": "Detail", "value": detail[:1000], "inline": False})
    await _post_webhook(
        secrets.discord_webhook_alerts,
        _embed(
            _title("Portal URL down", test),
            COLOR_DOWN,
            fields,
            description="Dry run. No failover or EPGenius call." if test else None,
        ),
        strict=test,
    )


async def notify_url_up(secrets: Secrets, url: str, role: str, *, test: bool = False) -> None:
    fields = [
        {"name": "URL", "value": url, "inline": False},
        {"name": "Pool", "value": role, "inline": True},
    ]
    await _post_webhook(
        secrets.discord_webhook_alerts,
        _embed(
            _title("Portal URL recovered", test),
            COLOR_UP,
            fields,
            description="Dry run. Status only." if test else None,
        ),
        strict=test,
    )


async def notify_no_standby(
    secrets: Secrets,
    failed_url: str,
    playlists: list[Playlist],
    *,
    test: bool = False,
) -> None:
    names = ", ".join(item.name for item in playlists) or "(none)"
    fields = [
        {"name": "Failed URL", "value": failed_url, "inline": False},
        {"name": "Affected playlists", "value": names, "inline": False},
    ]
    await _post_webhook(
        secrets.discord_webhook_alerts,
        _embed(
            _title("No healthy standby", test),
            COLOR_WARN,
            fields,
            description="Dry run. EPGenius was not called." if test else "Live URL is dead and no available URL passed this cycle. EPGenius was not called.",
        ),
        strict=test,
    )


async def notify_epgenius_error(
    secrets: Secrets,
    playlist: Playlist,
    old_url: str,
    new_url: str,
    error: str,
    *,
    test: bool = False,
) -> None:
    fields = [
        {"name": "Playlist", "value": playlist.name, "inline": True},
        {"name": "Playlist ID", "value": playlist.playlist_id, "inline": True},
        {"name": "Old URL", "value": old_url, "inline": False},
        {"name": "Attempted URL", "value": new_url, "inline": False},
        {"name": "Error", "value": error[:1000], "inline": False},
    ]
    await _post_webhook(
        secrets.discord_webhook_alerts,
        _embed(_title("EPGenius update failed", test), COLOR_DOWN, fields),
        strict=test,
    )


async def notify_swap(
    secrets: Secrets,
    playlist: Playlist,
    old_url: str,
    new_url: str,
    *,
    test: bool = False,
    manual: bool = False,
) -> None:
    fields = [
        {"name": "Name", "value": playlist.name, "inline": True},
        {"name": "Playlist ID", "value": playlist.playlist_id, "inline": True},
        {"name": "Username", "value": playlist.username, "inline": True},
        {"name": "Password", "value": playlist.password, "inline": True},
        {"name": "Old URL", "value": old_url, "inline": False},
        {"name": "New URL", "value": new_url, "inline": False},
    ]
    if test:
        description = "Dry run. EPGenius was not called and playlist DNS was not changed."
    elif manual:
        description = "Manual apply — EPGenius was updated outside automatic failover."
    else:
        description = None
    await _post_webhook(
        secrets.discord_webhook_swaps,
        _embed(
            _title("Playlist DNS swapped", test),
            COLOR_SWAP,
            fields,
            description=description,
        ),
        strict=test,
    )


def _flag_token(label: str, ok: bool | None) -> str:
    if ok is None:
        return f"{label}—"
    return f"{label} ok" if ok else f"{label} FAIL"


def _host_label(url: str) -> str:
    text = (url or "").strip()
    for prefix in ("https://", "http://"):
        if text.lower().startswith(prefix):
            text = text[len(prefix) :]
            break
    return text.rstrip("/") or url


def _ns_tag(row: dict[str, Any]) -> str:
    if row.get("cloudflare_proxied"):
        return "CF proxy"
    if row.get("cloudflare"):
        return "CF NS"
    nameserver = row.get("nameserver")
    return f"ns {nameserver}" if nameserver else ""


def _url_line(row: dict[str, Any]) -> str:
    mark = "✅" if row.get("healthy") else "❌"
    flags = " · ".join(
        [
            _flag_token("dns", row.get("dns_ok")),
            _flag_token("tcp", row.get("tcp_ok")),
            _flag_token("ts", row.get("stream_ok")),
        ]
    )
    bits = [f"{mark} `{_host_label(str(row.get('url') or ''))}`", flags]
    ns = _ns_tag(row)
    if ns:
        bits.append(ns)
    if row.get("healthy"):
        bits.append(f"pass {row.get('consecutive_successes') or 0}")
    else:
        reason = row.get("fail_reason") or "unknown"
        bits.append(f"{reason} · fails {row.get('consecutive_failures') or 0}")
    return " · ".join(bits)


def _playlist_line(row: dict[str, Any]) -> str:
    mark = "✅" if row.get("healthy") else "❌"
    name = row.get("name") or row.get("playlist_id") or "playlist"
    dns = _host_label(str(row.get("current_dns") or ""))
    ns = _ns_tag(row)
    extra = f" · {ns}" if ns else ""
    return f"{mark} **{name}** → `{dns}`{extra}"


def _chunk_field(name: str, lines: list[str]) -> list[dict[str, Any]]:
    if not lines:
        return [{"name": name, "value": "(none)", "inline": False}]
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in lines:
        extra = len(line) + (1 if current else 0)
        if current and size + extra > _FIELD_LIMIT:
            chunks.append("\n".join(current))
            current = [line]
            size = len(line)
        else:
            current.append(line)
            size += extra
    if current:
        chunks.append("\n".join(current))
    fields = []
    for index, chunk in enumerate(chunks):
        label = name if index == 0 else f"{name} (cont.)"
        fields.append({"name": label, "value": chunk[:_FIELD_LIMIT], "inline": False})
    return fields


def _discord_relative(iso: str | None) -> str:
    if not iso:
        return "waiting for first check"
    try:
        stamp = datetime.fromisoformat(iso)
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return f"<t:{int(stamp.timestamp())}:R>"
    except ValueError:
        return iso


def _status_color(snapshot: dict[str, Any]) -> int:
    live = snapshot.get("live") or []
    available = snapshot.get("available") or []
    if any(not row.get("healthy") for row in live):
        return COLOR_DOWN
    if snapshot.get("error") or any(not row.get("healthy") for row in available):
        return COLOR_WARN
    return COLOR_UP


def _status_fingerprint(snapshot: dict[str, Any]) -> str:
    """Ignore pass-count and timestamps so a healthy board is not edited every cycle."""
    parts: list[str] = [str(snapshot.get("error") or "")]
    for row in snapshot.get("playlists") or []:
        parts.append(
            f"p|{row.get('playlist_id')}|{row.get('current_dns')}|{int(bool(row.get('healthy')))}"
        )
    for prefix, key in (("L", "live"), ("A", "available")):
        for row in snapshot.get(key) or []:
            parts.append(
                f"{prefix}|{row.get('url')}|{int(bool(row.get('healthy')))}|"
                f"{row.get('fail_reason')}|{row.get('dns_ok')}|{row.get('tcp_ok')}|"
                f"{row.get('stream_ok')}|{row.get('consecutive_failures')}|"
                f"{int(bool(row.get('cloudflare_proxied')))}|{int(bool(row.get('cloudflare')))}"
            )
    return "\n".join(parts)


def build_status_payload(snapshot: dict[str, Any], *, test: bool = False) -> dict[str, Any]:
    counts = snapshot.get("counts") or {}
    live_up = counts.get("live_up", 0)
    live_total = counts.get("live_total", 0)
    avail_up = counts.get("available_up", 0)
    avail_total = counts.get("available_total", 0)
    checked = _discord_relative(snapshot.get("last_cycle_at"))
    interval = snapshot.get("check_interval_seconds") or 30
    description = (
        f"Live **{live_up}/{live_total}** · Standby **{avail_up}/{avail_total}** · "
        f"checked {checked} · probes every {interval}s"
    )
    if snapshot.get("error"):
        description += f"\nMonitor error: {snapshot['error']}"[:400]
    fields: list[dict[str, Any]] = []
    fields.extend(
        _chunk_field("Playlists", [_playlist_line(row) for row in snapshot.get("playlists") or []])
    )
    fields.extend(_chunk_field("Live URLs", [_url_line(row) for row in snapshot.get("live") or []]))
    fields.extend(
        _chunk_field("Standby URLs", [_url_line(row) for row in snapshot.get("available") or []])
    )
    payload = _embed(
        _title("Portal status", test),
        _status_color(snapshot),
        fields[:25],
        description=description,
    )
    payload["username"] = "IPTV status"
    payload["allowed_mentions"] = {"parse": []}
    return payload


def _webhook_id(url: str) -> str:
    path = urlparse(url).path.rstrip("/").split("/")
    try:
        index = path.index("webhooks")
        return path[index + 1]
    except (ValueError, IndexError):
        return "unknown"


def _status_state_path(root: Path) -> Path:
    return root / _STATUS_STATE


def _load_status_message_id(path: Path, webhook_id: str) -> str | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if str(data.get("webhook_id") or "") != webhook_id:
        return None
    message_id = str(data.get("message_id") or "").strip()
    return message_id or None


def _save_status_message_id(path: Path, webhook_id: str, message_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"webhook_id": webhook_id, "message_id": message_id}, indent=2) + "\n",
        encoding="utf-8",
    )


async def _webhook_json(
    url: str,
    payload: dict[str, Any],
    *,
    method: str = "POST",
    params: dict[str, str] | None = None,
    timeout_seconds: float = 10,
    strict: bool = False,
) -> httpx.Response | None:
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.request(method, url, json=payload, params=params)
        if not response.is_success:
            message = f"Discord webhook HTTP {response.status_code}: {response.text[:300]}"
            logger.warning(message)
            if strict:
                raise RuntimeError(message)
            return response
        return response
    except httpx.RequestError as exc:
        logger.warning("Discord webhook request failed: %s", exc)
        if strict:
            raise RuntimeError(f"Discord webhook request failed: {exc}") from exc
        return None


async def publish_status_board(
    secrets: Secrets,
    snapshot: dict[str, Any],
    *,
    root: Path,
    test: bool = False,
    persist: bool = True,
) -> bool:
    """Create or edit the single status-channel embed. Returns True if Discord accepted it."""
    webhook = secrets.discord_webhook_status
    if not webhook:
        return False
    payload = build_status_payload(snapshot, test=test)
    webhook_id = _webhook_id(webhook)
    state_path = _status_state_path(root)
    message_id = _load_status_message_id(state_path, webhook_id) if persist and not test else None

    if message_id:
        target = f"{webhook.rstrip('/')}/messages/{message_id}"
        response = await _webhook_json(target, payload, method="PATCH", strict=test)
        if response is not None and response.is_success:
            return True
        if response is not None and response.status_code != 404:
            return False
        logger.info("Discord status message missing; posting a new one")

    response = await _webhook_json(webhook, payload, params={"wait": "true"}, strict=test)
    if response is None or not response.is_success:
        return False
    if persist and not test:
        try:
            new_id = str(response.json().get("id") or "").strip()
        except json.JSONDecodeError:
            new_id = ""
        if new_id:
            _save_status_message_id(state_path, webhook_id, new_id)
    return True


class DiscordStatusBoard:
    """Throttle status-board edits: immediate on health change, otherwise on an interval."""

    def __init__(self) -> None:
        self._last_fingerprint: str | None = None
        self._last_sent_mono: float = 0.0
        self._logged_missing = False

    async def sync(self, cfg: AppConfig, snapshot: dict[str, Any], *, force: bool = False) -> None:
        webhook = cfg.secrets.discord_webhook_status
        if not webhook:
            if not self._logged_missing:
                logger.info(
                    "Discord status board off — set DISCORD_WEBHOOK_STATUS for a glanceable channel message"
                )
                self._logged_missing = True
            return
        fingerprint = _status_fingerprint(snapshot)
        interval = max(0, int(cfg.settings.discord_status_min_interval_seconds))
        now = time.monotonic()
        changed = fingerprint != self._last_fingerprint
        stale = (now - self._last_sent_mono) >= interval
        if not force and self._last_sent_mono and not changed and not stale:
            return
        ok = await publish_status_board(cfg.secrets, snapshot, root=cfg.paths.root)
        if ok:
            self._last_fingerprint = fingerprint
            self._last_sent_mono = now
            if changed or force:
                logger.info("Discord status board updated")
