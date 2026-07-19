#!/usr/bin/env bash
set -euo pipefail

REPOSITORY_URL="${LINK_REPOSITORY_URL:-https://github.com/Jo-Tsu/link.git}"
INSTALL_DIR="${LINK_INSTALL_DIR:-$HOME/link}"

if ! command -v sudo >/dev/null 2>&1; then
  echo "sudo is required on the ECS host." >&2
  exit 1
fi

if ! command -v apt-get >/dev/null 2>&1; then
  echo "This bootstrap currently supports Ubuntu 24.04/22.04. Use an Ubuntu ECS image." >&2
  exit 1
fi

sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
  ca-certificates \
  curl \
  docker.io \
  docker-compose-v2 \
  git \
  openssl
sudo systemctl enable --now docker

if [[ -d "$INSTALL_DIR/.git" ]]; then
  git -C "$INSTALL_DIR" fetch origin main
  git -C "$INSTALL_DIR" checkout main
  git -C "$INSTALL_DIR" pull --ff-only origin main
else
  git clone --branch main --single-branch "$REPOSITORY_URL" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"

if [[ ! -f .env ]]; then
  postgres_password="$(openssl rand -hex 32)"
  cat >.env <<EOF
LINK_PORT=41737
POSTGRES_PORT=55437
CRAWLER_PORT=18744
LINK_DEPLOYMENT_MODE=private-cloud-test
POSTGRES_USER=link
POSTGRES_PASSWORD=$postgres_password
POSTGRES_DB=link
EOF
  chmod 600 .env
fi

sudo docker compose up -d --build

for attempt in $(seq 1 30); do
  if curl --fail --silent http://127.0.0.1:41737/api/health >/dev/null; then
    echo "Link is healthy on the ECS loopback interface."
    echo "Keep ports 41737, 55437 and 18744 closed in the security group."
    exit 0
  fi
  sleep 2
done

sudo docker compose ps
sudo docker compose logs --tail=120 link-app postgres
echo "Link did not become healthy in time." >&2
exit 1
