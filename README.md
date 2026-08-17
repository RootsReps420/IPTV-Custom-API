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

## What to fill in for a dry run

`.env` is already local (API key + both Discord webhooks). You still need real portal URLs:

| File | Fields | Needed for |
|------|--------|------------|
| [`config/playlists.yaml`](config/playlists.yaml) | `name`, **`current_dns`** | URL checks, dashboard, failover preview |
| [`config/playlists.yaml`](config/playlists.yaml) | `playlist_id`, `username`, `password`, `discord_id` | `test discord` and real swaps later |
| [`config/urls.yaml`](config/urls.yaml) | `available` list of standby portal URLs | URL checks, failover preview, dashboard |

`current_dns` is the live portal URL exactly as EPGenius expects it, e.g. `http://cf.business-cdn-8k.com` (no port unless the portal actually uses a non-default one). Standby URLs in `urls.yaml` use the same shape. Leave example hosts in place only if you want to see guaranteed DNS failures.

None of the dry-run commands call EPGenius or rewrite `current_dns`.

## Dry-run commands

From the repo root, after `pip install -e .`:

```powershell
python main.py check
python main.py test urls
python main.py test failover
python main.py test discord
python main.py test dashboard
python main.py test dashboard --demo-down
```

| Command | What it does | Side effects |
|---------|----------------|--------------|
| `check` / `test urls` | DNS + TCP table for live and standby URLs, plus a this-cycle failover preview | None |
| `test failover` | Same probes, then prints what **would** swap if the 3-failure threshold were already met | None |
| `test discord` | Sends `[TEST]` messages to both webhooks (down, recovered, no standby, swap) | Discord only. No EPGenius. Swap test uses whatever username/password is in `playlists.yaml` |
| `test dashboard` | Local UI at http://127.0.0.1:8787, live probes, red banners when URLs are down | None (no Discord, no swaps) |
| `test dashboard --demo-down` | Same, plus a fake `http://dry-run-demo.invalid` live card so the down banner is visible even if every real URL is up | None |

`python main.py --once` is still an alias for `check`.

## Live run (not a dry run)

```powershell
python main.py
```

That **will** swap via EPGenius after 3 consecutive failures. Do not use it until the dry runs look right.

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
