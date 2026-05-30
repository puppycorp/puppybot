#!/usr/bin/env bash

set -euo pipefail

if [[ -f "$HOME/export-esp.sh" ]]; then
    . "$HOME/export-esp.sh"
fi

if ! command -v xtensa-esp32-elf-gcc >/dev/null 2>&1; then
    echo "xtensa-esp32-elf-gcc not found; run: ./scripts/install.sh" >&2
    exit 1
fi

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
