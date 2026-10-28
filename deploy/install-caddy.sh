#!/bin/bash
# First-time Caddy + HTTPS on the OVH VPS. Writes /etc/caddy/Caddyfile (same as deploy/Caddyfile).
# No logins in Caddy: the app's sign-in page handles the dashboard (main.py dashboard-user) and
# Watch has its own login. Do not re-run on a live box without checking the live Caddyfile first.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
HOST="vps-4f889186.vps.ovh.net"

install_caddy() {
  if command -v caddy >/dev/null 2>&1; then
    return
  fi
  if apt-get install -y caddy; then
    return
  fi
  curl -fsSL -o /tmp/caddy.deb \
    "https://github.com/caddyserver/caddy/releases/download/v2.10.2/caddy_2.10.2_linux_amd64.deb"
  apt-get install -y /tmp/caddy.deb
}

apt-get update -y
apt-get install -y curl ca-certificates debian-keyring debian-archive-keyring apt-transport-https gnupg
install_caddy

cat >/etc/caddy/Caddyfile <<EOF
${HOST} {
	@notplayer {
		not path /api/player /api/player/*
	}
	encode @notplayer gzip
	reverse_proxy 127.0.0.1:8787 {
		flush_interval -1
		transport http {
			dial_timeout 10s
			read_timeout 24h
			write_timeout 24h
		}
	}
}
EOF

caddy validate --config /etc/caddy/Caddyfile
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow OpenSSH
ufw --force enable
systemctl enable caddy
systemctl restart caddy

echo "CADDY_OK"
systemctl is-active caddy
echo "Next: create the dashboard owner account:"
echo "  cd /home/ubuntu/iptv-monitor && .venv/bin/python main.py dashboard-user dan --role owner"
