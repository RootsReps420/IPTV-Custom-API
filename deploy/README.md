# VPS operations

The live monitor runs on the Ubuntu VPS, not the Windows PC.

| | |
|---|---|
| App directory | `/home/ubuntu/iptv-monitor` |
| Process | systemd unit `iptv-monitor` (`deploy/iptv-monitor.service`) |
| Dashboard | `https://vps-4f889186.vps.ovh.net` (public standby pool). Playlists and Current DNS at `/owner` (same Caddy login). App binds `127.0.0.1:8787`. |
| Discord | Alerts, swaps, and the status-board webhook — no tunnel needed |

`systemctl enable` means it **starts on reboot**. `Restart=always` means it comes back if the process crashes.

```bash
systemctl is-enabled iptv-monitor   # enabled
systemctl is-active iptv-monitor    # active
sudo journalctl -u iptv-monitor -n 50 --no-pager
```

Do **not** also run `scripts/install-windows-task.ps1` or a second `main.py`. Two copies will fight over failovers.

## The VPS does not pull git by itself

Pushing to GitHub does nothing on the server. Someone has to copy or `git pull` on the VPS, then restart if the change was Python.

The first deploy was a file copy into `/home/ubuntu/iptv-monitor`. That folder may not be a git clone. Until it is, update by copying files (WinSCP / `pscp`) the same way.

## What is in git vs what stays on the VPS

| Path | In git? | How to update live |
|------|---------|-------------------|
| `src/`, `main.py`, `deploy/` | Yes | Copy or `git pull`, then **restart** |
| `config/settings.yaml` | Yes | Copy or `git pull`. YAML is re-read every cycle; restart anyway if unsure |
| `.env` | **No** | Edit on the VPS only |
| `config/playlists.yaml` | **No** | Edit on the VPS (or copy that file up). Reloads next cycle, no restart |
| `config/urls.yaml` | **No** | Same as playlists |

Never commit `.env`, `playlists.yaml`, or `urls.yaml`. Failover writes `current_dns` into `playlists.yaml` **on the VPS**. That is the live DNS. The copy on your PC can be stale.

## After you change code on the PC

1. Commit and push if you want GitHub as backup.
2. Get the changed files onto `/home/ubuntu/iptv-monitor` (copy, or `git pull` if that directory is a clone).
3. Restart:

```bash
cd /home/ubuntu/iptv-monitor
sudo systemctl restart iptv-monitor
systemctl is-active iptv-monitor
```

If Python dependencies changed (`pyproject.toml`), also:

```bash
cd /home/ubuntu/iptv-monitor
.venv/bin/pip install -e .
sudo systemctl restart iptv-monitor
```

## After you change playlists or standby URLs

Edit `/home/ubuntu/iptv-monitor/config/playlists.yaml` or `urls.yaml` on the VPS (nano, WinSCP, etc.). Wait one check interval. No restart.

Manual EPGenius push from the VPS:

```bash
cd /home/ubuntu/iptv-monitor
.venv/bin/python main.py apply DanMain --dns http://new-host.example --from-url http://old-host.example
```

## Dashboard in a browser (Caddy)

Caddy terminates HTTPS and proxies to `127.0.0.1:8787`. Port 8787 stays closed.

| URL | Login | What it shows |
|-----|--------|----------------|
| `https://vps-4f889186.vps.ovh.net` | none | Standby URL pool health. Safe to share. |
| `https://vps-4f889186.vps.ovh.net/owner` | username `dan` | Same page plus Current DNS, the playlists table, and manual Switch. |
| `/api/public` | none | JSON used by the public page (no live DNS, no playlist rows). |
| `/api/status` | `dan` | Full JSON including live DNS and playlists. |
| `/api/switch` | `dan` | POST `{ "playlist_id": "..." }` — immediate EPGenius swap to the best healthy standby. |

The **Playlists** button on the public page is `/owner`. The browser’s HTTP basic-auth prompt is the same login you already use. Standby hostnames in the available pool stay visible; currently-live DNS and playlist identity are hidden.

Unit: `caddy` (`deploy/Caddyfile`, `deploy/install-caddy.sh`). Auth is only on `/owner`, `/api/status`, and `/api/switch`. When you edit the Caddyfile, keep the `@owner` matcher — do not wrap the whole site in `basicauth` again.

To change the owner password, in PuTTY. Ubuntu’s Caddy 2.6.2 expects a **base64** hash, not a raw `$2a$...` line and not backslash-escaped dollars.

```bash
python3 << 'PY'
import base64, getpass, subprocess
pw = getpass.getpass("New dashboard password: ")
pw2 = getpass.getpass("Again: ")
if pw != pw2 or not pw:
    raise SystemExit("Passwords did not match")
raw = subprocess.check_output(["caddy", "hash-password", "--plaintext", pw], text=True).strip()
print("dan " + base64.b64encode(raw.encode()).decode())
PY
```

Copy the `dan JDJh...` line (no `$`, no backslashes). Then:

```bash
sudo nano /etc/caddy/Caddyfile
```

Replace the existing `dan ...` line inside `basicauth @owner` with that line. Leave the `@owner` path matcher in place. Save, then:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

```bash
sudo systemctl status caddy
sudo journalctl -u caddy -n 50 --no-pager
```

Firewall should allow **22, 80, 443** only. Do not allow 8787.

The SSH tunnel still works if Caddy is down:

```powershell
ssh -i $env:USERPROFILE\.ssh\id_ed25519_iptv_vps -N -L 8787:127.0.0.1:8787 ubuntu@198.244.234.149
```

Then `http://127.0.0.1:8787`.

## Optional: make the VPS a git clone

Only for **code**. Keep secrets untracked on the server.

```bash
# If the folder is not a clone yet, clone beside it, then move secrets across.
# If the GitHub repo is private, add a deploy key on the VPS first.

cd /home/ubuntu/iptv-monitor
git pull
sudo systemctl restart iptv-monitor
```

A private repo will not `git pull` until the VPS has a deploy key (or you keep copying files).

## SSH login (password vs key)

The `ubuntu` user already has a login password (whatever you set with `passwd` in PuTTY). That **is** the SSH password. It cannot be set from this PC without an existing login.

To change it, in PuTTY:

```bash
passwd
```

Do not paste that password into chat or into this repo.

To let this PC copy files / restart the service without a password, add an SSH **key** (preferred). On Windows PowerShell. Do **not** use `-N ""` — PowerShell strips that and ssh-keygen errors. Either press Enter twice when asked for a passphrase, or use `cmd`:

```powershell
ssh-keygen -t ed25519 -f $env:USERPROFILE\.ssh\id_ed25519_iptv_vps
Get-Content $env:USERPROFILE\.ssh\id_ed25519_iptv_vps.pub
```

On the VPS, append that one public line:

```bash
mkdir -p ~/.ssh
chmod 700 ~/.ssh
nano ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

Then test from Windows:

```powershell
ssh -i $env:USERPROFILE\.ssh\id_ed25519_iptv_vps ubuntu@YOUR_VPS_IP
```

## First install (already done on this box)

```bash
sudo cp /home/ubuntu/iptv-monitor/deploy/iptv-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now iptv-monitor
sudo ufw allow OpenSSH
sudo ufw --force enable
```

On the VPS, `config/settings.yaml` must keep `dashboard_host: 127.0.0.1`.
