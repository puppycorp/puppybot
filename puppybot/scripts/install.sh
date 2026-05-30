#!/usr/bin/env bash

set -euo pipefail

if ! command -v cargo >/dev/null 2>&1; then
    echo "cargo not found; install Rust first: https://rustup.rs/" >&2
    exit 1
fi

export PATH="$HOME/.cargo/bin:$PATH"

if ! command -v espup >/dev/null 2>&1; then
    cargo install espup --locked
fi

if [[ -f "$HOME/export-esp.sh" ]]; then
    . "$HOME/export-esp.sh"
fi

if ! command -v xtensa-esp32-elf-gcc >/dev/null 2>&1; then
    espup install
    . "$HOME/export-esp.sh"
fi

if ! command -v xtensa-esp32-elf-gcc >/dev/null 2>&1; then
    echo "xtensa-esp32-elf-gcc not found after espup install" >&2
    exit 1
fi

if ! command -v espflash >/dev/null 2>&1; then
    cargo install espflash --locked
fi

for serial_port in /dev/ttyUSB* /dev/ttyACM*; do
    if [[ -e "$serial_port" && (! -r "$serial_port" || ! -w "$serial_port") ]]; then
        port_group="$(stat -c '%G' "$serial_port")"
        echo "Serial port $serial_port is not accessible by $USER."
        echo "Run: sudo usermod -aG $port_group $USER"
        echo "Then log out and back in, or run: newgrp $port_group"
        break
    fi
done

echo "Puppybot Rust ESP32 dependencies are installed."
