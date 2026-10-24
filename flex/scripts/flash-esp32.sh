#!/usr/bin/env bash
set -euo pipefail
umask 077
project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if [[ $# != 1 ]]; then echo 'Usage: flash-esp32.sh /dev/serial/by-id/YOUR-ESP32' >&2; exit 2; fi
image="$project_dir/build/flex/esp32/puppybot.bin"
if [[ ! -f "$image" ]]; then echo 'Run flex/scripts/build-esp32.sh first.' >&2; exit 1; fi
python3 "$project_dir/flex/scripts/inspect-esp32.py" "$project_dir/build/flex/esp32/puppybot.elf" "$image"
# Explicit port, original ESP32 only. Save original flash before replacement.
backup="$(mktemp --suffix=.bin "$project_dir/build/flex/esp32/backup-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")"
python3 -m esptool --chip esp32 --port "$1" read_flash 0x0 0x400000 "$backup"
sha256sum "$backup" > "$backup.sha256"
python3 -m esptool --chip esp32 --port "$1" write_flash 0x1000 "$image"
