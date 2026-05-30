#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_dir="$(cd "$script_dir/.." && pwd)"

if [[ -f "$HOME/export-esp.sh" ]]; then
    . "$HOME/export-esp.sh"
fi

if [[ -f "$project_dir/.env" ]]; then
    set -a
    . "$project_dir/.env"
    set +a
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
