#!/bin/sh
set -eu

bundle_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

: "${LINGSHU_GATE_HOST:=127.0.0.1}"
: "${LINGSHU_GATE_PORT:=8000}"
: "${LINGSHU_GATE_DATA_DIR:=${bundle_dir}/data}"
: "${LINGSHU_GATE_CONFIG_DIR:=${bundle_dir}/config/mcp.d}"
: "${LINGSHU_GATE_ALLOWED_ROOT:=${bundle_dir}/workspace}"
: "${LINGSHU_GATE_RUNTIME_ROLE:=local}"

export LINGSHU_GATE_HOST LINGSHU_GATE_PORT LINGSHU_GATE_DATA_DIR
export LINGSHU_GATE_CONFIG_DIR LINGSHU_GATE_ALLOWED_ROOT LINGSHU_GATE_RUNTIME_ROLE

mkdir -p "$LINGSHU_GATE_DATA_DIR" "$LINGSHU_GATE_CONFIG_DIR" "$LINGSHU_GATE_ALLOWED_ROOT"
exec "${bundle_dir}/lingshu-gate" "$@"
