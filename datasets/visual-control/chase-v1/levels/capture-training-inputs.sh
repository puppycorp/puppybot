#!/usr/bin/env bash
# Pin the current training binaries, kernels, source models and aggregated
# data after collection, before training. Refuse to replace an existing record.
# Usage: capture-training-inputs.sh OUTPUT_SHA256 AGGREGATE_DIR
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="${1:?Output checksum file required}"; data="${2:?Aggregate directory required}"
cd "$project"
[[ ! -e "$out" ]] || { echo "Refusing to replace $out" >&2; exit 1; }
models=()
for s in 0 1 2; do models+=("$project/build/flex/sim/levels-v2/pitch82/more1-s$s"); done
files=(build/flex/control/control build/flex/control/simulator build/flex/control/compiler build/flex/control/trainer
       "$data/data.bin" "$data/map.bin")
for model in "${models[@]}"; do
    files+=("$model/receipt.json" "$model/policy" "$model/weights.bin")
    [[ -d "$model/kernels" ]] || { echo "Missing model kernels: $model" >&2; exit 1; }
    before=${#files[@]}
    while IFS= read -r -d '' file; do files+=("$file"); done < <(find "$model/kernels" -type f -print0 | sort -z)
    (( ${#files[@]} > before )) || { echo "Empty model kernels: $model" >&2; exit 1; }
done
[[ -d build/flex/control/kernels ]] || { echo 'Missing training kernels' >&2; exit 1; }
before=${#files[@]}
while IFS= read -r -d '' file; do files+=("$file"); done < <(find build/flex/control/kernels -type f -print0 | sort -z)
(( ${#files[@]} > before )) || { echo 'Empty training kernels' >&2; exit 1; }
temp=$(mktemp "${out}.tmp.XXXXXX")
trap 'rm -f "$temp"' EXIT
sha256sum "${files[@]}" > "$temp"
sha256sum -c "$temp" > /dev/null
ln "$temp" "$out"
echo "Captured ${#files[@]} current training inputs in $out"
