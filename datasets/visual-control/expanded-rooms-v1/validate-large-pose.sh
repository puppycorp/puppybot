#!/usr/bin/env bash
# Bind full-network gradients and large-policy export checks to a frozen runtime.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
root="$project/build/flex/sim/expanded-rooms-v1/large-model-v1"
runtime="$root/large-pose-tests-v1/runtime";gradient="$root/large-pose-gradient-result-v2"
test="$root/large-memory-pose-initial-test-v3";plain="$root/large-pose-default-e2e-v1"
targets="$root/memory-pose-preparation-test-v3";out="$root/large-pose-tests-v1/validation.json"
[[ ! -e "$out" ]]
cmp "$project/build/flex/control/gradient-tests" "$runtime/build/flex/control/gradient-tests"
for file in initial.bin first-gradients.bin first-after.bin last.bin weights.bin;do cmp "$plain/plain/$file" "$plain/old-plain/$file";done
jq -e '.passed and .poseAuxiliaryChecked and .fullCNNAndGRU and .parameters==3066453 and .tensorsChecked>=26 and .maxGradientAbsError<0.001 and .maxAdamAbsError<0.000001' "$gradient/result.json" > /dev/null
jq -e '.passed and .memoryWidth==256 and .allOriginalParametersByteIdentical and .addedPoseHeadOnly and .addedPoseParameters==1028' "$test/initial-comparison.json" > /dev/null
jq -e '.passed and .logitMaxAbsError<0.00001 and .memoryMaxAbsError<0.00001 and .resetBitIdentical' "$test/forward/result.json" > /dev/null
jq -e '.memoryPoseAuxiliary and .memoryWidth==256 and .phaseGatedNavigation and (.taskFeedback|not)' "$test/policy/receipt.json" > /dev/null
jq -e '.passed and .verifiedAgainstPhysicalTrace and .preActionRGBAndFeedbackMatched and .inverseTransformChecked and .actorInputsUnchanged' "$targets/targets/receipt.json" > /dev/null
rg -Fq 'original checkpoint tensor changed' "$test/rejected.log"
rg -Fq 'pose target disagrees with physical trace' "$targets/rejected.log"
sha256sum "$runtime/build/flex/control/control" "$runtime/build/flex/control/trainer" "$runtime/build/flex/control/gradient-tests" "$project/build/flex/control/compare-pose-initial" "$gradient/result.json" "$test/initial-comparison.json" "$test/forward/result.json" "$test/policy/receipt.json" "$targets/targets/receipt.json" "$plain/plain/last.bin" "$plain/old-plain/last.bin" > "$root/large-pose-tests-v1/inputs.sha256"
find "$runtime/build/flex/control/kernels" -type f -print0 | sort -z | xargs -0 sha256sum >> "$root/large-pose-tests-v1/inputs.sha256"
sha256sum -c "$root/large-pose-tests-v1/inputs.sha256" > "$root/large-pose-tests-v1/integrity.log"
jq -n '{passed:true,fullNetworkPoseGradientsChecked:true,largeActorInitialTensorsPreserved:true,onlyPoseHeadAdded:true,exportedInferenceParity:true,defaultTrainingBitIdentical:true,incorrectCoreAndTraceRejected:true,physicalPoseTargetsPilotChecked:true,actorInputsUnchanged:true}' > "$out"
echo 'Large-model pose supervision frozen runtime validation passed.'
