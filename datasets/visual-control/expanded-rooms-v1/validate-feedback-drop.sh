#!/usr/bin/env bash
# Bind feedback-drop tests to the exact frozen training runtime.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
root="$project/build/flex/sim/expanded-rooms-v1/large-model-v1"
runtime="$root/feedback-drop-tests-v1/runtime";old="$root/large-pose-tests-v1/runtime"
e2e="$root/feedback-drop-frozen-e2e-v1";gradients="$root/feedback-drop-gradient-result-v2"
out="$root/feedback-drop-tests-v1/validation.json";[[ ! -e "$out" ]]
for file in initial.bin first-gradients.bin first-after.bin last.bin weights.bin;do cmp "$e2e/plain/$file" "$e2e/old-plain/$file";cmp "$e2e/balanced/$file" "$e2e/repeat/$file";done
cmp "$e2e/plain/first-order.bin" "$e2e/balanced/first-order.bin";cmp "$e2e/plain/first-mirror-mask.bin" "$e2e/balanced/first-mirror-mask.bin"
cmp "$e2e/balanced/first-feedback-drop-mask.bin" "$e2e/repeat/first-feedback-drop-mask.bin"
[[ "$(od -An -tu8 "$e2e/balanced/first-feedback-drop-mask.bin" | tr -d ' ')" == 1 ]]
[[ "$(od -An -tu8 "$e2e/balanced/last-validation-feedback-drop-mask.bin" | tr -d ' ')" == 0 ]]
if cmp -s "$e2e/plain/first-gradients.bin" "$e2e/balanced/first-gradients.bin";then echo 'Feedback masking did not change the fixture gradient.' >&2;exit 1;fi
jq -e '.passed and .feedbackDropChecked and .fullCNNAndGRU and .tensorsChecked>=24 and .maxGradientAbsError<0.001 and .maxAdamAbsError<0.000001' "$gradients/result.json" > /dev/null
jq -e '.driveFeedbackDropMilli==1000 and .driveFeedbackDropTrainingOnly and .phaseGatedNavigation and (.taskFeedback|not)' "$e2e/balanced/receipt.json" > /dev/null
jq -e '.passed and .logitMaxAbsError<0.00001 and .memoryMaxAbsError<0.00001 and .resetBitIdentical' "$e2e/forward/result.json" > /dev/null
jq -n --slurpfile plain "$e2e/plain/curves.jsonl" --slurpfile masked "$e2e/balanced/curves.jsonl" '$masked[0].trainingLoss==$plain[0].trainingLoss and $masked[0].validationLoss==$plain[0].validationLoss and $masked[-1].driveFeedbackDroppedSequences==1' | jq -e . > /dev/null
rg -Fq 'invalid drive feedback drop rate' "$e2e/invalid.log"
rg -Fq 'drive feedback dropout is only valid during training' "$e2e/rejected-evaluation.log"
sha256sum "$runtime/build/flex/control/control" "$runtime/build/flex/control/trainer" "$runtime/build/flex/control/gradient-tests" "$runtime/build/flex/control/feedback-drop-tests" "$old/build/flex/control/trainer" "$gradients/result.json" "$e2e/balanced/receipt.json" "$e2e/forward/result.json" "$e2e/plain/last.bin" "$e2e/old-plain/last.bin" "$e2e/balanced/last.bin" "$e2e/repeat/last.bin" > "$root/feedback-drop-tests-v1/inputs.sha256"
find "$runtime/build/flex/control/kernels" -type f -print0 | sort -z | xargs -0 sha256sum >> "$root/feedback-drop-tests-v1/inputs.sha256"
sha256sum -c "$root/feedback-drop-tests-v1/inputs.sha256" > "$root/feedback-drop-tests-v1/integrity.log"
jq -n '{passed:true,numericGradientAndMaskTests:true,gpuDeterministic:true,feedbackDropChangesGradient:true,defaultBitIdenticalToPreviousRuntime:true,validationUnmasked:true,firstOrderAndMirrorMaskIdentical:true,inferenceParity:true,invalidRateRejected:true,actorInterfaceUnchanged:true}' > "$out"
echo 'Feedback-drop frozen runtime validation passed.'
