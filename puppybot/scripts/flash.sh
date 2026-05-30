#!/usr/bin/env bash

set -euo pipefail

if ! command -v espflash >/dev/null 2>&1; then
    echo "espflash not found; run: ./scripts/install.sh" >&2
    exit 1
fi

serial_port="${ESPFLASH_PORT:-}"

if [[ -z "$serial_port" ]]; then
    ports=()
    for candidate in /dev/ttyUSB* /dev/ttyACM*; do
        if [[ -e "$candidate" ]]; then
            ports+=("$candidate")
        fi
    done

    for candidate in "${ports[@]}"; do
        if [[ -r "$candidate" && -w "$candidate" ]]; then
            serial_port="$candidate"
            break
        fi
    done

    if [[ -z "$serial_port" && "${#ports[@]}" -gt 0 ]]; then
        serial_port="${ports[0]}"
    fi
fi

if [[ -n "$serial_port" && (! -r "$serial_port" || ! -w "$serial_port") ]]; then
    port_group="$(stat -c '%G' "$serial_port")"
    echo "Cannot access $serial_port; add your user to the $port_group group:" >&2
    echo "  sudo usermod -aG $port_group $USER" >&2
    echo "Then log out and back in, or run: newgrp $port_group" >&2
    exit 1
fi

mode="${1:-release}"

case "$mode" in
    release)
        ./scripts/build.sh release
        profile="release"
        ;;
    debug)
        ./scripts/build.sh debug
        profile="debug"
        ;;
    *)
        echo "usage: $0 [debug|release]" >&2
        exit 1
        ;;
esac

espflash flash --monitor "target/xtensa-esp32-none-elf/$profile/puppybot"
