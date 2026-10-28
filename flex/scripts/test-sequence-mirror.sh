#!/usr/bin/env bash
set -euo pipefail
project="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$project"
out="${1:?A new output directory is required}"
mkdir "$out"
out="$(cd "$out" && pwd)"
control="$project/build/flex/control/control"
build/flex/control/augmentation-tests build/flex/control/kernels "$out/contracts"
"$control" init --categorical --output "$out/initial" --seed 7 > "$out/init.log" 2>&1
for arm in plain manual augmented repeated; do
    data="$out/contracts/original.bin"
    if [[ "$arm" == manual ]]; then data="$out/contracts/mirrored-fit.bin"; fi
    extra=(); if [[ "$arm" == augmented || "$arm" == repeated ]]; then extra+=(--mirror-augment); fi
    "$control" train --initial-policy "$out/initial" --data "$data" --output "$out/$arm" \
        --epochs 1 --batch 2 --learning-rate-micros 100 --seed 101 --checkpoint-every 1 "${extra[@]}" > "$out/$arm.log" 2>&1
done
for artifact in first-gradients.bin first-after.bin last.bin first-order.bin final-order.bin; do
    /usr/bin/cmp "$out/manual/$artifact" "$out/augmented/$artifact"
    /usr/bin/cmp "$out/augmented/$artifact" "$out/repeated/$artifact"
done
if /usr/bin/cmp -s "$out/plain/first-gradients.bin" "$out/augmented/first-gradients.bin"; then
    echo 'Augmentation did not affect the optimizer gradients'; exit 1
fi
[[ "$(/usr/bin/od -An -tu8 "$out/augmented/first-mirror-mask.bin" | /usr/bin/tr -d ' ')" == 1 ]]
/usr/bin/jq -se 'map(select(.epoch==0))|length==2 and (map([.trainingLoss,.validationLoss])|unique|length)==1' "$out/plain/curves.jsonl" "$out/augmented/curves.jsonl" > /dev/null
/usr/bin/jq -se 'map(select(.epoch==0))|length==4 and (map(.validationLoss)|unique|length)==1' "$out/"{plain,manual,augmented,repeated}/curves.jsonl > /dev/null
/usr/bin/jq -se 'group_by(.epoch)|all((map(.validationLoss)|unique|length)==1)' "$out/"{manual,augmented}/curves.jsonl > /dev/null
/usr/bin/jq -se '.[0].mirroredTrainingSequences==0 and .[1].mirroredTrainingSequences==1' "$out/augmented/curves.jsonl" > /dev/null
/usr/bin/jq -e '.sequenceMirrorAugmentation and (.taskFeedback|not) and (.pythonRequired|not)' "$out/augmented/receipt.json" > /dev/null
if "$control" run --output "$out/rejected-run" --mirror-augment > "$out/rejected-run.log" 2>&1; then echo 'Inference accepted a training augmentation flag'; exit 1; fi
[[ ! -e "$out/rejected-run" && "$(< "$out/rejected-run.log")" == *'mirror augmentation is training-only'* ]]
if "$control" train --output "$out/rejected-duplicate" --mirror-augment --mirror-augment > "$out/rejected-duplicate.log" 2>&1; then echo 'Duplicate augmentation flag accepted'; exit 1; fi
[[ ! -e "$out/rejected-duplicate" && "$(< "$out/rejected-duplicate.log")" == *'duplicate mirror augmentation option'* ]]
/usr/bin/jq -n '{passed:true,runtime:"Flexscript/Pup CUDA",pythonRequired:false,explicitlyMirroredDatasetMatchesAugmentedGradientsAndWeights:true,repeatable:true,validationInputsUnchanged:true,initialEvaluationUnaugmented:true,inactiveBatchAndPaddingChecked:true,trainingOnlyCLIEnforced:true}' > "$out/result.json"
echo 'Native sequence mirror optimizer contracts passed.'
