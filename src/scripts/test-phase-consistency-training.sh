#!/usr/bin/env bash
set -euo pipefail
project="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
runtime="${PUPPYBOT_CONTROL_RUNTIME:-$project}"
output="${1:?New output directory required}"
mkdir "$output"
output="$(cd "$output" && pwd)"
cd "$runtime"
./build/flex/control/pose-fixtures "$output/data"
./build/flex/control/target-fixtures "$output/data/data.bin" "$output/data/mirrored-data.bin" "$output/targets"
args=(--data "$output/data/data.bin" --batch 1 --learning-rate-micros 100 --seed 7 --event-aux --target-heatmap "$output/targets/target-0" --heat-actor --large-model --phase-gated --from-scratch --epochs 1)
for arm in plain regularized repeat;do
    extra=();if [[ "$arm" != plain ]];then extra+=(--phase-consistency-milli 1000);fi
    ./build/flex/control/control train "${args[@]}" --output "$output/$arm" "${extra[@]}" > "$output/$arm.log" 2>&1
done
cmp "$output/plain/initial.bin" "$output/regularized/initial.bin"
for file in initial.bin first-gradients.bin first-after.bin last.bin weights.bin;do cmp "$output/regularized/$file" "$output/repeat/$file";done
if cmp -s "$output/plain/first-gradients.bin" "$output/regularized/first-gradients.bin";then echo 'Phase consistency did not change gradients.' >&2;exit 1;fi
jq -n --slurpfile plain "$output/plain/curves.jsonl" --slurpfile regularized "$output/regularized/curves.jsonl" '$regularized[0].trainingLoss==$plain[0].trainingLoss and $regularized[0].validationLoss==$plain[0].validationLoss and $regularized[1].trainingLoss>$plain[1].trainingLoss and $regularized[-1].optimizerSteps==1' | jq -e . > /dev/null
jq -e '.phaseConsistencyMilli==1000 and .phaseGatedNavigation and (.taskFeedback|not)' "$output/regularized/receipt.json" > /dev/null
jq -e 'has("phaseConsistencyMilli")|not' "$output/plain/receipt.json" > /dev/null
./build/flex/control/large-forward-tests "$output/regularized" "$output/data/data.bin" "$output/forward" > "$output/forward.log" 2>&1
jq -e '.passed and .logitMaxAbsError<0.00001 and .memoryMaxAbsError<0.00001 and .resetBitIdentical' "$output/forward/result.json" > /dev/null
if ./build/flex/control/control train --data "$output/data/data.bin" --output "$output/nongated" --epochs 1 --batch 1 --from-scratch --categorical --phase-consistency-milli 1000 > "$output/nongated.log" 2>&1;then echo 'A non-gated model accepted phase consistency.' >&2;exit 1;fi
rg -Fq 'phase consistency requires a phase-gated policy' "$output/nongated.log"
if [[ -n "${PUPPYBOT_OLD_CONTROL_RUNTIME:-}" ]];then
    cd "$PUPPYBOT_OLD_CONTROL_RUNTIME"
    ./build/flex/control/control train "${args[@]}" --output "$output/old-plain" > "$output/old-plain.log" 2>&1
    for file in initial.bin first-gradients.bin first-after.bin last.bin weights.bin;do cmp "$output/old-plain/$file" "$output/plain/$file";done
    echo 'Default training is bit-identical to the previous runtime.'
fi
echo 'Phase consistency is deterministic, changes gradients, rejects non-gated models and exports the gated model.'
