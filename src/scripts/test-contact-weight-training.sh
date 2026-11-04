#!/usr/bin/env bash
set -euo pipefail
project="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
runtime="${PUPPYBOT_CONTROL_RUNTIME:-$project}"
output="${1:?New output directory required}"
mkdir "$output";output="$(cd "$output" && pwd)";cd "$runtime"
./build/flex/control/pose-fixtures "$output/data"
# Set the second fitting frame's contact bit; keep mirrored fixtures aligned.
offset=$((32+4*21168+56+20))
for file in data.bin mirrored-data.bin;do printf '\000\000\200\077' | dd of="$output/data/$file" bs=1 seek="$offset" conv=notrunc status=none;done
./build/flex/control/target-fixtures "$output/data/data.bin" "$output/data/mirrored-data.bin" "$output/targets"
args=(--data "$output/data/data.bin" --batch 1 --learning-rate-micros 100 --seed 7 --event-aux --target-heatmap "$output/targets/target-0" --heat-actor --large-model --phase-gated --from-scratch --epochs 1)
for arm in plain balanced repeat;do
    extra=();if [[ "$arm" != plain ]];then extra+=(--contact-weight-milli 2000);fi
    ./build/flex/control/control train "${args[@]}" --output "$output/$arm" "${extra[@]}" > "$output/$arm.log" 2>&1
done
cmp "$output/plain/initial.bin" "$output/balanced/initial.bin"
for file in initial.bin first-gradients.bin first-after.bin last.bin weights.bin;do cmp "$output/balanced/$file" "$output/repeat/$file";done
if cmp -s "$output/plain/first-gradients.bin" "$output/balanced/first-gradients.bin";then echo 'Contact control weighting did not change gradients.' >&2;exit 1;fi
jq -n --slurpfile plain "$output/plain/curves.jsonl" --slurpfile balanced "$output/balanced/curves.jsonl" '$balanced[0].trainingLoss==$plain[0].trainingLoss and $balanced[0].validationLoss==$plain[0].validationLoss and $balanced[-1].optimizerSteps==1' | jq -e . > /dev/null
jq -e '.contactControlWeightMilli==2000 and .contactControlWeightTrainingOnly and .phaseGatedNavigation and (.taskFeedback|not)' "$output/balanced/receipt.json" > /dev/null
jq -e 'has("contactControlWeightMilli")|not' "$output/plain/receipt.json" > /dev/null
./build/flex/control/large-forward-tests "$output/balanced" "$output/data/data.bin" "$output/forward" > "$output/forward.log" 2>&1
jq -e '.passed and .logitMaxAbsError<0.00001 and .memoryMaxAbsError<0.00001 and .resetBitIdentical' "$output/forward/result.json" > /dev/null
if ./build/flex/control/control train --data "$output/data/data.bin" --output "$output/invalid" --epochs 1 --batch 1 --from-scratch --categorical --contact-weight-milli 999 > "$output/invalid.log" 2>&1;then echo 'An invalid contact control weight was accepted.' >&2;exit 1;fi
rg -Fq 'invalid contact control weight' "$output/invalid.log"
if ./build/flex/control/control evaluate --output "$output/rejected-evaluation" --contact-weight-milli 2000 > "$output/rejected-evaluation.log" 2>&1;then echo 'Contact weighting was accepted for evaluation.' >&2;exit 1;fi
rg -Fq 'contact control weight is only valid during training' "$output/rejected-evaluation.log"
cp "$output/data/data.bin" "$output/nonbinary.bin"
printf '\000\000\000\077' | dd of="$output/nonbinary.bin" bs=1 seek="$offset" conv=notrunc status=none
if ./build/flex/control/control train --data "$output/nonbinary.bin" --output "$output/nonbinary" --epochs 1 --batch 1 --from-scratch --categorical --contact-weight-milli 2000 > "$output/nonbinary.log" 2>&1;then echo 'Nonbinary contact feedback was accepted.' >&2;exit 1;fi
rg -Fq 'contact feedback must be binary' "$output/nonbinary/training.log"
if [[ -n "${PUPPYBOT_OLD_CONTROL_RUNTIME:-}" ]];then
    cd "$PUPPYBOT_OLD_CONTROL_RUNTIME"
    ./build/flex/control/control train "${args[@]}" --output "$output/old-plain" > "$output/old-plain.log" 2>&1
    for file in initial.bin first-gradients.bin first-after.bin last.bin weights.bin;do cmp "$output/old-plain/$file" "$output/plain/$file";done
    echo 'Default training remains bit-identical to the previous runtime.'
fi
echo 'Contact control weighting changes training gradients, preserves validation setup and exports deterministically.'
