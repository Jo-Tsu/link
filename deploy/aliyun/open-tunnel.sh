#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: $0 <ssh-user@ecs-public-ip> [private-key-path]" >&2
  exit 1
fi

target="$1"
key_path="${2:-}"
local_port="${LINK_TUNNEL_PORT:-42737}"
remote_port="${LINK_REMOTE_PORT:-41737}"
ssh_options=(
  -N
  -T
  -o ExitOnForwardFailure=yes
  -o ServerAliveInterval=30
  -o ServerAliveCountMax=3
  -o StrictHostKeyChecking=accept-new
  -L "127.0.0.1:${local_port}:127.0.0.1:${remote_port}"
)

if [[ -n "$key_path" ]]; then
  ssh_options+=(-i "$key_path")
fi

echo "Opening Link at http://127.0.0.1:${local_port}"
echo "Keep this terminal running while the browser or LinkAgent uses the cloud platform."
exec ssh "${ssh_options[@]}" "$target"
