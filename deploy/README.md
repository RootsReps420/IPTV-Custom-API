# VPS operations

How to run, update, and debug the **live** copy. Git push does not update the server. Copy files, then restart if the change was Python or static assets.

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
| `src/`, `main.py`, `deploy/` | Yes | Copy or `git pull`, then **restart** |
| `src/iptv_monitor/static/` | Yes | Copy, then restart (or at least cache-bust `?v=` in HTML) |
| `config/settings.yaml` | Yes | Copy carefully. Production **must** keep `dashboard_host: 127.0.0.1`. YAML reloads each cycle. |
| `.env` | **No** | Edit on the server only |
| `config/playlists.yaml` | **No** | Edit on the server. Reloads next cycle. Failover rewrites `current_dns` here. |
| `config/urls.yaml` | **No** | Same as playlists |
| `config/player.yaml` | **No** | Watch portal + M3U. Magnum swaps rewrite `dns`. |
| `config/watch_users.yaml` | **No** | Watch site hashes |
| `config/watch_live_groups.yaml` | **No** | /watch Live TV group ON/OFF. Edited from `/owner`. Reloads without a restart. |
| `state/` | **No** | Failure history, URL history, Watch catalogue cache |
| Live `/etc/caddy/Caddyfile` | **No** | Do **not** overwrite with `deploy/Caddyfile` without keeping live hashes and hostname |

Never commit `.env`, playlists, urls, player, or watch-users YAML. The laptop copy of `playlists.yaml` can be stale.

---

## After you change code

1. Push to GitHub if you want a backup (code only).
2. Copy the changed files onto the app directory (or `git pull` if that directory is a clone).
3. Restart:

```bash
cd /home/ubuntu/iptv-monitor
sudo systemctl restart iptv-monitor
systemctl is-active iptv-monitor
```

If `pyproject.toml` changed:

```bash
cd /home/ubuntu/iptv-monitor
.venv/bin/pip install -e .
sudo systemctl restart iptv-monitor
```

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

1. Keep the live basic-auth hashes (do not paste template placeholders).
2. Keep Watch, `/api/watch/*`, `/api/player/*`, and `/static/*` **out** of basic-auth.
3. Do **not** gzip `/api/player/*` (live MPEG-TS will buffer).
4. Validate, then **`systemctl restart caddy`** (do not `reload` on this box — reload has taken the site down).

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl restart caddy
sudo systemctl status caddy
```

Typical access:

| Path | Login | What it shows |
|------|--------|----------------|
| `/` `/history` | Caddy (owner and optional read-only user) | Standby pool / 90-day history |
| `/key` `/owner` | Caddy **owner only** | Legend, playlists, Switch, Watch kick |
| `/api/public` `/api/history` | Same as `/` | JSON for those pages |
| `/api/status` `/api/switch` `/api/switch-back` `/api/live-groups` | Owner only | Full snapshot, failover, Watch live-group toggles |
| `/watch` `/api/watch/*` `/api/player/*` | Watch site cookie (not Caddy) | Player, catalogue, media proxy |

To rotate the owner password, generate a hash the way **this** Caddy build expects (Ubuntu 2.6.2 wants **base64** of the bcrypt string, not a raw `$2a$` line):

```bash
python3 << 'PY'
import base64, getpass, subprocess
pw = getpass.getpass("New dashboard password: ")
pw2 = getpass.getpass("Again: ")
if pw != pw2 or not pw:
    raise SystemExit("Passwords did not match")
raw = subprocess.check_output(["caddy", "hash-password", "--plaintext", pw], text=True).strip()
print("owner " + base64.b64encode(raw.encode()).decode())
PY
```

Put that user line inside the owner `basicauth` matcher. Leave path matchers in place.

If Caddy is down, an SSH tunnel still works:

```powershell
ssh -N -L 8787:127.0.0.1:8787 ubuntu@YOUR_VPS
```

Then `http://127.0.0.1:8787`.

---

## Optional: git clone on the server

Code only. Keep secrets untracked.

```bash
cd /home/ubuntu/iptv-monitor
git pull
sudo systemctl restart iptv-monitor
```

A private repo needs a deploy key (or keep copying files).

---

## First install

```bash
sudo cp /home/ubuntu/iptv-monitor/deploy/iptv-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now iptv-monitor
sudo ufw allow OpenSSH
sudo ufw --force enable
```

On the server, `config/settings.yaml` must keep `dashboard_host: 127.0.0.1`. Recreate `.venv` on the target architecture — do not copy an x86 venv onto ARM.

Caddy: prefer `apt install caddy` for the host architecture. `deploy/install-caddy.sh` is a first-boot helper with an amd64 fallback; do not run it on a live box (it would replace hashes) and do not use the amd64 deb on ARM.
