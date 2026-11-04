#!/usr/bin/env bash
set -euo pipefail
project="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$project"
output="${1:?New output directory required}"
mkdir "$output"
output="$(cd "$output" && pwd)"
build/flex/control/pose-fixtures "$output/fixture"
for episode in 0 1; do
    mkdir -p "$output/runs/expert-$episode"
    printf '{}\n' > "$output/runs/expert-$episode/initial.json"
    printf '{}\n' > "$output/runs/expert-$episode/decisions.jsonl"
done
build/flex/control/merge-dense-many "$output/data" "$output/fixture/data.bin" "$output/runs" "$output/fixture/mirrored-data.bin" "$output/runs" "$output/fixture/data.bin" "$output/runs" "$output/fixture/mirrored-data.bin" "$output/runs"
build/flex/control/control init --categorical --output "$output/base" --seed 7 > "$output/base.log" 2>&1
for arm in plain focus repeat; do
    extra=(); if [[ "$arm" != plain ]]; then extra+=(--focus-history 3 --focus-copies 2); fi
    build/flex/control/control train --initial-policy "$output/base" --data "$output/data/data.bin" --output "$output/$arm" --epochs 3 --batch 2 --learning-rate-micros 100 --seed 7 "${extra[@]}" > "$output/$arm.log" 2>&1
done
for file in initial.bin first-order.bin final-order.bin first-gradients.bin first-after.bin last.bin weights.bin; do cmp "$output/focus/$file" "$output/repeat/$file"; done
check_order() {
    local file="$1"; local values=()
    read -r -a values <<< "$(od -An -v -t u8 "$file" | xargs)"
    [[ "${#values[@]}" == 8 && "${values[*]:4:4}" == '4 5 6 7' ]]
    local focus=0 value other=()
    for value in "${values[@]:0:4}"; do if [[ "$value" == 3 ]]; then focus=$((focus+1)); else [[ "$value" -lt 3 ]]; other+=("$value"); fi; done
    [[ "$focus" == 2 && "${#other[@]}" == 2 && "${other[0]}" != "${other[1]}" ]]
}
check_order "$output/focus/first-order.bin"
check_order "$output/focus/final-order.bin"
read -r -a first_order <<< "$(od -An -v -t u8 "$output/focus/first-order.bin" | xargs)"
read -r -a final_order <<< "$(od -An -v -t u8 "$output/focus/final-order.bin" | xargs)"
[[ "$(printf '%s\n' "${first_order[@]:0:4}" | sort -n | xargs)" != "$(printf '%s\n' "${final_order[@]:0:4}" | sort -n | xargs)" ]]
[[ "$(od -An -v -t u8 "$output/plain/first-order.bin" | xargs)" != "$(od -An -v -t u8 "$output/focus/first-order.bin" | xargs)" ]]
jq -se 'map(select(.epoch==0)|[.trainingLoss,.validationLoss])|unique|length==1' "$output/plain/curves.jsonl" "$output/focus/curves.jsonl" > /dev/null
for arm in plain focus; do jq -se '.[-1].epoch==3 and .[-1].optimizerSteps==6' "$output/$arm/curves.jsonl" > /dev/null; done
jq -e '.focusHistory==3 and .focusCopiesPerEpoch==2 and (.taskFeedback|not)' "$output/focus/receipt.json" > /dev/null
if build/flex/control/control train --initial-policy "$output/base" --data "$output/data/data.bin" --output "$output/invalid-validation" --epochs 1 --batch 2 --focus-history 4 --focus-copies 2 > "$output/invalid-validation.log" 2>&1; then echo 'Validation history was accepted for focused training.' >&2; exit 1; fi
rg -Fq 'focus requires a fitting history' "$output/invalid-validation/training.log"
if build/flex/control/control train --initial-policy "$output/base" --data "$output/data/data.bin" --output "$output/invalid-copies" --epochs 1 --batch 2 --focus-history 3 --focus-copies 5 > "$output/invalid-copies.log" 2>&1; then echo 'Excessive focus copies were accepted.' >&2; exit 1; fi
rg -Fq 'focus requires a fitting history' "$output/invalid-copies/training.log"
if build/flex/control/control train --data "$output/data/data.bin" --output "$output/invalid-pair" --focus-history 1 > "$output/invalid-pair.log" 2>&1; then echo 'Incomplete focus options were accepted.' >&2; exit 1; fi
[[ ! -e "$output/invalid-pair" ]]
echo 'Focused sampling is deterministic, fitting-only and preserves validation.'
