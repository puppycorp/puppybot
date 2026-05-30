#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_dir="$(cd "$script_dir/.." && pwd)"

if [[ -f "$HOME/export-esp.sh" ]]; then
    . "$HOME/export-esp.sh"
fi

if [[ -f "$project_dir/.env" ]]; then
    had_wifi_ssid=0
    had_wifi_password=0
    if [[ -v WIFI_SSID ]]; then
        had_wifi_ssid=1
        old_wifi_ssid="$WIFI_SSID"
    fi
    if [[ -v WIFI_PASSWORD ]]; then
        had_wifi_password=1
        old_wifi_password="$WIFI_PASSWORD"
    fi

    set -a
    . "$project_dir/.env"
    set +a

    if [[ "$had_wifi_ssid" -eq 1 ]]; then
        WIFI_SSID="$old_wifi_ssid"
        export WIFI_SSID
    fi
    if [[ "$had_wifi_password" -eq 1 ]]; then
        WIFI_PASSWORD="$old_wifi_password"
        export WIFI_PASSWORD
    fi
fi

if ! command -v xtensa-esp32-elf-gcc >/dev/null 2>&1; then
    echo "xtensa-esp32-elf-gcc not found; run: ./scripts/install.sh" >&2
    exit 1
fi

cd "$project_dir"

case "${1:-release}" in
    release)
        cargo build --release
        ;;
    debug)
        cargo build
        ;;
    *)
        echo "usage: $0 [debug|release]" >&2
        exit 1
        ;;
esac
