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
python3 "$project_dir/flex/scripts/prepare-dashboard.py" --check
export FLEXSCRIPT_ROOT="${FLEXSCRIPT_ROOT:-$project_dir/../flexscript}"
export FLEXSCRIPT_LIB="${FLEXSCRIPT_LIB:-$FLEXSCRIPT_ROOT/libs}"
python3 "$project_dir/flex/scripts/prepare-compiler.py" --source "$FLEXSCRIPT_ROOT" --bootstrap "$compiler"
compiler="$project_dir/build/flex/pup-compiler"
python3 "$project_dir/flex/scripts/prepare-gym.py"
"$compiler" "$project_dir/flex/ml/compile.flex" -o "$project_dir/build/flex/compile-pup"
detector_model="${PUPPYBOT_DETECTOR_MODEL:-$project_dir/flex/vision/models/yolo26n.pup}"
"$project_dir/build/flex/compile-pup" "$detector_model" "$project_dir/build/flex/detector-model.flex"
"$compiler" "$project_dir/flex/ml/codegen.flex" -o "$project_dir/build/flex/pup-codegen.tmp.$$"
mv -f "$project_dir/build/flex/pup-codegen.tmp.$$" "$project_dir/build/flex/pup-codegen"
"$project_dir/build/flex/pup-codegen" --output "$project_dir/build/flex/pup-kernels" --generic-only --compiler "$compiler"
"$compiler" "$project_dir/flex/ml/describe.flex" -o "$project_dir/build/flex/pup-describe"
"$project_dir/build/flex/pup-describe" "$project_dir/build/flex/pup-graph.bin"
"$project_dir/build/flex/pup-codegen" "$project_dir/build/flex/pup-graph.bin" --output "$project_dir/build/flex/pup-kernels" --compiler "$compiler" --math "${PUPPYBOT_MATH:-fp32}"
for entry in examples/controller runtime/main simulator/main cli/main firmware/sim gym/main vision/main; do
    case "$entry" in
        examples/controller) output=controller-demo ;;
        runtime/main) output=puppybot-runtime ;;
        simulator/main) output=puppybot-simulator ;;
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
