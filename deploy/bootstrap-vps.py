#!/usr/bin/env python3
"""One-shot VPS bootstrap. Run locally with env vars — never commit secrets."""
from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

import paramiko

HOST = os.environ["VPS_HOST"]
USER = os.environ.get("VPS_USER", "root")
PASSWORD = os.environ["VPS_PASSWORD"]
APP_DIR = os.environ.get("VPS_APP_DIR", "/opt/letsscribe")
REPO = os.environ.get("VPS_REPO", "https://github.com/dlaumets/LetsScribe.git")
BOT_TOKEN = os.environ["BOT_TOKEN"]

PUBKEY_PATH = Path(os.environ.get("SSH_PUBKEY", Path.home() / ".ssh" / "id_ed25519.pub"))


def run(client: paramiko.SSHClient, cmd: str, *, check=True) -> tuple[int, str, str]:
    print(f"\n$ {cmd[:120]}{'...' if len(cmd) > 120 else ''}")
    _, stdout, stderr = client.exec_command(cmd, get_pty=True)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    if out.strip():
        print(out.rstrip())
    if err.strip():
        print(err.rstrip(), file=sys.stderr)
    if check and code != 0:
        raise RuntimeError(f"Command failed ({code}): {cmd}\n{err or out}")
    return code, out, err


def main() -> int:
    pubkey = PUBKEY_PATH.read_text(encoding="utf-8").strip()
    db_password = secrets.token_urlsafe(24)

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Connecting to {USER}@{HOST}...")
    client.connect(HOST, username=USER, password=PASSWORD, timeout=60)

    run(client, "mkdir -p ~/.ssh && chmod 700 ~/.ssh")
    run(
        client,
        f'grep -Fq "{pubkey.split()[1]}" ~/.ssh/authorized_keys 2>/dev/null || echo "{pubkey}" >> ~/.ssh/authorized_keys',
    )
    run(client, "chmod 600 ~/.ssh/authorized_keys")

    run(
        client,
        "test -f /swapfile || (fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile && "
        'grep -q "/swapfile" /etc/fstab || echo "/swapfile none swap sw 0 0" >> /etc/fstab)',
        check=False,
    )

    run(client, "command -v docker >/dev/null || curl -fsSL https://get.docker.com | sh")
    run(client, "systemctl enable docker && systemctl start docker")
    run(
        client,
        "docker compose version >/dev/null 2>&1 || (apt-get update -qq && apt-get install -y -qq git curl docker-compose-plugin)",
        check=False,
    )

    run(client, f'test -d {APP_DIR}/.git || git clone {REPO} {APP_DIR}', check=False)
    run(client, f"cd {APP_DIR} && git fetch origin main && git reset --hard origin/main")

    env_content = f"""DEVICE=cpu
MAX_UPLOAD_MB=500
MAX_DURATION_HOURS=4
DEFAULT_PRESET=balanced
DEFAULT_LANGUAGE=ru
RATE_LIMIT_PER_HOUR=30
QUEUE_MAX_SIZE=3
ASYNC_THRESHOLD_SECONDS=900

DATABASE_URL=postgresql+asyncpg://transcribe:{db_password}@db:5432/transcribe
DB_PASSWORD={db_password}

BOT_TOKEN={BOT_TOKEN}
WEBHOOK_URL=
WEBHOOK_PATH=/bot/webhook
BOT_HOST=0.0.0.0
BOT_PORT=8081
API_URL=http://api:8000
"""
    run(client, f"cat > {APP_DIR}/.env << 'ENVEOF'\n{env_content}ENVEOF")
    run(client, f"mkdir -p {APP_DIR}/data/temp {APP_DIR}/data/jobs {APP_DIR}/models-cache")

    run(client, f"cd {APP_DIR} && docker compose --profile bot up -d --build --remove-orphans")

    run(
        client,
        f"sleep 20 && curl -sf http://localhost:8000/v1/health && echo HEALTH_OK || "
        f"(cd {APP_DIR} && docker compose logs --tail=50 api; exit 1)",
        check=False,
    )

    run(client, f"cd {APP_DIR} && docker compose ps")
    run(client, "free -h")

    client.close()
    print("\n=== Bootstrap complete ===")
    print(f"API: http://{HOST}:8000")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
