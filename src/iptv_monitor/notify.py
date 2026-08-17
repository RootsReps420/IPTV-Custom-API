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


async def _post_webhook(url: str, payload: dict[str, Any], timeout_seconds: float = 10) -> None:
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(url, json=payload)
        if not response.is_success:
            logger.warning("Discord webhook HTTP %s: %s", response.status_code, response.text[:300])
    except httpx.RequestError as exc:
        logger.warning("Discord webhook request failed: %s", exc)


def _embed(title: str, color: int, fields: list[dict[str, Any]], description: str | None = None) -> dict[str, Any]:
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
        _embed("Portal URL down", COLOR_DOWN, fields),
    )


async def notify_url_up(secrets: Secrets, url: str, role: str) -> None:
    fields = [
        {"name": "URL", "value": url, "inline": False},
        {"name": "Pool", "value": role, "inline": True},
    ]
    await _post_webhook(
        secrets.discord_webhook_alerts,
        _embed("Portal URL recovered", COLOR_UP, fields),
    )


async def notify_no_standby(secrets: Secrets, failed_url: str, playlists: list[Playlist]) -> None:
    names = ", ".join(item.name for item in playlists) or "(none)"
    fields = [
        {"name": "Failed URL", "value": failed_url, "inline": False},
        {"name": "Affected playlists", "value": names, "inline": False},
    ]
    await _post_webhook(
        secrets.discord_webhook_alerts,
        _embed(
            "No healthy standby",
            COLOR_WARN,
            fields,
            description="Live URL is dead and no available URL passed this cycle. EPGenius was not called.",
        ),
    )


async def notify_epgenius_error(
    secrets: Secrets,
    playlist: Playlist,
    old_url: str,
    new_url: str,
    error: str,
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
        _embed("EPGenius update failed", COLOR_DOWN, fields),
    )


async def notify_swap(
    secrets: Secrets,
    playlist: Playlist,
    old_url: str,
    new_url: str,
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
        _embed("Playlist DNS swapped", COLOR_SWAP, fields),
    )
