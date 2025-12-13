#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

if [ -f "${ROOT_DIR}/.env" ]; then
  set -a
  # shellcheck disable=SC1090
  source "${ROOT_DIR}/.env"
  set +a
fi

cd "${SCRIPT_DIR}"

ACTION="${1:-all}"

case "${ACTION}" in
build)
  idf.py -DPROJECT_VER="${VERSION:-1}" build
  ;;
flash)
  idf.py flash
  ;;
monitor)
  idf.py monitor
  ;;
all)
  idf.py -DPROJECT_VER="${VERSION:-1}" build
  idf.py flash monitor
  ;;
*)
  echo "Usage: $0 [build|flash|monitor|all]"
  exit 2
  ;;
esac
