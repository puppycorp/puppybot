#!/usr/bin/env bash
# Bind the frozen runtime to numeric, integration and default-compatibility tests.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
root="$project/build/flex/sim/expanded-rooms-v1/large-model-v1"
runtime="$root/contact-weight-tests-v1/runtime";old="$root/return-weight-tests-v1/runtime"
e2e="$root/contact-weight-frozen-e2e-v1";gradients="$root/contact-weight-gradient-result-v1"
out="$root/contact-weight-tests-v1/validation.json"
[[ ! -e "$out" ]]
cmp "$project/build/flex/control/gradient-tests" "$runtime/build/flex/control/gradient-tests"
for file in initial.bin first-gradients.bin first-after.bin last.bin weights.bin;do
    cmp "$e2e/plain/$file" "$e2e/old-plain/$file"
    cmp "$e2e/balanced/$file" "$e2e/repeat/$file"
done
if cmp -s "$e2e/plain/first-gradients.bin" "$e2e/balanced/first-gradients.bin";then echo 'Contact weighting did not change the fixture gradient.' >&2;exit 1;fi
jq -e '.passed and .contactControlWeightChecked and .fullCNNAndGRU and .tensorsChecked>=24 and .maxGradientAbsError<0.001 and .maxAdamAbsError<0.000001' "$gradients/result.json" > /dev/null
jq -e '.contactControlWeightMilli==2000 and .contactControlWeightTrainingOnly and .phaseGatedNavigation and (.taskFeedback|not)' "$e2e/balanced/receipt.json" > /dev/null
jq -n --slurpfile plain "$e2e/plain/curves.jsonl" --slurpfile weighted "$e2e/balanced/curves.jsonl" '$weighted[0].trainingLoss==$plain[0].trainingLoss and $weighted[0].validationLoss==$plain[0].validationLoss and $weighted[-1].optimizerSteps==1' | jq -e . > /dev/null
jq -e '.passed and .logitMaxAbsError<0.00001 and .memoryMaxAbsError<0.00001 and .resetBitIdentical' "$e2e/forward/result.json" > /dev/null
rg -Fq 'invalid contact control weight' "$e2e/invalid.log"
rg -Fq 'contact feedback must be binary' "$e2e/nonbinary/training.log"
sha256sum "$runtime/build/flex/control/control" "$runtime/build/flex/control/trainer" "$runtime/build/flex/control/gradient-tests" "$old/build/flex/control/trainer" "$gradients/result.json" "$e2e/balanced/receipt.json" "$e2e/forward/result.json" "$e2e/plain/last.bin" "$e2e/old-plain/last.bin" "$e2e/balanced/last.bin" "$e2e/repeat/last.bin" > "$root/contact-weight-tests-v1/inputs.sha256"
find "$runtime/build/flex/control/kernels" -type f -print0 | sort -z | xargs -0 sha256sum >> "$root/contact-weight-tests-v1/inputs.sha256"
sha256sum -c "$root/contact-weight-tests-v1/inputs.sha256" > "$root/contact-weight-tests-v1/integrity.log"
jq -n '{passed:true,numericGradientAndMaskTests:true,gpuDeterministic:true,contactWeightedGradientChanged:true,defaultBitIdenticalToPreviousRuntime:true,validationUsesOriginalLoss:true,inferenceParity:true,invalidWeightRejected:true,nonbinaryContactRejected:true,actorInputsUnchanged:true}' > "$out"
echo 'Contact-weighted frozen runtime validation passed.'
