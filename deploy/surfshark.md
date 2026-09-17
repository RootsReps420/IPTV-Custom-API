# Surfshark WireGuard for /watch (split tunnel)

Magnum `/watch` traffic binds to the VPN address when the interface is up.
Dashboard health checks, EPGenius, Discord, Android, SSH, Caddy, and Strong 8K
stay on the VPS public NIC.

Do **not** put `AllowedIPs = 0.0.0.0/0` on the **main** routing table. That
blackholes SSH. Use a separate table (`51820`) plus `from <wg-ip>` so only
sockets bound to the WireGuard address leave through Surfshark.

Keys stay on the VPS. Never commit them.

## Install

```bash
sudo apt-get update
sudo apt-get install -y wireguard
```

Copy `deploy/surfshark-wg.example.conf` to `/etc/wireguard/surfshark.conf`.
Fill in `PrivateKey`, `Address`, `PublicKey`, and `Endpoint` from the
Surfshark Linux WireGuard config (same values; different routing).

Replace `10.14.0.2` in `PostUp` / `PostDown` with the IPv4 from `Address=`
(the part before `/`). `Table = 51820` already installs the default route in
that table; the `from` rules are what keep SSH on the public NIC.

```bash
sudo chmod 600 /etc/wireguard/surfshark.conf
sudo systemctl enable --now wg-quick@surfshark
ip -4 addr show dev surfshark
```

`curl --interface surfshark https://api.ipify.org` should print a Surfshark
exit IP. `curl https://api.ipify.org` (no `--interface`) should still be the
VPS public IP.

Optional: set `watch_vpn_interface: surfshark` in `config/settings.yaml`.
Empty means auto-detect `surfshark` / `wg0`. YAML reloads next cycle.

## Handshake extras (optional)

The portal already reports connected / city / exit IP from the bind address.
`wg show` needs extra rights because the systemd unit sets `NoNewPrivileges`.

```bash
echo 'ubuntu ALL=(root) NOPASSWD: /usr/bin/wg show all dump' | sudo tee /etc/sudoers.d/iptv-wg
sudo chmod 440 /etc/sudoers.d/iptv-wg
sudo visudo -cf /etc/sudoers.d/iptv-wg
sudo mkdir -p /etc/systemd/system/iptv-monitor.service.d
sudo tee /etc/systemd/system/iptv-monitor.service.d/vpn.conf >/dev/null << 'EOF'
[Service]
NoNewPrivileges=false
EOF
sudo systemctl daemon-reload
sudo systemctl restart iptv-monitor
```

Skip this if you only care about connected / location / speed test.

## Owner portal

`/owner` → **Watch VPN**: connected, location, exit IP, and a ~5MB speed test
through the same bind `/watch` uses. Strong 8K probes never use this path.

## Bring-up / down

```bash
sudo systemctl start wg-quick@surfshark
sudo systemctl stop wg-quick@surfshark
sudo journalctl -u wg-quick@surfshark -n 50 --no-pager
```

If SSH dies after `wg-quick up`, reboot from the OVH console and check that
`Table = 51820` and the `from <wg-ip>` rules are present. Do not run a
Surfshark “full tunnel” Linux profile on this VPS.
