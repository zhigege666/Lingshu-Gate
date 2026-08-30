#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"
LOCAL_DIR="$REPOSITORY_DIR/local"
CONFIG_DIR="$LOCAL_DIR/config/mcp.d"
DATA_DIR="$LOCAL_DIR/data"
WORKSPACE_DIR="$LOCAL_DIR/workspace"
CONSOLE_INDEX="$REPOSITORY_DIR/src/lingshu_gate/static/console/index.html"

bash "$SCRIPT_DIR/check.sh"

mkdir -p "$CONFIG_DIR" "$DATA_DIR" "$WORKSPACE_DIR"
cd "$REPOSITORY_DIR"

if [ ! -f "$CONSOLE_INDEX" ]; then
  printf '\033[36mBuilding Console assets...\033[0m\n'
  (cd "$REPOSITORY_DIR/web" && npm ci --no-audit --no-fund && npm run build)
fi

if [ ! -d ".venv" ]; then
  printf '\033[36mCreating Python virtual environment...\033[0m\n'
  python3 -m venv .venv
fi

PYTHON="$REPOSITORY_DIR/.venv/bin/python"

printf '\033[36mInstalling locked Python dependencies...\033[0m\n'
"$PYTHON" -m pip install --require-hashes --requirement requirements.lock

export PYTHONPATH="$REPOSITORY_DIR/src"
export LINGSHU_GATE_ALLOWED_ROOT="$WORKSPACE_DIR"
export LINGSHU_GATE_CONFIG_DIR="$CONFIG_DIR"
export LINGSHU_GATE_DATA_DIR="$DATA_DIR"
export LINGSHU_GATE_HOST="${LINGSHU_GATE_HOST:-127.0.0.1}"
export LINGSHU_GATE_PORT="${LINGSHU_GATE_PORT:-8000}"
export LINGSHU_GATE_LOG_LEVEL="${LINGSHU_GATE_LOG_LEVEL:-INFO}"
export LINGSHU_GATE_RUNTIME_ROLE="${LINGSHU_GATE_RUNTIME_ROLE:-local}"

printf '\033[32mStarting Lingshu Gate...\033[0m\n'
printf '\033[36mConsole: http://%s:%s/console\033[0m\n' "$LINGSHU_GATE_HOST" "$LINGSHU_GATE_PORT"
printf '\033[36mConfig : %s\033[0m\n' "$CONFIG_DIR"
printf '\033[36mData   : %s\033[0m\n' "$DATA_DIR"
printf '\033[36mWork   : %s\033[0m\n' "$WORKSPACE_DIR"

exec "$PYTHON" -m lingshu_gate.cli
