#!/usr/bin/env bash
# Pull-based deploy for the VPS. iptv-monitor-update.timer runs this as ubuntu every 2 minutes.
# Overview: when origin/main moves, reset tracked files to it, reinstall if pyproject changed,
# restart iptv-monitor, and roll back + alert Discord if the new code does not come up healthy.
# Never runs git clean: .env, live config YAML, state/ and logs/ are gitignored and left alone.
# A commit that failed is remembered in .deploy-failed and skipped until main moves again.
set -euo pipefail

APP=/home/ubuntu/iptv-monitor
SERVICE=iptv-monitor
FAILED_FILE="$APP/.deploy-failed"
cd "$APP"

exec 9>/run/lock/iptv-monitor-update.lock
flock -n 9 || { echo "Another update is running"; exit 0; }

git fetch -q origin main
old=$(git rev-parse HEAD)
new=$(git rev-parse origin/main)
[ "$old" = "$new" ] && exit 0
if [ -f "$FAILED_FILE" ] && [ "$(cat "$FAILED_FILE")" = "$new" ]; then
    exit 0
fi

changed=$(git diff --name-only "$old" "$new")
echo "Deploying ${old:0:7} -> ${new:0:7}: $(git log -1 --format=%s "$new")"
git reset -q --hard "$new"

needs_restart=false
while read -r f; do
    case "$f" in
        *.md|android/*) ;;
        *) needs_restart=true ;;
    esac
done <<< "$changed"

pyproject_changed=false
grep -qx 'pyproject.toml' <<< "$changed" && pyproject_changed=true
$pyproject_changed && .venv/bin/pip install -q -e .

if ! $needs_restart; then
    echo "Docs/android only, no restart"
    rm -f "$FAILED_FILE"
    exit 0
fi

# Healthy = service active, no automatic restarts since ours, dashboard answering locally.
healthy() {
    for _ in $(seq 1 15); do
        sleep 3
        if systemctl is-active -q "$SERVICE" \
            && [ "$(systemctl show -p NRestarts --value "$SERVICE")" = "0" ] \
            && curl -sf -o /dev/null --max-time 5 http://127.0.0.1:8787/api/public; then
            return 0
        fi
    done
    return 1
}

sudo systemctl restart "$SERVICE"
if healthy; then
    echo "Deployed ${new:0:7}, $SERVICE healthy"
    rm -f "$FAILED_FILE"
    exit 0
fi

echo "$SERVICE unhealthy after ${new:0:7}, rolling back to ${old:0:7}"
echo "$new" > "$FAILED_FILE"
git reset -q --hard "$old"
$pyproject_changed && .venv/bin/pip install -q -e .
sudo systemctl restart "$SERVICE"

webhook=$(grep -E '^DISCORD_WEBHOOK_ALERTS=' .env | cut -d= -f2- | tr -d '"'"'"'\r' || true)
if [ -n "$webhook" ]; then
    msg="VPS deploy of ${new:0:7} failed health check; rolled back to ${old:0:7}. Logs: journalctl -u iptv-monitor-update"
    curl -sf -o /dev/null --max-time 10 -H 'Content-Type: application/json' \
        -d "{\"content\": \"$msg\"}" "$webhook" || echo "Discord alert failed"
fi
exit 1
