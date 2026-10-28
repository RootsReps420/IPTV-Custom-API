# VPS operations

How to run, update, and debug the **live** copy. The VPS runs whatever is on GitHub `main`: push, and it deploys within about 2 minutes (see [Auto-deploy](#auto-deploy-from-main)).

Run **one** monitor. Do not also run the Windows Task Scheduler job.

| | |
|---|---|
| App directory | `/home/ubuntu/iptv-monitor` (adjust if you installed elsewhere) |
| Process | systemd unit `iptv-monitor` (`deploy/iptv-monitor.service`) |
| Dashboard | Caddy HTTPS → app on `127.0.0.1:8787` |
| Discord | Alerts, swaps, optional status-board webhook |

```bash
systemctl is-enabled iptv-monitor
systemctl is-active iptv-monitor
sudo journalctl -u iptv-monitor -n 50 --no-pager
```

`Restart=always` brings the process back after a crash or reboot.

---

## Git vs secrets

| Path | In git? | How to update live |
|------|---------|-------------------|
| `src/`, `main.py`, `pyproject.toml` | Yes | Push to `main`. Auto-deploy pulls, reinstalls if needed, restarts |
| `src/iptv_monitor/static/` | Yes | Push to `main` (bump the `?v=` cache-bust in HTML) |
| `config/settings.yaml` | Yes | Push to `main`. Keep `dashboard_host: 127.0.0.1`; the unit also pins `DASHBOARD_HOST=127.0.0.1`. |
| `deploy/*.service`, `deploy/*.timer`, `deploy/Caddyfile` | Yes | Pulled automatically but **not** installed. Copy to `/etc/systemd/system/` and `daemon-reload` by hand |
| `.env` | **No** | Edit on the server only |
| `config/playlists.yaml` | **No** | Edit on the server. Reloads next cycle. Failover rewrites `current_dns` here. |
| `config/urls.yaml` | **No** | Same as playlists |
| `config/player.yaml` | **No** | Watch portal + M3U. Magnum swaps rewrite `dns`. |
| `config/watch_users.yaml` | **No** | Watch site hashes |
| `config/watch_live_groups.yaml` | **No** | /watch Live TV group ON/OFF. Edited from `/owner`. Reloads without a restart. |
| `config/dashboard_users.yaml` | **No** | Dashboard sign-in accounts. Manage with `main.py dashboard-user` (see below). |
| `state/` | **No** | Failure history, URL history, Watch catalogue cache |
| Live `/etc/caddy/Caddyfile` | **No** | Do **not** overwrite with `deploy/Caddyfile` without keeping live hashes and hostname |

Never commit `.env`, playlists, urls, player, or watch-users YAML. The laptop copy of `playlists.yaml` can be stale.

---

## Auto-deploy from main

The app directory is a git checkout of `main`. `iptv-monitor-update.timer` runs `deploy/update.sh` every 2 minutes. When `origin/main` has moved, it:

1. Resets tracked files to `origin/main`. It never runs `git clean`, so `.env`, live config YAML, `state/` and `logs/` are untouched.
2. Runs `.venv/bin/pip install -e .` if `pyproject.toml` changed.
3. Restarts `iptv-monitor`, unless only `*.md` or `android/` changed.
4. Health check: the service stays up with no crash restarts and `/api/public` answers on `127.0.0.1:8787`. If not, it rolls back to the previous commit, restarts, and posts to the Discord alerts webhook. The failed commit is skipped until `main` moves again.

```bash
journalctl -u iptv-monitor-update -n 30 --no-pager   # recent deploys
sudo systemctl start iptv-monitor-update             # deploy now
sudo systemctl stop iptv-monitor-update.timer        # pause auto-deploy (start to resume)
```

Do not edit tracked files on the server; the next deploy overwrites them. Server-only config belongs in the gitignored files above.

---

## After you change playlists or standby URLs

Edit `config/playlists.yaml` or `config/urls.yaml` **on the server**. Wait one check cycle. No restart.

Manual EPGenius push:

```bash
cd /home/ubuntu/iptv-monitor
.venv/bin/python main.py apply account-1 --dns http://new-host.example --from-url http://old-host.example
```

Watch password hash:

```bash
cd /home/ubuntu/iptv-monitor
.venv/bin/python main.py watch-hash
# paste into config/watch_users.yaml, then restart
```

---

## Caddy

Caddy terminates HTTPS and proxies to `127.0.0.1:8787`. Port **8787 stays closed**. Firewall: **22, 80, 443** only.

`deploy/Caddyfile` is a **template**. The live file is `/etc/caddy/Caddyfile`. When you edit Caddy:

1. Caddy does **no** logins any more — the app's sign-in page does (see [Dashboard accounts](#dashboard-accounts)). Do not add `basicauth` back for dashboard paths, or people get two password prompts.
2. Do **not** gzip `/api/player/*` (live MPEG-TS will buffer).
3. Validate, then **`systemctl restart caddy`** (do not `reload` on this box — reload has taken the site down).

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl restart caddy
sudo systemctl status caddy
```

Typical access:

| Path | Login | What it shows |
|------|--------|----------------|
| `/` | Sign-in page when signed out; then owner or viewer | Standby pool, signal map, reliability |
| `/history` | Owner or viewer | 90-day history |
| `/key` `/owner` | Owner account | Legend, playlists, Switch, Watch kick |
| `/api/public` `/api/history` `/api/session` | Owner or viewer | JSON for those pages |
| `/api/status` `/api/switch` `/api/switch-back` `/api/live-groups` `/api/kick-watch` | Owner account | Full snapshot, failover, Watch live-group toggles |
| `/watch` `/api/watch/*` `/api/player/*` | Watch site cookie (separate accounts) | Player, catalogue, media proxy |
| `/healthz` `/static/*` | None | Deploy health check, CSS / JS |

Anything not listed is owner-only by default (`dash_auth.required_role`).

## Dashboard accounts

Accounts live in `config/dashboard_users.yaml` (not in git). **Owner** = everything; **viewer** = Monitor + History. Passwords are stored as hashes only.

```bash
cd /home/ubuntu/iptv-monitor
.venv/bin/python main.py dashboard-user --list
.venv/bin/python main.py dashboard-user dan --role owner      # add, or change password (prompted)
.venv/bin/python main.py dashboard-user Steve --role viewer
.venv/bin/python main.py dashboard-user Steve --remove
```

Changes apply at once, no restart: removing an account or changing its role takes effect on that person's next request. "Keep me signed in" lasts 30 days, otherwise 12 hours. After 8 wrong passwords for one name (or 10 from one IP) in 15 minutes, sign-in is locked for the rest of that window.

The first accounts (dan, Steve) were imported from the old Caddy basicauth lines, so their passwords did not change. To import again from a Caddyfile backup:

```bash
sudo cat /etc/caddy/Caddyfile.bak-basicauth | .venv/bin/python main.py dashboard-user --import-caddy -
```

If Caddy is down, an SSH tunnel still works:

```powershell
ssh -N -L 8787:127.0.0.1:8787 ubuntu@YOUR_VPS
```

Then `http://127.0.0.1:8787`.

---

## First install

```bash
git clone https://github.com/RootsReps420/IPTV-Custom-API.git /home/ubuntu/iptv-monitor
cd /home/ubuntu/iptv-monitor
python3 -m venv .venv && .venv/bin/pip install -e .
# add .env and the gitignored config YAML, then:
sudo cp deploy/iptv-monitor.service deploy/iptv-monitor-update.service deploy/iptv-monitor-update.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now iptv-monitor iptv-monitor-update.timer
sudo ufw allow OpenSSH
sudo ufw --force enable
```

The repo is public, so the clone needs no deploy key. Recreate `.venv` on the target architecture — do not copy an x86 venv onto ARM.

Caddy: prefer `apt install caddy` for the host architecture. `deploy/install-caddy.sh` is a first-boot helper with an amd64 fallback; do not run it on a live box (it would replace hashes) and do not use the amd64 deb on ARM.
