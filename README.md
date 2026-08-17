# IPTV Custom API

Long-running monitor that health-checks IPTV portal URLs (DNS + TCP), swaps dead live URLs to a healthy standby via EPGenius `update_creds`, notifies Discord, and serves a local status dashboard.

## How it works

- **Live URLs** come from each playlist’s `current_dns` in `config/playlists.yaml`.
- **Standby URLs** come from the shared list in `config/urls.yaml`.
- Every cycle, **both** lists are probed the same way so a swap never picks a dead standby.
- A URL is **dead** if DNS resolution fails **or** TCP connect to host:port fails. HTTP `GET /` is off by default.
- After **3 consecutive** dead cycles on a live URL, playlists on that URL are updated to a standby that passed **this** cycle.
- Discord gets swap details and down/up alerts. The dashboard is the current-state view.

## Setup

Python 3.11+. From the repo root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
copy .env.example .env
copy config\playlists.example.yaml config\playlists.yaml
copy config\urls.example.yaml config\urls.yaml
```

Edit `.env` (API key and Discord webhooks), `config/playlists.yaml`, and `config/urls.yaml`. Do not commit those files.

## Run

```powershell
python main.py
```

- Dashboard: [http://127.0.0.1:8787](http://127.0.0.1:8787) (localhost only)
- One observe-only cycle (no swaps, no dashboard): `python main.py --once`
- Checker only, no UI: `python main.py --no-dashboard`

Leave example.com URLs in place only for a `--once` smoke test. A continuous run will treat those as down and can fire Discord alerts.

## Config

| File | Purpose |
|------|---------|
| `.env` | `EPGENIUS_API_KEY`, `DISCORD_WEBHOOK_SWAPS`, `DISCORD_WEBHOOK_ALERTS` |
| `config/playlists.yaml` | Per-account Discord ID, playlist ID, username, password, live DNS |
| `config/urls.yaml` | Shared standby portal URLs |
| `config/settings.yaml` | Intervals, timeouts, which checks are enabled |

Passwords are sent on the **swaps** Discord webhook as requested. They are **not** shown on the dashboard.

## Secrets

Webhook URLs and the EPGenius key are secrets. Keep them in `.env` only. Rotate webhooks if they were pasted into chat or email.
