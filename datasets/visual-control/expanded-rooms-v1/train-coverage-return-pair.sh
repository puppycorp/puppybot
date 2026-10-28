#!/usr/bin/env bash
# Matched-update development screen for verified student return interventions.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
base="$project/build/flex/sim/expanded-rooms-v1"
root="$base/large-model-v1"
out="${PUPPYBOT_COVERAGE_RETURN_PAIR_OUT:?New output directory required}"
admission="$root/coverage-return-admission-v1"
baseline="$root/coverage-v2-teacher-admission-v1"
initial="$root/expanded-236-mirrored"
runtime="$root/phase-large-tests-v1/runtime"
source="$root/source/phase-screen-v1"
[[ ! -e "$out" ]]
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
for job in "$baseline/run" "$admission/run";do
    while [[ ! -f "$job.exit" ]];do [[ -f "$job.pid" ]] && kill -0 "$(< "$job.pid")" || { echo "$job ended without a status." >&2;exit 1; }; /usr/bin/sleep 20;done
    [[ "$(< "$job.exit")" == 0 ]] || { echo "$job failed; pair not started." >&2;exit 1; }
done
# Wait for the preceding large-model experiment to leave GPU capacity. Its
# outcome does not decide this same-seed, matched-update comparison.
capacity="$root/return-weight-screen-v1/run"
while [[ ! -f "$capacity.exit" ]];do [[ -f "$capacity.pid" ]] && kill -0 "$(< "$capacity.pid")" || { echo 'Previous training ended without a status.' >&2;exit 1; }; /usr/bin/sleep 20;done
printf '%s\n' "$(< "$capacity.exit")" > "$out/prior-training-status.txt"
old_sha="$(/usr/bin/sha256sum "$baseline/expanded/data.bin" | /usr/bin/cut -d' ' -f1)"
new_sha="$(/usr/bin/sha256sum "$admission/expanded/data.bin" | /usr/bin/cut -d' ' -f1)"
initial_sha="$(/usr/bin/sha256sum "$initial/weights.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$old_sha" '.passed and .episodes==308 and .fittingHistories==217 and .dataSHA256==$sha and .newHistoriesIndependentlyAudited and .actorInputsUnchanged' "$baseline/coverage.json" > /dev/null
count="$(/usr/bin/jq -r '.addedReturnHistories/2' "$admission/coverage.json")"
[[ "$count" == 1 || "$count" == 2 ]]
/usr/bin/jq -e --arg old "$old_sha" --arg sha "$new_sha" --argjson count "$count" '.passed and .episodes==(308+2*$count) and .fittingHistories==(217+$count) and .validationHistories==(91+$count) and .oldDataSHA256==$old and .dataSHA256==$sha and .studentReturnActionsReplayed>=2 and .newHistoriesIndependentlyAudited and .teacherSearchGoalsReconstructed and .teacherLabelsTrainingOnly and .teacherAssisted and .actorInputsUnchanged and (.autonomousWholeEpisodeSuccessClaimed|not)' "$admission/coverage.json" > /dev/null
/usr/bin/sha256sum "$baseline/expanded/data.bin" "$baseline/targets/targets.bin" "$baseline/targets/receipt.json" "$baseline/coverage.json" "$admission/expanded/data.bin" "$admission/targets/targets.bin" "$admission/targets/receipt.json" "$admission/coverage.json" "$initial/weights.bin" "$initial/receipt.json" "$root/phase-screen-v1/gated-initial/weights.bin" "$source/screen-large-model.sh" "$runtime/build/flex/control/control" "$runtime/build/flex/control/trainer" "$runtime/build/flex/control/large-forward-tests" "$source/fixture/data/data.bin" > "$out/inputs.sha256"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
export PATH="$base/unseen-benchmark-v2/native-path:$PATH" XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1 PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
cd "$runtime"
for arm in baseline augmented;do
    corpus="$baseline"; data_sha="$old_sha"; if [[ "$arm" == augmented ]];then corpus="$admission";data_sha="$new_sha";fi
    ./build/flex/control/control train --initial-policy "$initial" --data "$corpus/expanded/data.bin" --output "$out/$arm-policy" --epochs 1 --batch 2 --learning-rate-micros 100 --seed 202 --checkpoint-every 1 --event-aux --target-heatmap "$corpus/targets" --heat-actor --heat-stop-gradient --mirror-augment --large-model --phase-gated --max-optimizer-steps 109 > "$out/$arm-training.log" 2>&1
    /usr/bin/cmp "$initial/weights.bin" "$out/$arm-policy/seed.bin"
    /usr/bin/cmp "$root/phase-screen-v1/gated-initial/weights.bin" "$out/$arm-policy/initial.bin"
    /usr/bin/jq -e --arg data "$data_sha" --arg initial "$initial_sha" '.memoryWidth==256 and .dataSHA256==$data and .initialWeightsSHA256==$initial and .epochs==1 and .batch==2 and .learningRateMicros==100 and .seed==202 and .maxOptimizerSteps==109 and .phaseGatedNavigation and .sequenceMirrorAugmentation and .heatmapActorFeatures and .heatmapActorGradientDetached and (.taskFeedback|not)' "$out/$arm-policy/receipt.json" > /dev/null
    /usr/bin/jq -se 'last | .epoch==1 and .optimizerSteps==109' "$out/$arm-policy/curves.jsonl" > /dev/null
    # The baseline has 217 fitting trips, so its last batch contains one trip.
    expected=218;if [[ "$arm" == baseline ]];then expected=217;fi
    /usr/bin/od -An -v -tu8 -N $((expected*8)) "$out/$arm-policy/first-order.bin" | /usr/bin/tr ' ' '\n' | /usr/bin/rg '^[0-9]+$' | /usr/bin/jq -R 'tonumber' | /usr/bin/jq -s '.' > "$out/$arm-training-indices.json"
    /usr/bin/jq -e --argjson expected "$expected" 'length==$expected and (unique|length)==$expected' "$out/$arm-training-indices.json" > /dev/null
    if [[ "$arm" == augmented ]];then /usr/bin/jq -e --argjson count "$count" '. as $order | all(range(217;217+$count); . as $i | $order|index($i)!=null)' "$out/$arm-training-indices.json" > /dev/null;fi
    ./build/flex/control/large-forward-tests "$out/$arm-policy" "$source/fixture/data/data.bin" "$out/$arm-forward" > "$out/$arm-forward.log" 2>&1
    /usr/bin/jq -e '.passed and .logitMaxAbsError<0.00001 and .memoryMaxAbsError<0.00001 and .resetBitIdentical' "$out/$arm-forward/result.json" > /dev/null
done
for arm in baseline augmented;do
    PUPPYBOT_POLICY="$out/$arm-policy" PUPPYBOT_SCREEN_OUTPUT="$out/$arm-screen" PUPPYBOT_SCREEN_CASES=observed /usr/bin/bash "$source/screen-large-model.sh" > "$out/$arm-screen.log" 2>&1
    /usr/bin/jq -e '.exploratory and .episodes==4' "$out/$arm-screen/summary.json" > /dev/null
done
for index in 2 15 16 17;do
    seed=$((9960000+index))
    for file in case.json environment.bin;do /usr/bin/cmp "$out/baseline-screen/$index/$seed/scene/$file" "$out/augmented-screen/$index/$seed/scene/$file";done
done
/usr/bin/jq -n --argjson count "$count" --slurpfile old "$out/baseline-screen/summary.json" --slurpfile new "$out/augmented-screen/summary.json" --slurpfile oldorder "$out/baseline-training-indices.json" --slurpfile neworder "$out/augmented-training-indices.json" '{exploratory:true,episodesPerModel:4,optimizerStepsPerModel:109,baselineFittingSamples:217,augmentedFittingSamples:218,seed:202,initialWeightsIdentical:true,additionalFittingHistorySeen:(all(range(217;217+$count); . as $i | $neworder[0]|index($i)!=null)),trainingOrdersIdentical:($oldorder[0]==$neworder[0]),shuffleDifferencesLimitCausalInterpretation:true,teacherAssistedTrainingData:true,baseline:$old[0],augmented:$new[0],reservedFinalStillRequired:true,automaticPromotion:false}' > "$out/comparison.json"
/usr/bin/jq -e '.additionalFittingHistorySeen and .baseline.episodes==4 and .augmented.episodes==4' "$out/comparison.json" > /dev/null
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
echo 'Matched-update return-data screen complete; held-out evaluation remains required.'
