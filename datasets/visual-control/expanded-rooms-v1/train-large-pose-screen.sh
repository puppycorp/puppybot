#!/usr/bin/env bash
# Add a training-only pose readout to the same 316-history policy and sampling.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
base="$project/build/flex/sim/expanded-rooms-v1";root="$base/large-model-v1"
admission="$root/coverage-v2-student-admission-v1";baseline="$root/coverage-v2-student-training-v1"
pose="$root/memory-pose-316-v2";seed="$root/phase-screen-v1/gated-initial"
runtime="$root/large-pose-tests-v1/runtime";tests="$root/large-pose-tests-v1"
screen="$root/source/phase-screen-v1";core="$root/large-pose-screen-source-v1/compare-pose-initial"
out="${PUPPYBOT_LARGE_POSE_SCREEN_OUT:?New output directory required}"
[[ ! -e "$out" ]];mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
for job in "$admission/run" "$baseline/run" "$pose/run";do
    while [[ ! -f "$job.exit" ]];do [[ -f "$job.pid" ]] && kill -0 "$(< "$job.pid")" || { echo "$job ended without a status." >&2;exit 1; };sleep 20;done
    [[ "$(< "$job.exit")" == 0 ]] || { echo "$job failed; pose training not started." >&2;exit 1; }
done
capacity="$root/contact-weight-screen-v1/run"
while [[ ! -f "$capacity.exit" ]];do [[ -f "$capacity.pid" ]] && kill -0 "$(< "$capacity.pid")" || { echo 'Previous training ended without a status.' >&2;exit 1; };sleep 20;done
printf '%s\n' "$(< "$capacity.exit")" > "$out/prior-training-status.txt"
data="$admission/expanded/data.bin";targets="$admission/targets";pose_targets="$pose/targets"
data_sha="$(sha256sum "$data" | cut -d' ' -f1)";target_sha="$(sha256sum "$targets/targets.bin" | cut -d' ' -f1)";pose_sha="$(sha256sum "$pose_targets/targets.bin" | cut -d' ' -f1)";seed_sha="$(sha256sum "$seed/weights.bin" | cut -d' ' -f1)"
jq -e --arg sha "$data_sha" '.passed and .episodes==316 and .fittingHistories==221 and .validationHistories==95 and .dataSHA256==$sha and .newHistoriesIndependentlyAudited and .actorInputsUnchanged' "$admission/coverage.json" > /dev/null
jq -e --arg sha "$data_sha" --arg pose "$pose_sha" '.passed and .verifiedAgainstPhysicalTrace and .preActionRGBAndFeedbackMatched and .inverseTransformChecked and .sourceFilesStableDuringVerification and .actorInputsUnchanged and .episodes==316 and .sourceDataSHA256==$sha and .targetsSHA256==$pose' "$pose_targets/receipt.json" > /dev/null
jq -e --arg data "$data_sha" --arg target "$target_sha" '.dataSHA256==$data and .targetPositionTargetsSHA256==$target and .memoryWidth==256 and .seed==202 and .batch==2 and .epochs==1 and .maxOptimizerSteps==98 and .phaseGatedNavigation and .sequenceMirrorAugmentation and .heatmapActorGradientDetached and (.memoryPoseAuxiliary|not) and (.taskFeedback|not)' "$baseline/policy/receipt.json" > /dev/null
jq -e '.passed and .fullNetworkPoseGradientsChecked and .largeActorInitialTensorsPreserved and .onlyPoseHeadAdded and .exportedInferenceParity and .defaultTrainingBitIdentical and .incorrectCoreAndTraceRejected and .physicalPoseTargetsPilotChecked and .actorInputsUnchanged' "$tests/validation.json" > /dev/null
cmp "$seed/weights.bin" "$baseline/policy/initial.bin"
cmp "$core" "$runtime/build/flex/control/compare-pose-initial"
sha256sum -c "$tests/inputs.sha256" > "$out/tests-integrity.log"
sha256sum "$data" "$targets/targets.bin" "$targets/receipt.json" "$admission/coverage.json" "$pose_targets/targets.bin" "$pose_targets/receipt.json" "$pose_targets/sources.json" "$seed/weights.bin" "$seed/receipt.json" "$baseline/policy/initial.bin" "$baseline/policy/last.bin" "$baseline/policy/first-order.bin" "$baseline/policy/first-mirror-mask.bin" "$baseline/policy/receipt.json" "$baseline/screen/summary.json" "$tests/validation.json" "$core" "$runtime/build/flex/control/control" "$runtime/build/flex/control/trainer" "$runtime/build/flex/control/large-forward-tests" "$screen/screen-large-model.sh" "$screen/fixture/data/data.bin" > "$out/inputs.sha256"
sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
export PATH="$base/unseen-benchmark-v2/native-path:$PATH" XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1 PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
cd "$runtime"
./build/flex/control/control train --initial-policy "$seed" --data "$data" --output "$out/policy" --epochs 1 --batch 2 --learning-rate-micros 100 --seed 202 --checkpoint-every 1 --event-aux --target-heatmap "$targets" --heat-actor --heat-stop-gradient --mirror-augment --large-model --phase-gated --max-optimizer-steps 98 --memory-pose "$pose_targets" > "$out/training.log" 2>&1
"$core" "$baseline/policy/initial.bin" "$out/policy/initial.bin" "$out/initial-comparison.json"
jq -e '.passed and .allOriginalParametersByteIdentical and .addedPoseHeadOnly and .memoryWidth==256 and .addedPoseParameters==1028' "$out/initial-comparison.json" > /dev/null
for file in first-order.bin first-mirror-mask.bin;do cmp "$baseline/policy/$file" "$out/policy/$file";done
if "$core" "$baseline/policy/last.bin" "$out/policy/last.bin" "$out/unchanged-core.json" > "$out/core-change.log" 2>&1;then echo 'Pose auxiliary did not change existing trained tensors.' >&2;exit 1;fi
rg -Fq 'original checkpoint tensor changed' "$out/core-change.log"
jq -e --arg data "$data_sha" --arg target "$target_sha" --arg pose "$pose_sha" --arg initial "$seed_sha" '.dataSHA256==$data and .targetPositionTargetsSHA256==$target and .memoryPoseTargetsSHA256==$pose and .initialWeightsSHA256==$initial and .memoryPoseAuxiliary and .memoryWidth==256 and .phaseGatedNavigation and .maxOptimizerSteps==98 and (.taskFeedback|not)' "$out/policy/receipt.json" > /dev/null
jq -se 'last | .epoch==1 and .optimizerSteps==98' "$out/policy/curves.jsonl" > /dev/null
./build/flex/control/large-forward-tests "$out/policy" "$screen/fixture/data/data.bin" "$out/forward" > "$out/forward.log" 2>&1
jq -e '.passed and .logitMaxAbsError<0.00001 and .memoryMaxAbsError<0.00001 and .resetBitIdentical' "$out/forward/result.json" > /dev/null
PUPPYBOT_POLICY="$out/policy" PUPPYBOT_SCREEN_OUTPUT="$out/screen" PUPPYBOT_SCREEN_CASES=observed bash "$screen/screen-large-model.sh" > "$out/screen.log" 2>&1
for index in 2 15 16 17;do case_seed=$((9960000+index));for file in case.json environment.bin;do cmp "$baseline/screen/$index/$case_seed/scene/$file" "$out/screen/$index/$case_seed/scene/$file";done;done
jq -n --slurpfile baseline "$baseline/screen/summary.json" --slurpfile candidate "$out/screen/summary.json" '{exploratory:true,episodesPerModel:4,optimizerStepsPerModel:98,sameTrainingData:true,initialActorTensorsIdentical:true,trainingOrdersIdentical:true,firstMirrorMasksIdentical:true,poseTargetsTrainingOnly:true,validationLossIncludesPoseAuxiliary:true,checkpointSelectionMayDiffer:true,baseline:$baseline[0],candidate:$candidate[0],reservedFinalStillRequired:true,automaticPromotion:false}' > "$out/comparison.json"
jq -e '.baseline.episodes==4 and .candidate.episodes==4 and .initialActorTensorsIdentical and .trainingOrdersIdentical and .firstMirrorMasksIdentical' "$out/comparison.json" > /dev/null
sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
echo 'Large-model pose supervision and baseline evaluated on four matching development cases.'
