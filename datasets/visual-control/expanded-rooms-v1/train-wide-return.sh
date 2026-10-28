#!/usr/bin/env bash
# Compare additional wide return histories with the 350-history baseline.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
base="$project/build/flex/sim/expanded-rooms-v1";root="$base/large-model-v1"
admission="$root/wide-return-admission-v1";baseline="$root/return-reuse-training-v1";old="$root/return-reuse-admission-v1"
initial="$root/expanded-236-mirrored";runtime="$root/phase-large-tests-v1/runtime";screen="$root/source/phase-screen-v1"
capacity="${PUPPYBOT_WIDE_RETURN_TRAIN_WAIT_RUN:?Previous GPU job required}"
out="${PUPPYBOT_WIDE_RETURN_TRAIN_OUT:?New output directory required}"
[[ ! -e "$out" ]];mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
for job in "$admission/run" "$baseline/run";do
    while [[ ! -f "$job.exit" ]];do [[ -f "$job.pid" ]] && kill -0 "$(< "$job.pid")" || { echo "$job ended without a status." >&2;exit 1; };sleep 20;done
    [[ "$(< "$job.exit")" == 0 ]] || { echo "$job failed; training not started." >&2;exit 1; }
done
while [[ ! -f "$capacity.exit" ]];do [[ -f "$capacity.pid" ]] && kill -0 "$(< "$capacity.pid")" || { echo 'Previous GPU job ended without a status.' >&2;exit 1; };sleep 20;done
printf '%s\n' "$(< "$capacity.exit")" > "$out/prior-gpu-status.txt"
data="$admission/expanded/data.bin";targets="$admission/targets";old_data="$old/expanded/data.bin"
data_sha="$(sha256sum "$data" | cut -d' ' -f1)";old_sha="$(sha256sum "$old_data" | cut -d' ' -f1)";target_sha="$(sha256sum "$targets/targets.bin" | cut -d' ' -f1)";old_target_sha="$(sha256sum "$old/targets/targets.bin" | cut -d' ' -f1)";initial_sha="$(sha256sum "$initial/weights.bin" | cut -d' ' -f1)"
added="$(jq -er '.addedReturnHistories | select(.==2 or .==4)' "$admission/coverage.json")";count=$((added/2));total=$((350+added));fit=$((238+count));validation=$((112+count))
jq -e --arg data "$data_sha" --arg old "$old_sha" --argjson total "$total" --argjson fit "$fit" --argjson validation "$validation" --argjson added "$added" '.passed and .episodes==$total and .fittingHistories==$fit and .validationHistories==$validation and .addedReturnHistories==$added and .studentReturnActionsReplayed>=2 and .teacherAssisted and (.autonomousWholeEpisodeSuccessClaimed|not) and .dataSHA256==$data and .oldDataSHA256==$old and .existingDataBytePreserved and .existingTargetsBytePreserved and .newHistoriesIndependentlyAudited and .teacherLabelsTrainingOnly and .actorInputsUnchanged and (.automaticPromotion|not)' "$admission/coverage.json" > /dev/null
jq -e --arg data "$old_sha" --arg target "$old_target_sha" --arg initial "$initial_sha" '.dataSHA256==$data and .targetPositionTargetsSHA256==$target and .initialWeightsSHA256==$initial and .memoryWidth==256 and .epochs==1 and .batch==2 and .learningRateMicros==100 and .seed==202 and .maxOptimizerSteps==98 and .phaseGatedNavigation and .sequenceMirrorAugmentation and .heatmapActorGradientDetached and (.taskFeedback|not)' "$baseline/policy/receipt.json" > /dev/null
jq -se 'last | .epoch==1 and .optimizerSteps==98' "$baseline/policy/curves.jsonl" > /dev/null
sha256sum "$data" "$targets/targets.bin" "$targets/receipt.json" "$admission/coverage.json" "$admission/expanded/report.json" "$admission/audit-fit/result.json" "$admission/audit-validation/result.json" "$old_data" "$old/targets/targets.bin" "$initial/weights.bin" "$baseline/policy/initial.bin" "$baseline/policy/first-order.bin" "$baseline/policy/receipt.json" "$baseline/screen/summary.json" "$runtime/build/flex/control/control" "$runtime/build/flex/control/trainer" "$runtime/build/flex/control/large-forward-tests" "$screen/screen-large-model.sh" "$screen/fixture/data/data.bin" > "$out/inputs.sha256"
sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
export PATH="$base/unseen-benchmark-v2/native-path:$PATH" XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1 PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
cd "$runtime"
./build/flex/control/control train --initial-policy "$initial" --data "$data" --output "$out/policy" --epochs 1 --batch 2 --learning-rate-micros 100 --seed 202 --checkpoint-every 1 --event-aux --target-heatmap "$targets" --heat-actor --heat-stop-gradient --mirror-augment --large-model --phase-gated --max-optimizer-steps 98 > "$out/training.log" 2>&1
cmp "$baseline/policy/initial.bin" "$out/policy/initial.bin"
jq -e --arg data "$data_sha" --arg target "$target_sha" --arg initial "$initial_sha" '.dataSHA256==$data and .targetPositionTargetsSHA256==$target and .initialWeightsSHA256==$initial and .memoryWidth==256 and .epochs==1 and .batch==2 and .learningRateMicros==100 and .seed==202 and .maxOptimizerSteps==98 and .phaseGatedNavigation and .sequenceMirrorAugmentation and .heatmapActorGradientDetached and (.taskFeedback|not)' "$out/policy/receipt.json" > /dev/null
jq -se 'last | .epoch==1 and .optimizerSteps==98' "$out/policy/curves.jsonl" > /dev/null
od -An -v -tu8 -N $((196*8)) "$out/policy/first-order.bin" | tr ' ' '\n' | rg '^[0-9]+$' | jq -R 'tonumber' | jq -s '.' > "$out/training-indices.json"
jq -e --argjson fit "$fit" 'length==196 and (unique|length)==196 and any(.>=238 and .<$fit)' "$out/training-indices.json" > /dev/null
training_orders_identical=false
if cmp -s -n $((196*8)) "$baseline/policy/first-order.bin" "$out/policy/first-order.bin";then training_orders_identical=true;fi
./build/flex/control/large-forward-tests "$out/policy" "$screen/fixture/data/data.bin" "$out/forward" > "$out/forward.log" 2>&1
jq -e '.passed and .logitMaxAbsError<0.00001 and .memoryMaxAbsError<0.00001 and .resetBitIdentical' "$out/forward/result.json" > /dev/null
PUPPYBOT_POLICY="$out/policy" PUPPYBOT_SCREEN_OUTPUT="$out/screen" PUPPYBOT_SCREEN_CASES=observed bash "$screen/screen-large-model.sh" > "$out/screen.log" 2>&1
for index in 2 15 16 17;do seed=$((9960000+index));for file in case.json environment.bin;do cmp "$baseline/screen/$index/$seed/scene/$file" "$out/screen/$index/$seed/scene/$file";done;done
jq -n --argjson same "$training_orders_identical" --argjson fit "$fit" --argjson added "$added" --slurpfile indices "$out/training-indices.json" --slurpfile a "$baseline/screen/summary.json" --slurpfile b "$out/screen/summary.json" '{exploratory:true,episodesPerModel:4,optimizerStepsPerModel:98,initialWeightsIdentical:true,differentTrainingData:true,trainingOrdersIdentical:$same,addedFittingHistoriesSeen:($indices[0]|map(select(.>=238 and .<$fit))|length),teacherAssistedReturnHistories:$added,validationSetsDiffer:true,shuffleAndCheckpointSelectionLimitCausalInterpretation:true,baseline:$a[0],candidate:$b[0],reservedFinalStillRequired:true,automaticPromotion:false}' > "$out/comparison.json"
jq -e '.baseline.episodes==4 and .candidate.episodes==4 and .initialWeightsIdentical and .addedFittingHistoriesSeen>0 and .validationSetsDiffer and (.automaticPromotion|not)' "$out/comparison.json" > /dev/null
sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
echo 'Wide-return corpus and baseline compared at equal optimizer updates.'
