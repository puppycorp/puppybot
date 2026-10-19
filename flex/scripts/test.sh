#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
compiler="${FLEXSCRIPT_COMPILER:-}"
if [[ -z "$compiler" ]]; then
    compiler="$(command -v flexscript || true)"
fi
if [[ -z "$compiler" ]]; then
    compiler="$project_dir/../flexscript/build/flex"
fi
if [[ ! -x "$compiler" ]]; then
    echo 'Set FLEXSCRIPT_COMPILER to a verified Flexscript compiler.' >&2
    exit 1
fi

mkdir -p "$project_dir/build/flex"
cargo test --quiet --locked --offline \
    --manifest-path "$project_dir/flex/tests/core-reference/Cargo.toml" \
    --target-dir "$project_dir/build/flex/core-reference" --lib
for mode in hardware reference; do
    python3 "$project_dir/flex/tests/differential.py" --compiler "$compiler" --lowering-mode "$mode"
    "$compiler" --lowering-mode "$mode" "$project_dir/flex/tests/contracts.flex" \
        -o "$project_dir/build/flex/contracts-$mode"
    "$project_dir/build/flex/contracts-$mode"
done
"$compiler" --target esp32-xip-elf "$project_dir/flex/tests/esp32-smoke.flex" \
    -o "$project_dir/build/flex/esp32-smoke.elf"
FLEXSCRIPT_COMPILER="$compiler" "$project_dir/flex/scripts/build.sh"
"$project_dir/build/flex/controller-demo"
for probe in numbers json; do
    "$compiler" "$project_dir/flex/tests/$probe-probe.flex" -o "$project_dir/build/flex/$probe-probe"
done
for suite in numbers host_json runtime cli; do
    python3 "$project_dir/flex/tests/$suite.py"
done
echo 'Controller, host runtime, CLI, and ESP32 flash-code cross-compilation passed.'
