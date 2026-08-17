from __future__ import annotations

import logging
from typing import Any

import httpx

from iptv_monitor.config import Playlist, Secrets

logger = logging.getLogger("iptv_monitor.notify")

COLOR_DOWN = 0xFF5C7A
COLOR_UP = 0x3EE08F
COLOR_SWAP = 0xF5A524
COLOR_WARN = 0xF0C14A


async def _post_webhook(
    url: str,
    payload: dict[str, Any],
    timeout_seconds: float = 10,
    *,
    strict: bool = False,
) -> None:
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
) -> None:
    fields = [
        {"name": "Name", "value": playlist.name, "inline": True},
        {"name": "Playlist ID", "value": playlist.playlist_id, "inline": True},
        {"name": "Username", "value": playlist.username, "inline": True},
        {"name": "Password", "value": playlist.password, "inline": True},
        {"name": "Old URL", "value": old_url, "inline": False},
        {"name": "New URL", "value": new_url, "inline": False},
    ]
    await _post_webhook(
        secrets.discord_webhook_swaps,
        _embed(
            _title("Playlist DNS swapped", test),
            COLOR_SWAP,
            fields,
            description="Dry run. EPGenius was not called and playlist DNS was not changed." if test else None,
        ),
        strict=test,
    )
