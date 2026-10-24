#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
compiler="${FLEXSCRIPT_COMPILER:-}"
if [[ -z "$compiler" ]]; then compiler="$(command -v flexscript || true)"; fi
if [[ -z "$compiler" ]]; then compiler="$project_dir/../flexscript/build/flex"; fi
flexscript_dir="${FLEXSCRIPT_SOURCE:-$project_dir/../flexscript}"
linker="${ESP32_LD:-}"
if [[ -z "$linker" ]]; then linker="$(command -v xtensa-esp32-elf-ld || command -v xtensa-esp-elf-ld || true)"; fi
if [[ -z "$linker" ]]; then linker="$project_dir/build/flex/esp32/tools/xtensa-esp-elf/bin/xtensa-esp32-elf-ld"; fi
if [[ ! -x "$compiler" || ! -x "$linker" ]]; then
    echo 'Set FLEXSCRIPT_COMPILER and ESP32_LD to the Flexscript compiler and Espressif Xtensa linker.' >&2; exit 1
fi
output_dir="$project_dir/build/flex/esp32"
mkdir -p "$output_dir"
python3 "$project_dir/flex/scripts/prepare-esp32.py" --config "${PUPPYBOT_ESP32_CONFIG:-$project_dir/puppybot.json}"
"$compiler" "$project_dir/flex/tests/esp32-config.flex" -o "$output_dir/check-config"
"$output_dir/check-config"
"$compiler" --target esp32-xip-elf "$project_dir/flex/firmware/esp32.flex" -o "$output_dir/puppybot-unlinked.elf"
"$compiler" "$flexscript_dir/scripts/esp32-link.flex" -o "$output_dir/esp32-link"
"$output_dir/esp32-link" --firmware "$output_dir/puppybot-unlinked.elf" --xip \
    --ld "$linker" --rom "$project_dir/flex/firmware/esp32-symbols.ld" \
    --output "$output_dir/puppybot.elf" --image "$output_dir/puppybot.bin" --map "$output_dir/puppybot.map"
python3 "$project_dir/flex/scripts/inspect-esp32.py" "$output_dir/puppybot.elf" "$output_dir/puppybot.bin"
echo "Built classic ESP32 firmware: $output_dir/puppybot.bin (flash offset 0x1000)"
