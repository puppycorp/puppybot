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
build/flex/control/merge-dense-many "$output/data" "$output/fixture/data.bin" "$output/runs" "$output/fixture/mirrored-data.bin" "$output/runs"
for arm in limited repeat full; do
    extra=(); if [[ "$arm" != full ]]; then extra+=(--max-optimizer-steps 3); fi
    build/flex/control/control train --data "$output/data/data.bin" --output "$output/$arm" --epochs 4 --batch 1 --learning-rate-micros 100 --seed 7 --from-scratch --categorical "${extra[@]}" > "$output/$arm.log" 2>&1
done
for file in initial.bin first-order.bin final-order.bin first-gradients.bin first-after.bin last.bin weights.bin; do cmp "$output/limited/$file" "$output/repeat/$file"; done
jq -se 'length==3 and .[0].optimizerSteps==0 and .[1].optimizerSteps==2 and .[2].epoch==2 and .[2].optimizerSteps==3 and all(.[];.maxOptimizerSteps==3)' "$output/limited/curves.jsonl" > /dev/null
jq -se 'length==5 and .[-1].epoch==4 and .[-1].optimizerSteps==8 and all(.[];has("maxOptimizerSteps")|not)' "$output/full/curves.jsonl" > /dev/null
jq -e '.maxOptimizerSteps==3 and .epochs==4 and (.taskFeedback|not)' "$output/limited/receipt.json" > /dev/null
jq -e 'has("maxOptimizerSteps")|not' "$output/full/receipt.json" > /dev/null
if build/flex/control/control train --data "$output/data/data.bin" --output "$output/invalid" --max-optimizer-steps 0 > "$output/invalid.log" 2>&1; then echo 'Zero optimizer limit was accepted.' >&2; exit 1; fi
[[ ! -e "$output/invalid" ]]
echo 'Optimizer limit is deterministic and validates the final partial epoch.'
