"""EPGenius public update_creds call — this is the actual playlist DNS swap."""

from __future__ import annotations

import logging

import httpx

from iptv_monitor.config import Playlist, Secrets

logger = logging.getLogger("iptv_monitor.epgenius")


class EpgeniusError(Exception):
    def __init__(self, message: str, status_code: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


async def update_creds(
    secrets: Secrets,
    playlist: Playlist,
    new_dns: str,
    timeout_seconds: float = 20,
) -> None:
    headers = {
        "Authorization": secrets.epgenius_api_key,
        "X-Discord-ID": playlist.discord_id,
        "Content-Type": "application/json",
    }
    payload = {
        "playlist_id": playlist.playlist_id,
        "dns": new_dns,
        "username": playlist.username,
        "password": playlist.password,
    }
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        try:
            response = await client.post(secrets.epgenius_url, headers=headers, json=payload)
        except httpx.RequestError as exc:
            raise EpgeniusError(f"EPGenius request failed: {exc}") from exc

    if response.is_success:
        logger.info(
            "Updated EPGenius playlist %s (%s) to %s",
            playlist.name,
            playlist.playlist_id,
            new_dns,
        )
        return

    body = response.text[:500]
    raise EpgeniusError(
        f"EPGenius update_creds returned HTTP {response.status_code} for playlist {playlist.name}",
        status_code=response.status_code,
        body=body,
    )
