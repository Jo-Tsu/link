#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: $0 <ssh-user@ecs-public-ip> [private-key-path]" >&2
  exit 1
fi

target="$1"
key_path="${2:-}"
ssh_options=(-o BatchMode=yes -o StrictHostKeyChecking=accept-new)

if [[ -n "$key_path" ]]; then
  ssh_options+=(-i "$key_path")
fi

ssh "${ssh_options[@]}" "$target" "bash -s" <"$(dirname "$0")/bootstrap.sh"
