#!/usr/bin/env bash
# Pull latest code and rebuild containers
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/letstranscriber}"
cd "$APP_DIR"

echo "==> Pulling latest..."
git fetch origin main
git reset --hard origin/main

echo "==> Building and starting services..."
docker compose --profile bot --profile prod pull --ignore-buildable 2>/dev/null || true
docker compose --profile bot --profile prod up -d --build --remove-orphans

echo "==> Cleaning old images..."
docker image prune -f

echo "==> Status:"
docker compose ps

echo "==> Deploy done at $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
