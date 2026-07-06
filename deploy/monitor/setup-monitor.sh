#!/usr/bin/env bash
# Install server monitor bot on VPS
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/server-monitor}"
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SRC_DIR/../.." && pwd)"

echo "==> Installing to ${APP_DIR}..."
mkdir -p "$APP_DIR"
cp "$SRC_DIR/monitor_bot.py" "$SRC_DIR/collectors.py" "$SRC_DIR/requirements.txt" "$APP_DIR/"

if [ ! -f "$APP_DIR/.env" ]; then
  cp "$SRC_DIR/.env.example" "$APP_DIR/.env"
  echo "!!! Edit ${APP_DIR}/.env — set MONITOR_BOT_TOKEN and MONITOR_ALLOWED_IDS"
fi

sed -i 's/\r$//' "$APP_DIR/.env" 2>/dev/null || true

if [ ! -d "$APP_DIR/.venv" ]; then
  python3 -m venv "$APP_DIR/.venv"
fi

"$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

cp "$SRC_DIR/server-monitor.service" /etc/systemd/system/server-monitor.service
systemctl daemon-reload
systemctl enable server-monitor
systemctl restart server-monitor

echo "==> Status:"
systemctl status server-monitor --no-pager -l | head -15
echo ""
echo "Send /whoami to your monitor bot to get your Telegram ID, then add it to MONITOR_ALLOWED_IDS"
