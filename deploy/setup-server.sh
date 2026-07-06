#!/usr/bin/env bash
# One-time VPS setup for LetsTranscriber
# Run as root on the server: bash setup-server.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/letstranscriber}"
REPO_URL="${REPO_URL:-https://github.com/dlaumets/LetsTranscriber.git}"

echo "==> Installing Docker..."
if ! command -v docker &>/dev/null; then
  curl -fsSL https://get.docker.com | sh
  systemctl enable docker
  systemctl start docker
fi

echo "==> Installing Docker Compose plugin..."
if ! docker compose version &>/dev/null; then
  apt-get update -qq
  apt-get install -y docker-compose-plugin git curl
fi

echo "==> Cloning repository to ${APP_DIR}..."
if [ ! -d "$APP_DIR/.git" ]; then
  git clone "$REPO_URL" "$APP_DIR"
else
  echo "    Repo already exists, skipping clone"
fi

cd "$APP_DIR"

if [ ! -f .env ]; then
  cp .env.example .env
  echo ""
  echo "!!! Edit ${APP_DIR}/.env before first start:"
  echo "    - DB_PASSWORD"
  echo "    - BOT_TOKEN"
  echo "    - WEBHOOK_URL (https://YOUR_DOMAIN/bot/webhook)"
  echo "    - Update Caddyfile with your domain"
fi

mkdir -p data/temp data/jobs models-cache

echo "==> Setup complete."
echo "    Next: edit .env and Caddyfile, then run:"
echo "    cd ${APP_DIR} && bash deploy/deploy.sh"
