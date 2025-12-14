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

VERSION_SCRIPT="${ROOT_DIR}/scripts/build_version.sh"
if [ -f "${VERSION_SCRIPT}" ]; then
  BUILD_VERSION="$("${VERSION_SCRIPT}" version)"
  BUILD_NAME="$("${VERSION_SCRIPT}" name)"
else
  BUILD_VERSION="unknown"
  BUILD_NAME="puppybot"
fi

ACTION="${1:-all}"

case "${ACTION}" in
build)
  echo "Building ESP32 firmware with version: ${BUILD_VERSION}"
  idf.py -DPROJECT_VER="${BUILD_VERSION}" -DPUPPYBOT_BUILD_NAME="${BUILD_NAME}" build
  ;;
flash)
  idf.py flash
  ;;
monitor)
  idf.py monitor
  ;;
all)
  echo "Building ESP32 firmware with version: ${BUILD_VERSION}"
  idf.py -DPROJECT_VER="${BUILD_VERSION}" -DPUPPYBOT_BUILD_NAME="${BUILD_NAME}" build
  idf.py flash monitor
  ;;
*)
  echo "Usage: $0 [build|flash|monitor|all]"
  exit 2
  ;;
esac
