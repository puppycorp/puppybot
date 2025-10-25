#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(
  cd "$(dirname "${BASH_SOURCE[0]}")"
  pwd
)

sudo apt update
sudo apt-get install -y git wget flex bison gperf python3 python3-pip \
  python3-venv cmake ninja-build ccache libffi-dev libssl-dev \
  dfu-util libusb-1.0-0 clang-format

git submodule sync --recursive
git submodule update --init --recursive

ESP_IDF_DIR="$ROOT_DIR/deps/espidf"
cd "$ESP_IDF_DIR"
./install.sh esp32
. "$ESP_IDF_DIR/export.sh"

cd "$ROOT_DIR"
bun install

ANDROID_SDK_DIR="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-}}"
if [ -z "$ANDROID_SDK_DIR" ] && [ -d "$HOME/Android/Sdk" ]; then
  ANDROID_SDK_DIR="$HOME/Android/Sdk"
fi

if [ -n "$ANDROID_SDK_DIR" ] && [ -d "$ANDROID_SDK_DIR" ]; then
  printf 'sdk.dir=%s\n' "$ANDROID_SDK_DIR" >"$ROOT_DIR/android/local.properties"
  (cd "$ROOT_DIR/android" && ./gradlew assembleDebug)
else
  echo "Android SDK not found; skipping Android build. Set ANDROID_HOME or ANDROID_SDK_ROOT to run the Android build." >&2
fi
