#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$project_dir/src/scripts/native-toolchain.sh"
if [[ ! -x "$compiler" ]]; then
    echo 'Set FLEXSCRIPT_COMPILER to a verified Flexscript compiler.' >&2
    exit 1
fi

# The controller and serial simulator do not need GPU training dependencies.
mkdir -p "$project_dir/build/flex"
python3 "$project_dir/src/scripts/prepare-dashboard.py" --check
for entry in examples/controller runtime/main simulator/main cli/main firmware/sim; do
    case "$entry" in
        examples/controller) output=controller-demo ;;
        runtime/main) output=puppybot-runtime ;;
        simulator/main) output=puppybot-simulator ;;
        cli/main) output=puppybot ;;
        firmware/sim) output=puppybot-firmware-sim ;;
    esac
    temporary="$project_dir/build/flex/$output.tmp.$$"
    trap 'rm -f "$temporary"' EXIT
    "$compiler" "$project_dir/src/$entry.flex" -o "$temporary"
    mv -f "$temporary" "$project_dir/build/flex/$output"
    echo "Built $project_dir/build/flex/$output"
done
