#!/usr/bin/env bash
set -euo pipefail
project="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$project"
data="${1:?A demonstration fixture is required}"
out="${2:?A new output directory is required}"
mkdir "$out"
out="$(cd "$out" && pwd)"
control="$project/build/flex/control/control"
for arm in default one; do
    extra=(); if [[ "$arm" == one ]]; then extra+=(--stop-weight-one); fi
    "$control" train --data "$data" --output "$out/$arm" --epochs 1 --batch 1 --learning-rate-micros 100 --seed 7 --from-scratch --categorical "${extra[@]}" > "$out/$arm.log" 2>&1
done
cmp "$out/default/initial.bin" "$out/one/initial.bin"
if cmp -s "$out/default/first-gradients.bin" "$out/one/first-gradients.bin"; then echo 'Stop weight did not affect gradients.' >&2; exit 1; fi
jq -e '.stopLossWeight==5 and (.taskFeedback|not)' "$out/default/receipt.json" > /dev/null
jq -e '.stopLossWeight==1 and (.taskFeedback|not)' "$out/one/receipt.json" > /dev/null
if "$control" run --output "$out/rejected-run" --stop-weight-one > "$out/rejected-run.log" 2>&1; then echo 'Inference accepted a training loss flag.' >&2; exit 1; fi
[[ ! -e "$out/rejected-run" && "$(< "$out/rejected-run.log")" == *'stop weight is training-only'* ]]
if "$control" train --output "$out/rejected-duplicate" --stop-weight-one --stop-weight-one > "$out/rejected-duplicate.log" 2>&1; then echo 'Duplicate stop weight accepted.' >&2; exit 1; fi
[[ ! -e "$out/rejected-duplicate" && "$(< "$out/rejected-duplicate.log")" == *'duplicate stop weight option'* ]]
jq -n '{passed:true,runtime:"Flexscript/Pup CUDA",sameInitialWeights:true,stopWeightChangedGradients:true,receiptsAndTrainingOnlyBoundaryChecked:true,taskPerformanceNotImplied:true}' > "$out/result.json"
echo 'Native stop-loss weighting contracts passed.'
