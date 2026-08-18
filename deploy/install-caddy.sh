#!/bin/bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
HOST="vps-4f889186.vps.ovh.net"
USER_NAME="dan"

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

PASS="$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')"
HASH="$(caddy hash-password --plaintext "$PASS")"

umask 077
cat >/etc/caddy/Caddyfile <<EOF
${HOST} {
	encode gzip
	@owner {
		path /owner /owner/ /api/status
	}
	basicauth @owner {
		${USER_NAME} "${HASH}"
	}
	reverse_proxy 127.0.0.1:8787
}
EOF

caddy validate --config /etc/caddy/Caddyfile
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow OpenSSH
ufw --force enable
systemctl enable --now caddy
systemctl reload caddy

install -m 600 /dev/null /home/ubuntu/.dashboard-login
chown ubuntu:ubuntu /home/ubuntu/.dashboard-login
cat >/home/ubuntu/.dashboard-login <<EOF
url=https://${HOST}
username=${USER_NAME}
password=${PASS}
EOF

echo "CADDY_OK"
systemctl is-active caddy
