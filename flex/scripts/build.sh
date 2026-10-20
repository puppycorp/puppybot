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
python3 "$project_dir/flex/scripts/prepare-gym.py"
export FLEXSCRIPT_LIB="${FLEXSCRIPT_LIB:-$project_dir/../flexscript/libs}"
"$compiler" "$project_dir/flex/vision/compile.flex" -o "$project_dir/build/flex/compile-pup"
detector_model="${PUPPYBOT_DETECTOR_MODEL:-$project_dir/flex/vision/models/yolo26n.pup}"
"$project_dir/build/flex/compile-pup" "$detector_model" "$project_dir/build/flex/detector-model.flex"
"$compiler" --target hip "$project_dir/flex/vision/kernels/run.flex" -o "$project_dir/build/flex/vision-kernel.hip"
for entry in examples/controller runtime/main cli/main firmware/sim gym/main vision/main; do
    case "$entry" in
        examples/controller) output=controller-demo ;;
        runtime/main) output=puppybot-runtime ;;
        cli/main) output=puppybot ;;
        firmware/sim) output=puppybot-firmware-sim ;;
        gym/main) output=puppybotgym ;;
        vision/main) output=puppybot-vision ;;
    esac
    temporary="$project_dir/build/flex/$output.tmp.$$"
    trap 'rm -f "$temporary"' EXIT
    "$compiler" "$project_dir/flex/$entry.flex" -o "$temporary"
    mv -f "$temporary" "$project_dir/build/flex/$output"
    echo "Built $project_dir/build/flex/$output"
done
