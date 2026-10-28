#!/usr/bin/env bash
# Compare longer training with the same 316-history starting point and seed.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
base="$project/build/flex/sim/expanded-rooms-v1";root="$base/large-model-v1"
admission="$root/coverage-v2-student-admission-v1";baseline="$root/coverage-v2-student-training-v1"
initial="$root/expanded-236-mirrored";runtime="$root/phase-large-tests-v1/runtime";screen="$root/source/phase-screen-v1"
capacity="${PUPPYBOT_LONGER_316_WAIT_RUN:?Previous training run required}"
out="${PUPPYBOT_LONGER_316_OUT:?New output directory required}"
[[ ! -e "$out" ]];mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
for job in "$admission/run" "$baseline/run";do
    while [[ ! -f "$job.exit" ]];do [[ -f "$job.pid" ]] && kill -0 "$(< "$job.pid")" || { echo "$job ended without a status." >&2;exit 1; };sleep 20;done
    [[ "$(< "$job.exit")" == 0 ]] || { echo "$job failed; training not started." >&2;exit 1; }
done
# Wait for GPU capacity, without treating the preceding experiment's outcome as
# evidence for this experiment. The queue owner must start that job first.
while [[ ! -f "$capacity.exit" ]];do [[ -f "$capacity.pid" ]] && kill -0 "$(< "$capacity.pid")" || { echo 'Previous training ended without a status.' >&2;exit 1; };sleep 20;done
printf '%s\n' "$(< "$capacity.exit")" > "$out/prior-training-status.txt"
data="$admission/expanded/data.bin";targets="$admission/targets"
data_sha="$(sha256sum "$data" | cut -d' ' -f1)";target_sha="$(sha256sum "$targets/targets.bin" | cut -d' ' -f1)";initial_sha="$(sha256sum "$initial/weights.bin" | cut -d' ' -f1)"
jq -e --arg sha "$data_sha" '.passed and .episodes==316 and .fittingHistories==221 and .validationHistories==95 and .dataSHA256==$sha and .newHistoriesIndependentlyAudited and .teacherLabelsTrainingOnly and .actorInputsUnchanged' "$admission/coverage.json" > /dev/null
jq -e --arg data "$data_sha" --arg target "$target_sha" --arg initial "$initial_sha" '.dataSHA256==$data and .targetPositionTargetsSHA256==$target and .initialWeightsSHA256==$initial and .memoryWidth==256 and .seed==202 and .batch==2 and .epochs==1 and .learningRateMicros==100 and .maxOptimizerSteps==98 and .phaseGatedNavigation and .sequenceMirrorAugmentation and .heatmapActorGradientDetached and (.taskFeedback|not)' "$baseline/policy/receipt.json" > /dev/null
jq -se 'last | .epoch==1 and .optimizerSteps==98' "$baseline/policy/curves.jsonl" > /dev/null
sha256sum "$data" "$targets/targets.bin" "$targets/receipt.json" "$admission/coverage.json" "$initial/weights.bin" "$initial/receipt.json" "$baseline/policy/initial.bin" "$baseline/policy/first-order.bin" "$baseline/policy/first-mirror-mask.bin" "$baseline/policy/first-gradients.bin" "$baseline/policy/first-after.bin" "$baseline/policy/receipt.json" "$baseline/policy/curves.jsonl" "$baseline/screen/summary.json" "$runtime/build/flex/control/control" "$runtime/build/flex/control/trainer" "$runtime/build/flex/control/large-forward-tests" "$screen/screen-large-model.sh" "$screen/fixture/data/data.bin" > "$out/inputs.sha256"
sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
export PATH="$base/unseen-benchmark-v2/native-path:$PATH" XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1 PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
cd "$runtime"
./build/flex/control/control train --initial-policy "$initial" --data "$data" --output "$out/policy" --epochs 10 --batch 2 --learning-rate-micros 100 --seed 202 --checkpoint-every 1 --event-aux --target-heatmap "$targets" --heat-actor --heat-stop-gradient --mirror-augment --large-model --phase-gated --max-optimizer-steps 1110 > "$out/training.log" 2>&1
# The same first update verifies both identical sampling and actual optimizer
# behaviour; later epochs intentionally train for more steps.
for file in initial.bin first-order.bin first-mirror-mask.bin first-gradients.bin first-after.bin;do cmp "$baseline/policy/$file" "$out/policy/$file";done
jq -e --arg data "$data_sha" --arg target "$target_sha" --arg initial "$initial_sha" '.dataSHA256==$data and .targetPositionTargetsSHA256==$target and .initialWeightsSHA256==$initial and .memoryWidth==256 and .seed==202 and .batch==2 and .epochs==10 and .learningRateMicros==100 and .maxOptimizerSteps==1110 and .phaseGatedNavigation and .sequenceMirrorAugmentation and .heatmapActorGradientDetached and (.taskFeedback|not)' "$out/policy/receipt.json" > /dev/null
jq -se 'length==11 and (last | .epoch==10 and .optimizerSteps==1110) and .[1].optimizerSteps==111' "$out/policy/curves.jsonl" > /dev/null
./build/flex/control/large-forward-tests "$out/policy" "$screen/fixture/data/data.bin" "$out/forward" > "$out/forward.log" 2>&1
jq -e '.passed and .logitMaxAbsError<0.00001 and .memoryMaxAbsError<0.00001 and .resetBitIdentical' "$out/forward/result.json" > /dev/null
PUPPYBOT_POLICY="$out/policy" PUPPYBOT_SCREEN_OUTPUT="$out/screen" PUPPYBOT_SCREEN_CASES=observed bash "$screen/screen-large-model.sh" > "$out/screen.log" 2>&1
for index in 2 15 16 17;do seed=$((9960000+index));for file in case.json environment.bin;do cmp "$baseline/screen/$index/$seed/scene/$file" "$out/screen/$index/$seed/scene/$file";done;done
jq -n --slurpfile baseline "$baseline/screen/summary.json" --slurpfile candidate "$out/screen/summary.json" --slurpfile curves "$out/policy/curves.jsonl" '{exploratory:true,episodesPerModel:4,sameTrainingData:true,initialWeightsIdentical:true,firstTrainingOrderIdentical:true,firstOptimizerUpdateIdentical:true,baselineOptimizerSteps:98,candidateOptimizerSteps:1110,validationSelectedEpoch:([$curves[]|select(.selected)|.epoch]|last),validationCheckpointSelectionCanDiffer:true,baseline:$baseline[0],candidate:$candidate[0],reservedFinalStillRequired:true,automaticPromotion:false}' > "$out/comparison.json"
jq -e '.baseline.episodes==4 and .candidate.episodes==4 and .firstOptimizerUpdateIdentical and .candidateOptimizerSteps==1110 and (.automaticPromotion|not)' "$out/comparison.json" > /dev/null
sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
echo 'Longer 316-history training and matched four-case screen complete.'
