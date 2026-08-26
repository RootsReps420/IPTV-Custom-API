# IPTV portal monitor
#
# Overview: long-running service that health-checks IPTV portals, fails playlists
# over via EPGenius, serves a public status site + owner Switch UI + History, and
# (separately) a login-gated /watch Chromium player. Run one copy only — usually
# systemd on the OVH VPS. See deploy/README.md for production.

A long-running Python service that watches IPTV portal URLs, fails a playlist over to a healthy standby via EPGenius when the live URL dies, posts Discord alerts, and serves a local dashboard.

It is meant to run on one machine (this PC via Task Scheduler, or later a Pi / VPS). Do not run two copies at once.

## How a check cycle works

Every `check_interval_seconds` (default 10s) the monitor:

1. Reloads `config/playlists.yaml`, `config/urls.yaml`, and `config/settings.yaml`.
2. Builds two URL lists:
   - **Live** — each playlist’s `current_dns`
   - **Standby** — the shared `available` list in `urls.yaml`
3. Probes **every** unique URL the same way (live and standby).
4. Updates per-URL failure / success counters.
5. If a **live** URL has failed **3 cycles in a row**, swaps those playlists to a standby that passed **this** cycle.
6. Refreshes the dashboard snapshot. Discord fires only on state changes (down, recovered, swap, no standby, EPGenius error). If `DISCORD_WEBHOOK_STATUS` is set, one status-channel message is edited in place (no extra posts).

Changing YAML is picked up on the next cycle. Changing Python code needs a process restart (`IPTVPortalMonitor` task).

## What “healthy” means

A URL is healthy only if every **enabled** check passes. Defaults:

| Check | Default | What it actually does |
|-------|---------|------------------------|
| DNS | on | Resolve A/AAAA. Fail examples: `dns_nxdomain`, `dns_timeout`. |
| TCP | on | Connect to the portal port (80 unless the URL has a port). Fail examples: `tcp_timeout`, `tcp_refused`. |
| HTTP GET `/` | **off** | Too noisy on Xtream panels (many return odd status on `/`). |
| MPEG-TS stream | **on** | Xtream `player_api.php` then a short `GET /live/user/pass/id.ts`. Looks for MPEG-TS sync byte `0x47` / `video/mp2t`. |

These panels do **not** serve multicast UDP. Players pull **HTTP MPEG-TS**. That is what the `ts` flag on the dashboard is.

Stream-check outcomes you will see as `fail_reason`:

| Reason | Meaning |
|--------|---------|
| `stream_no_api` | `player_api.php` returned 404 — not an Xtream panel (parked domain, nginx default, etc.). |
| `stream_blocked` | API or stream returned 401/403, a Cloudflare challenge page, or non-JSON HTML instead of Xtream JSON. |
| `stream_452` | Panel returned HTTP 452/453/456/464 (blocked, geo, or DNS-locked). All channels are unusable on that host. |
| `stream_auth` | Xtream JSON came back but `user_info.auth` was not 1 for our playlist accounts. |
| `stream_no_mpegts` | Logged in, but the live path did not return MPEG-TS (placeholder `black.ts` redirects do not count). |
| `stream_timeout` / `stream_error` | Network timeout or request error talking to the API/stream. |

The stream check uses the username/password from `playlists.yaml` against **every** URL (standbys too). Same credentials, different DNS — that is how EPGenius failover works.

## Cloudflare flags

Each hostname also gets a nameserver lookup (walks `host` → parent zone for NS records) and a check of whether the resolved IP sits in [Cloudflare’s published proxy ranges](https://www.cloudflare.com/ips/).

The dashboard badge is **informational** (no top banner):

- **Cloudflare proxy** — orange-cloud / anycast IP. Last-choice swap target (most likely to block streams).
- **Cloudflare NS** — domain uses `*.ns.cloudflare.com` but the A record is origin (grey-cloud). Second-choice swap target.
- **ns aws / godaddy / …** — other DNS hosts.

This flag does not by itself mark a URL down. A Cloudflare-proxied host can still pass DNS, TCP, and HTTP MPEG-TS.

## Failover

When a live URL is unhealthy:

- **1st and 2nd** consecutive failures: wait (Discord “down” on the first transition).
- **3rd** (~30s at a 10s check interval): pick a standby that is healthy **this cycle** and is not the failed URL, in this order: no Cloudflare → Cloudflare NS only → Cloudflare proxy. Prefer standbys with at least 2 consecutive successes within that group.
- Call EPGenius `POST /api/public/update_creds` with the playlist id, new DNS, username, and password. Magnum playlists use the same call, but only onto URLs tagged `pool: magnum`.
- After a Magnum swap, write Watch’s portal DNS into `player.yaml` and refresh `/watch` so the live M3U follows the new host.
- On success, write the new URL into `playlists.yaml` `current_dns`, update the in-memory playlist, and refresh the dashboard (playlists table + Current DNS) on that same cycle.
- If no eligible standby exists, Discord gets “No healthy standby” and EPGenius is not called.

## Dashboard

On the VPS, `https://vps-4f889186.vps.ovh.net` (monitor, History, Info, Playlists) is behind the same Caddy login (`dan`) you already use for `/owner`. Friends use **`/watch`**, which stays on the Watch site login only. Locally the app is `http://127.0.0.1:8787`.

- Public: available pool cards (`dns` / `tcp` / `ts`, nameserver badge), plus standby down/up events (Caddy `dan` login on the VPS)
- Owner (`/owner`): the same, plus Current DNS, the playlists table (no passwords), a Switch button, and Switch back after a manual swap

Do not port-forward 8787 to the public internet.

## Remote status (Discord)

The local dashboard is LAN-only. For a glance from any network, add a **dedicated Discord channel** and a third webhook. The monitor keeps **one** message in that channel and **edits** it. Discord does not notify on edits, so a 15s check cycle will not spam you.

Create a channel such as `#iptv-status`, create a webhook there, and put it in `.env` as `DISCORD_WEBHOOK_STATUS`. Mute the channel if you like — you still open it when you want the board.

The embed lists playlists, live URLs, and standbys with `dns` / `tcp` / `ts` flags. It updates immediately when something actually changes (down, recovered, fail count toward swap, DNS change). If everything is stable it only refreshes the “checked … ago” line every `discord_status_min_interval_seconds` (default 60).

A slash-command bot (`/status`) would also work, but it needs a Discord application, a bot token, an invite, and a persistent gateway connection. The edited webhook message is the same data with none of that setup. Add a bot later if you want pull-on-demand without opening the channel.

Do not put this webhook in the swaps channel — the status board has no passwords, but swaps still do.

## Files

| Path | Purpose |
|------|---------|
| `.env` | EPGenius API key and Discord webhooks (swaps, alerts, optional status board). **Never commit.** |
| `config/playlists.yaml` | Accounts: Discord ID, playlist ID, username, password, live `current_dns`. **Never commit.** |
| `config/urls.yaml` | Shared standby portal URLs. **Never commit.** |
| `config/settings.yaml` | Intervals, which checks run, dashboard bind address. |
| `config/*.example.yaml` | Templates to copy on first setup. |
| `src/iptv_monitor/` | The app. |
| `logs/monitor.log` | Rotating log. |

`current_dns` must be the portal URL **as EPGenius expects it** (usually `http://host` with no `:8080` unless the panel really uses that port).

Passwords are included on the **swaps** Discord webhook on purpose. They are not shown on the dashboard.

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

Fill in `.env`, `playlists.yaml`, and `urls.yaml`. On Windows, if `python` is a Store stub, use `.\.venv\Scripts\python.exe`.

## Commands

None of the dry-run commands call EPGenius or rewrite `current_dns`.

```powershell
.\.venv\Scripts\python.exe main.py check
.\.venv\Scripts\python.exe main.py test urls
.\.venv\Scripts\python.exe main.py test failover
.\.venv\Scripts\python.exe main.py test discord
.\.venv\Scripts\python.exe main.py test dashboard
.\.venv\Scripts\python.exe main.py test dashboard --demo-down
.\.venv\Scripts\python.exe main.py apply DanMain
```

| Command | What it does |
|---------|----------------|
| `check` / `test urls` | One probe of live + standby. Prints a table and a this-cycle failover preview. |
| `test failover` | Same probes, then prints what **would** swap if the 3-failure threshold were already met. |
| `test discord` | Sends `[TEST]` messages to alerts and swaps. If a status webhook is set, posts a one-off `[TEST]` board (does not replace the live board). |
| `test dashboard` | UI with live probes, no Discord, no swaps. |
| `test dashboard --demo-down` | Same, plus a fake down URL so the red banner is visible. |
| `apply DanMain` | Push that playlist’s `current_dns` to EPGenius **and** send the Discord swap alert. Use `--dns` / `--from-url` if needed. |
| `python main.py` | **Live:** swaps and Discord are real. |
| `python main.py --no-dashboard` | Live checks without the web UI. |

`python main.py --once` is an alias for `check`.

## Keep it running on Windows

Close any other `main.py` first (port 8787 can only bind once). Then:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-windows-task.ps1
```

That registers Task Scheduler job `IPTVPortalMonitor`: starts at logon, restarts on crash, no run-time limit, uses `pythonw.exe` (no console). Logs: `logs\monitor.log`.

Remove with `scripts\uninstall-windows-task.ps1`. The PC must be on and you must be logged in; sleep still pauses it.

## Keep it running on the VPS

**This is the live monitor.** Day-to-day: updates, git vs secrets, restart rules, dashboard tunnel — see [deploy/README.md](deploy/README.md).

Short version: GitHub does **not** update the VPS. Copy or `git pull` on the server, then `sudo systemctl restart iptv-monitor` for Python changes. Playlist/URL YAML is edited on the VPS and reloads by itself. Do not run the Windows task at the same time.

Dashboard (SSH tunnel, then `http://127.0.0.1:8787`):

```powershell
ssh -L 8787:127.0.0.1:8787 ubuntu@YOUR_VPS_IP
```

## Layout of the code

| Module | Role |
|--------|------|
| `config.py` | Load settings, playlists, URLs, `.env`. Persist `current_dns` after a swap. |
| `health.py` | Per-URL DNS → TCP → optional HTTP → MPEG-TS. |
| `stream.py` | Xtream `player_api.php` + short MPEG-TS read. |
| `nameserver.py` | NS lookup and Cloudflare proxy-range detection. |
| `monitor.py` | Cycle loop, counters, failover plans, dashboard state. |
| `epgenius.py` | `update_creds` HTTP call. |
| `notify.py` | Discord webhooks. |
| `dashboard.py` | FastAPI + static UI. |
| `dryrun.py` | `check` / `test` commands. |
| `__main__.py` | CLI and logging. |
