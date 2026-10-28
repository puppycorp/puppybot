#!/usr/bin/env bash
# Check the reversal loss together with the neutral-drive large actor.
set -euo pipefail
project="${PUPPYBOT_PROJECT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
runtime="${PUPPYBOT_CONTROL_RUNTIME:-$project}"
output="${1:?New output directory required}"
mkdir "$output";output="$(cd "$output" && pwd)";cd "$runtime"
sha256sum ./build/flex/control/{control,trainer,pose-fixtures,target-fixtures,large-forward-tests} > "$output/runtime-inputs.sha256"
find ./build/flex/control/kernels -type f -print0 | sort -z | xargs -0 -r sha256sum >> "$output/runtime-inputs.sha256"
./build/flex/control/pose-fixtures "$output/data"
./build/flex/control/target-fixtures "$output/data/data.bin" "$output/data/mirrored-data.bin" "$output/targets"
data_sha="$(sha256sum "$output/data/data.bin" | cut -d' ' -f1)"
args=(--data "$output/data/data.bin" --batch 1 --learning-rate-micros 100 --seed 7 --event-aux --target-heatmap "$output/targets/target-0" --heat-actor --heat-stop-gradient --large-model --phase-gated --mirror-augment --drop-drive-feedback-milli 1000 --from-scratch --epochs 1)
for arm in plain regularized repeat;do
    extra=();if [[ "$arm" != plain ]];then extra+=(--reversal-penalty-milli 1000);fi
    ./build/flex/control/control train "${args[@]}" --output "$output/$arm" "${extra[@]}" > "$output/$arm.log" 2>&1
done
for file in initial.bin first-order.bin first-mirror-mask.bin first-feedback-drop-mask.bin;do cmp "$output/plain/$file" "$output/regularized/$file";done
for file in initial.bin first-gradients.bin first-after.bin last.bin weights.bin;do cmp "$output/regularized/$file" "$output/repeat/$file";done
if cmp -s "$output/plain/first-gradients.bin" "$output/regularized/first-gradients.bin";then echo 'Reversal loss did not change masked-feedback gradients.' >&2;exit 1;fi
[[ "$(od -An -tu8 "$output/regularized/first-feedback-drop-mask.bin" | tr -d ' ')" == 1 ]]
[[ "$(od -An -tu8 "$output/regularized/last-validation-feedback-drop-mask.bin" | tr -d ' ')" == 0 ]]
jq -n --slurpfile plain "$output/plain/curves.jsonl" --slurpfile regularized "$output/regularized/curves.jsonl" '$regularized[0].trainingLoss==$plain[0].trainingLoss and $regularized[0].validationLoss==$plain[0].validationLoss and $regularized[1].trainingLoss>$plain[1].trainingLoss and $regularized[-1].optimizerSteps==1 and $regularized[-1].driveFeedbackDroppedSequences==1' | jq -e . > /dev/null
jq -e '.reversalPenaltyMilli==1000 and .driveFeedbackDropMilli==1000 and .driveFeedbackDropTrainingOnly and .phaseGatedNavigation and (.taskFeedback|not)' "$output/regularized/receipt.json" > /dev/null
./build/flex/control/large-forward-tests "$output/regularized" "$output/data/data.bin" "$output/forward" > "$output/forward.log" 2>&1
jq -e '.passed and .logitMaxAbsError<0.00001 and .memoryMaxAbsError<0.00001 and .resetBitIdentical' "$output/forward/result.json" > /dev/null
[[ "$(sha256sum "$output/data/data.bin" | cut -d' ' -f1)" == "$data_sha" ]]
sha256sum -c "$output/runtime-inputs.sha256" > "$output/runtime-integrity.log"
control_sha="$(sha256sum ./build/flex/control/control | cut -d' ' -f1)";trainer_sha="$(sha256sum ./build/flex/control/trainer | cut -d' ' -f1)"
jq -n --arg sha "$data_sha" --arg control "$control_sha" --arg trainer "$trainer_sha" '{passed:true,datasetSHA256:$sha,controlSHA256:$control,trainerSHA256:$trainer,sameInitialWeightsAndOrder:true,feedbackMaskedInTraining:true,validationUnmasked:true,reversalChangesGradients:true,deterministicRepeat:true,inferenceParity:true,trainingOnlyLoss:true}' > "$output/summary.json"
echo 'Reversal loss and feedback masking passed their combined training check.'
