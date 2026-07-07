#!/usr/bin/env bash
# One-time VPS migration: letstranscriber -> letsscribe
# Run on the server as root after DNS is ready:
#   curl -fsSL https://raw.githubusercontent.com/dlaumets/LetsScribe/main/deploy/migrate-to-letsscribe.sh | bash
set -euo pipefail

OLD=/opt/letstranscriber
NEW=/opt/letsscribe

if [ -d "$OLD" ] && [ ! -e "$NEW" ]; then
  mv "$OLD" "$NEW"
  echo "==> Renamed ${OLD} -> ${NEW}"
elif [ -d "$NEW" ]; then
  echo "==> Already using ${NEW}"
else
  echo "ERROR: neither ${OLD} nor ${NEW} exists" >&2
  exit 1
fi

cd "$NEW"
git remote set-url origin https://github.com/dlaumets/LetsScribe.git 2>/dev/null || true
git fetch origin main
git reset --hard origin/main

if [ -f .env ]; then
  sed -i 's|transcriber\.letscore\.tech|scribe.letscore.tech|g' .env
fi

echo "==> Pull done. Redeploy:"
echo "    cd ${NEW} && bash deploy/deploy.sh"
echo ""
echo "Optional: update server-monitor .env MONITOR_SCRIBE_API if you use a custom URL."
