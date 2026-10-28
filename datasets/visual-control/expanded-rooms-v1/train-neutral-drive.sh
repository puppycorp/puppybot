#!/usr/bin/env bash
# Retrain the same model and dataset with all drive-feedback inputs neutralized.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
base="$project/build/flex/sim/expanded-rooms-v1";root="$base/large-model-v1"
admission="$root/incomplete-return-admission-v1";baseline="$root/incomplete-return-training-v1";initial="$root/neutral-drive-initial-v1";source="$root/expanded-236-mirrored"
runtime="$root/neutral-drive-runtime-v1/runtime";screen="$root/source/phase-screen-v1"
ablate="${PUPPYBOT_NEUTRAL_TRAIN_ABLATE:?Frozen ablation binary required}"
verify_zero="${PUPPYBOT_NEUTRAL_TRAIN_VERIFY_ZERO:?Frozen zero verifier required}"
capacity="${PUPPYBOT_NEUTRAL_TRAIN_WAIT_RUN:?Previous GPU job required}"
out="${PUPPYBOT_NEUTRAL_TRAIN_OUT:?New output directory required}"
[[ ! -e "$out" ]];mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
for job in "$admission/run" "$baseline/run" "$initial/run";do [[ "$(< "$job.exit")" == 0 ]];done
while [[ ! -f "$capacity.exit" ]];do [[ -f "$capacity.pid" ]] && kill -0 "$(< "$capacity.pid")" || { echo 'Previous GPU job ended without a status.' >&2;exit 1; };sleep 20;done
printf '%s\n' "$(< "$capacity.exit")" > "$out/prior-gpu-status.txt"
data="$admission/expanded/data.bin";targets="$admission/targets";data_sha="$(sha256sum "$data" | cut -d' ' -f1)";target_sha="$(sha256sum "$targets/targets.bin" | cut -d' ' -f1)";source_sha="$(sha256sum "$source/weights.bin" | cut -d' ' -f1)";initial_sha="$(sha256sum "$initial/policy/weights.bin" | cut -d' ' -f1)"
jq -e --arg data "$data_sha" '.passed and .episodes==354 and .fittingHistories==240 and .validationHistories==114 and .dataSHA256==$data and .newHistoriesIndependentlyAudited and .teacherLabelsTrainingOnly and .actorInputsUnchanged and (.automaticPromotion|not)' "$admission/coverage.json" > /dev/null
jq -e --arg parent "$source_sha" --arg sha "$initial_sha" '.passed and .parentWeightsSHA256==$parent and .weightsSHA256==$sha and .driveFeedbackValuesZeroed==5 and .contactFeedbackPreserved and .otherWeightsPreserved and .singleFrameForwardChecked and (.trainingPerformed|not) and (.automaticPromotion|not)' "$initial/summary.json" > /dev/null
jq -e '.passed and .numericGradientAndMaskTests and .gpuDeterministic and .feedbackDropChangesGradient and .defaultBitIdenticalToPreviousRuntime and .validationUnmasked and .firstOrderAndMirrorMaskIdentical and .inferenceParity and .invalidRateRejected and .actorInterfaceUnchanged' "$root/feedback-drop-tests-v1/validation.json" > /dev/null
sha256sum -c "$root/neutral-drive-runtime-v1/inputs.sha256" > "$out/runtime-integrity-before.log"
cmp "$runtime/build/flex/control/simulator" "$root/phase-large-tests-v1/runtime/build/flex/control/simulator"
jq -e --arg data "$data_sha" --arg target "$target_sha" --arg source "$source_sha" '.dataSHA256==$data and .targetPositionTargetsSHA256==$target and .initialWeightsSHA256==$source and .memoryWidth==256 and .epochs==1 and .batch==2 and .learningRateMicros==100 and .seed==202 and .maxOptimizerSteps==98 and .phaseGatedNavigation and .sequenceMirrorAugmentation and .heatmapActorGradientDetached and ((.driveFeedbackDropMilli // 0)==0) and (.taskFeedback|not)' "$baseline/policy/receipt.json" > /dev/null
jq -se 'last | .epoch==1 and .optimizerSteps==98' "$baseline/policy/curves.jsonl" > /dev/null
sha256sum "$ablate" "$verify_zero" "$data" "$targets/targets.bin" "$targets/receipt.json" "$admission/coverage.json" "$source/weights.bin" "$initial/policy/weights.bin" "$initial/policy/receipt.json" "$initial/summary.json" "$baseline/policy/initial.bin" "$baseline/policy/first-order.bin" "$baseline/policy/first-mirror-mask.bin" "$baseline/policy/receipt.json" "$baseline/screen/summary.json" "$runtime/build/flex/control/control" "$runtime/build/flex/control/trainer" "$runtime/build/flex/control/large-forward-tests" "$screen/screen-large-model.sh" "$screen/fixture/data/data.bin" > "$out/inputs.sha256"
sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
export PATH="$base/unseen-benchmark-v2/native-path:$PATH" XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1 PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
cd "$runtime"
./build/flex/control/control train --initial-policy "$initial/policy" --data "$data" --output "$out/policy" --epochs 1 --batch 2 --learning-rate-micros 100 --seed 202 --checkpoint-every 1 --event-aux --target-heatmap "$targets" --heat-actor --heat-stop-gradient --mirror-augment --large-model --phase-gated --max-optimizer-steps 98 --drop-drive-feedback-milli 1000 > "$out/training.log" 2>&1
jq -e --arg data "$data_sha" --arg target "$target_sha" --arg initial "$initial_sha" '.dataSHA256==$data and .targetPositionTargetsSHA256==$target and .initialWeightsSHA256==$initial and .memoryWidth==256 and .epochs==1 and .batch==2 and .learningRateMicros==100 and .seed==202 and .maxOptimizerSteps==98 and .phaseGatedNavigation and .sequenceMirrorAugmentation and .heatmapActorGradientDetached and .driveFeedbackDropMilli==1000 and (.taskFeedback|not)' "$out/policy/receipt.json" > /dev/null
jq -se 'last | .epoch==1 and .optimizerSteps==98 and .driveFeedbackDroppedSequences==196' "$out/policy/curves.jsonl" > /dev/null
"$ablate" "$baseline/policy/initial.bin" "$out/expected-initial.bin" "$out/expected-initial.json" > "$out/expected-initial.log" 2>&1
cmp "$out/expected-initial.bin" "$out/policy/initial.bin";cmp "$baseline/policy/first-order.bin" "$out/policy/first-order.bin";cmp "$baseline/policy/first-mirror-mask.bin" "$out/policy/first-mirror-mask.bin"
for file in initial.bin first-after.bin weights.bin;do
    "$verify_zero" "$out/policy/$file" "$out/$file-zero.json"
    sha="$(sha256sum "$out/policy/$file" | cut -d' ' -f1)";jq -e --arg sha "$sha" '.passed and .weightsSHA256==$sha and .bytesChecked==15360 and .driveFeedbackValuesZero==5' "$out/$file-zero.json" > /dev/null
done
./build/flex/control/large-forward-tests "$out/policy" "$screen/fixture/data/data.bin" "$out/forward" > "$out/forward.log" 2>&1
jq -e '.passed and .logitMaxAbsError<0.00001 and .memoryMaxAbsError<0.00001 and .resetBitIdentical' "$out/forward/result.json" > /dev/null
PUPPYBOT_POLICY="$out/policy" PUPPYBOT_SCREEN_OUTPUT="$out/screen" PUPPYBOT_SCREEN_CASES=observed bash "$screen/screen-large-model.sh" > "$out/screen.log" 2>&1
for index in 2 15 16 17;do seed=$((9960000+index));for file in case.json environment.bin;do cmp "$baseline/screen/$index/$seed/scene/$file" "$out/screen/$index/$seed/scene/$file";done;done
jq -n --slurpfile curve "$out/policy/curves.jsonl" --slurpfile a "$baseline/screen/summary.json" --slurpfile b "$out/screen/summary.json" '{exploratory:true,episodesPerModel:4,sameTrainingData:true,sameValidationData:true,trainingOrdersIdentical:true,firstMirrorMasksIdentical:true,optimizerStepsPerModel:98,onlyInitialDriveFeedbackRowsAblated:true,driveFeedbackDropMilli:1000,driveFeedbackRowsStayedZero:true,contactFeedbackPreserved:true,candidateEpochOneSelected:($curve[-1].selected),baseline:$a[0],candidate:$b[0],reservedFinalStillRequired:true,automaticPromotion:false}' > "$out/comparison.json"
jq -e '.baseline.episodes==4 and .candidate.episodes==4 and .sameTrainingData and .sameValidationData and .trainingOrdersIdentical and .firstMirrorMasksIdentical and .onlyInitialDriveFeedbackRowsAblated and .driveFeedbackDropMilli==1000 and .driveFeedbackRowsStayedZero and (.automaticPromotion|not)' "$out/comparison.json" > /dev/null
sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
sha256sum -c "$root/neutral-drive-runtime-v1/inputs.sha256" > "$out/runtime-integrity-after.log"
echo 'Neutral-drive training and its same-data baseline compared at equal updates.'
