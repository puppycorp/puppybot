#!/usr/bin/env bash
# Compare equal-update neutral-drive policies with and without pilot histories.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
base="$project/build/flex/sim/expanded-rooms-v1";root="$base/large-model-v1"
old="$root/incomplete-return-admission-v1";admission="$root/forward-return-admission-v1";initial="$root/neutral-drive-initial-v1";runtime="$root/neutral-drive-runtime-v1/runtime";screen="$root/source/phase-screen-v1"
verify_zero="${PUPPYBOT_FORWARD_RETURN_VERIFY_ZERO:?Frozen zero verifier required}"
capacity="${PUPPYBOT_FORWARD_RETURN_WAIT_RUN:?Previous GPU job required}"
out="${PUPPYBOT_FORWARD_RETURN_TRAIN_OUT:?New output directory required}"
[[ ! -e "$out" ]];mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
for job in "$old/run" "$admission/run" "$initial/run";do [[ "$(< "$job.exit")" == 0 ]];done
while [[ ! -f "$capacity.exit" ]];do [[ -f "$capacity.pid" ]] && kill -0 "$(< "$capacity.pid")" || { echo 'Previous GPU job ended without a status.' >&2;exit 1; };sleep 20;done
printf '%s\n' "$(< "$capacity.exit")" > "$out/prior-gpu-status.txt"
old_data="$old/expanded/data.bin";new_data="$admission/known/expanded/data.bin";old_targets="$old/targets";new_targets="$admission/known/targets";initial_sha="$(sha256sum "$initial/policy/weights.bin" | cut -d' ' -f1)";old_sha="$(sha256sum "$old_data" | cut -d' ' -f1)";new_sha="$(sha256sum "$new_data" | cut -d' ' -f1)"
jq -e --arg old "$old_sha" --arg sha "$new_sha" '.passed and .episodes==358 and .fittingHistories==242 and .validationHistories==116 and .addedTeacherHistories==4 and .incompleteAddedEpisodes==1 and .studentActionsReplayed==4 and .oldDataSHA256==$old and .dataSHA256==$sha and .reusedScenesSameSplit and .existingDataBytePreserved and .existingTargetsBytePreserved and .newHistoriesIndependentlyAudited and .teacherSearchGoalsReconstructed and .teacherLabelsTrainingOnly and .actorInputsUnchanged and (.incompleteEpisodesClaimedSuccessful|not) and (.automaticPromotion|not)' "$admission/coverage.json" > /dev/null
jq -e --arg sha "$old_sha" '.passed and .episodes==354 and .fittingHistories==240 and .validationHistories==114 and .dataSHA256==$sha and .actorInputsUnchanged' "$old/coverage.json" > /dev/null
jq -e --arg sha "$initial_sha" '.passed and .weightsSHA256==$sha and .driveFeedbackValuesZeroed==5 and .contactFeedbackPreserved and .otherWeightsPreserved and .singleFrameForwardChecked and (.trainingPerformed|not)' "$initial/summary.json" > /dev/null
sha256sum -c "$root/neutral-drive-runtime-v1/inputs.sha256" > "$out/runtime-integrity-before.log"
cmp "$runtime/build/flex/control/simulator" "$root/phase-large-tests-v1/runtime/build/flex/control/simulator"
sha256sum "$verify_zero" "$old_data" "$old_targets/targets.bin" "$old_targets/receipt.json" "$old/coverage.json" "$new_data" "$new_targets/targets.bin" "$new_targets/receipt.json" "$admission/coverage.json" "$admission"/audit-{240,241,356,357}/result.json "$initial/policy/weights.bin" "$initial/policy/receipt.json" "$initial/summary.json" "$runtime/build/flex/control/control" "$runtime/build/flex/control/trainer" "$runtime/build/flex/control/large-forward-tests" "$screen/screen-large-model.sh" "$screen/fixture/data/data.bin" > "$out/inputs.sha256"
sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
export PATH="$base/unseen-benchmark-v2/native-path:$PATH" XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1 PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
cd "$runtime"
for kind in baseline candidate;do
    work="$out/$kind";mkdir "$work";data="$old_data";targets="$old_targets";if [[ "$kind" == candidate ]];then data="$new_data";targets="$new_targets";fi
    data_sha="$(sha256sum "$data" | cut -d' ' -f1)";target_sha="$(sha256sum "$targets/targets.bin" | cut -d' ' -f1)"
    ./build/flex/control/control train --initial-policy "$initial/policy" --data "$data" --output "$work/policy" --epochs 1 --batch 2 --learning-rate-micros 100 --seed 203 --checkpoint-every 1 --event-aux --target-heatmap "$targets" --heat-actor --heat-stop-gradient --mirror-augment --large-model --phase-gated --max-optimizer-steps 98 --drop-drive-feedback-milli 1000 > "$work/training.log" 2>&1
    jq -e --arg data "$data_sha" --arg target "$target_sha" --arg initial "$initial_sha" '.dataSHA256==$data and .targetPositionTargetsSHA256==$target and .initialWeightsSHA256==$initial and .memoryWidth==256 and .epochs==1 and .batch==2 and .learningRateMicros==100 and .seed==203 and .maxOptimizerSteps==98 and .phaseGatedNavigation and .sequenceMirrorAugmentation and .heatmapActorGradientDetached and .driveFeedbackDropMilli==1000 and (.memoryPoseAuxiliary|not) and (.taskFeedback|not)' "$work/policy/receipt.json" > /dev/null
    jq -se 'last | .epoch==1 and .optimizerSteps==98 and .driveFeedbackDroppedSequences==196' "$work/policy/curves.jsonl" > /dev/null
    for file in initial.bin first-after.bin weights.bin;do
        "$verify_zero" "$work/policy/$file" "$work/$file-zero.json"
        sha="$(sha256sum "$work/policy/$file" | cut -d' ' -f1)";jq -e --arg sha "$sha" '.passed and .weightsSHA256==$sha and .bytesChecked==15360 and .driveFeedbackValuesZero==5' "$work/$file-zero.json" > /dev/null
    done
    od -An -v -tu8 -N $((196*8)) "$work/policy/first-order.bin" | tr ' ' '\n' | rg '^[0-9]+$' | jq -R 'tonumber' | jq -s '.' > "$work/training-indices.json"
    jq -e 'length==196' "$work/training-indices.json" > /dev/null
    ./build/flex/control/large-forward-tests "$work/policy" "$screen/fixture/data/data.bin" "$work/forward" > "$work/forward.log" 2>&1
    jq -e '.passed and .logitMaxAbsError<0.00001 and .memoryMaxAbsError<0.00001 and .resetBitIdentical' "$work/forward/result.json" > /dev/null
    PUPPYBOT_POLICY="$work/policy" PUPPYBOT_SCREEN_OUTPUT="$work/screen" PUPPYBOT_SCREEN_CASES=observed bash "$screen/screen-large-model.sh" > "$work/screen.log" 2>&1
done
cmp "$out/baseline/policy/initial.bin" "$out/candidate/policy/initial.bin"
jq -e 'any(.==240) and any(.==241)' "$out/candidate/training-indices.json" > /dev/null
for index in 2 15 16 17;do seed=$((9960000+index));for file in case.json environment.bin;do cmp "$out/baseline/screen/$index/$seed/scene/$file" "$out/candidate/screen/$index/$seed/scene/$file";done;done
jq -n --slurpfile a "$out/baseline/screen/summary.json" --slurpfile b "$out/candidate/screen/summary.json" --slurpfile old "$out/baseline/training-indices.json" --slurpfile new "$out/candidate/training-indices.json" --slurpfile curve "$out/candidate/policy/curves.jsonl" '{exploratory:true,episodesPerModel:4,optimizerStepsPerModel:98,sameInitialActorParameters:true,sameSeed:true,seed:203,trainingDataDiffer:true,validationDataDiffer:true,trainingOrdersIdentical:($old[0]==$new[0]),bothNewFittingHistoriesSampled:($new[0]|any(.==240) and any(.==241)),driveFeedbackDropMilli:1000,driveFeedbackRowsStayedZero:true,contactFeedbackPreserved:true,candidateEpochOneSelected:($curve[-1].selected),baseline:$a[0],candidate:$b[0],reservedFinalStillRequired:true,automaticPromotion:false}' > "$out/comparison.json"
jq -e '.baseline.episodes==4 and .candidate.episodes==4 and .sameInitialActorParameters and .sameSeed and .trainingDataDiffer and .validationDataDiffer and .bothNewFittingHistoriesSampled and .driveFeedbackDropMilli==1000 and .driveFeedbackRowsStayedZero and (.automaticPromotion|not)' "$out/comparison.json" > /dev/null
sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
sha256sum -c "$root/neutral-drive-runtime-v1/inputs.sha256" > "$out/runtime-integrity-after.log"
echo 'Forward-return demonstrations compared at equal optimizer updates.'
