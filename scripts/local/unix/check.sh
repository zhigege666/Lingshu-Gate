#!/usr/bin/env bash
set -euo pipefail

printf '\033[36mLingshu Gate local environment check\033[0m\n'

failed=0

check_command() {
  local name="$1"
  local hint="$2"
  if command -v "$name" >/dev/null 2>&1; then
    printf '\033[32m[OK] %s: %s\033[0m\n' "$name" "$("$name" --version 2>&1 | tail -n 1)"
  else
    printf '\033[31m[FAIL] %s not found. %s\033[0m\n' "$name" "$hint"
    failed=1
  fi
}

check_command python3 "Install Python 3.11 or newer."
check_command node "Install Node.js 22 or newer."
check_command npm "Install the npm version bundled with Node.js 22 or newer."

if command -v python3 >/dev/null 2>&1 && ! python3 - <<'PY'
import sys

raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
then
  printf '\033[31m[FAIL] Python 3.11 or newer is required.\033[0m\n'
  failed=1
fi

if command -v node >/dev/null 2>&1 && ! node --eval 'process.exit(Number(process.versions.node.split(".")[0]) >= 22 ? 0 : 1)'
then
  printf '\033[31m[FAIL] Node.js 22 or newer is required.\033[0m\n'
  failed=1
fi

if [ "$failed" -ne 0 ]; then
  exit 1
fi

printf '\033[32mEnvironment check passed.\033[0m\n'
