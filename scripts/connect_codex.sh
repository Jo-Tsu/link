#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CLI="$ROOT/.venv/bin/smallink-connectors"

if [[ ! -x "$CLI" ]]; then
  echo "Smallink development environment is missing: $CLI" >&2
  echo "Create .venv and install the project before running this script." >&2
  exit 1
fi

# With no --folder argument the CLI opens the native directory picker. The user selects
# ~/.codex (or ~/.codex/sessions); the connector stores the normalized path, then imports all
# usable Codex sessions. Pass arguments through for --folder, --limit, or --reconnect.
exec "$CLI" sync-codex "$@"
