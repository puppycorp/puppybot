#!/usr/bin/env bash
# Matched-update development screen for the added student search histories.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
base="$project/build/flex/sim/expanded-rooms-v1"
root="$base/large-model-v1"
out="${PUPPYBOT_GATED_PAIR_OUT:?New output directory required}"
admission="$root/gated-search-admission-v1"
baseline="$root/return-cohort-admission-v3"
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
old_sha="$(/usr/bin/sha256sum "$baseline/expanded/data.bin" | /usr/bin/cut -d' ' -f1)"
new_sha="$(/usr/bin/sha256sum "$admission/expanded/data.bin" | /usr/bin/cut -d' ' -f1)"
initial_sha="$(/usr/bin/sha256sum "$initial/weights.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$old_sha" '.passed and .episodes==280 and .fittingHistories==203 and .dataSHA256==$sha' "$baseline/coverage.json" > /dev/null
/usr/bin/jq -e --arg old "$old_sha" --arg sha "$new_sha" '.passed and .episodes==282 and .fittingHistories==204 and .oldDataSHA256==$old and .dataSHA256==$sha and .addedSearchHistories==2 and .studentSearchActionsReplayed==240 and .newHistoriesIndependentlyAudited and .actorInputsUnchanged' "$admission/coverage.json" > /dev/null
/usr/bin/sha256sum "$baseline/expanded/data.bin" "$baseline/targets/targets.bin" "$baseline/targets/receipt.json" "$baseline/coverage.json" "$admission/expanded/data.bin" "$admission/targets/targets.bin" "$admission/targets/receipt.json" "$admission/coverage.json" "$initial/weights.bin" "$initial/receipt.json" "$root/phase-screen-v1/gated-initial/weights.bin" "$source/screen-large-model.sh" "$runtime/build/flex/control/control" "$runtime/build/flex/control/trainer" "$runtime/build/flex/control/large-forward-tests" "$source/fixture/data/data.bin" > "$out/inputs.sha256"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
export PATH="$base/unseen-benchmark-v2/native-path:$PATH" XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1 PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
cd "$runtime"
for arm in baseline augmented;do
    corpus="$baseline"; data_sha="$old_sha"; if [[ "$arm" == augmented ]];then corpus="$admission";data_sha="$new_sha";fi
    ./build/flex/control/control train --initial-policy "$initial" --data "$corpus/expanded/data.bin" --output "$out/$arm-policy" --epochs 1 --batch 2 --learning-rate-micros 100 --seed 197 --checkpoint-every 1 --event-aux --target-heatmap "$corpus/targets" --heat-actor --heat-stop-gradient --mirror-augment --large-model --phase-gated --max-optimizer-steps 98 > "$out/$arm-training.log" 2>&1
    /usr/bin/cmp "$initial/weights.bin" "$out/$arm-policy/seed.bin"
    /usr/bin/cmp "$root/phase-screen-v1/gated-initial/weights.bin" "$out/$arm-policy/initial.bin"
    /usr/bin/jq -e --arg data "$data_sha" --arg initial "$initial_sha" '.memoryWidth==256 and .dataSHA256==$data and .initialWeightsSHA256==$initial and .epochs==1 and .batch==2 and .learningRateMicros==100 and .seed==197 and .maxOptimizerSteps==98 and .phaseGatedNavigation and .sequenceMirrorAugmentation and .heatmapActorFeatures and .heatmapActorGradientDetached and (.taskFeedback|not)' "$out/$arm-policy/receipt.json" > /dev/null
    /usr/bin/jq -se 'last | .epoch==1 and .optimizerSteps==98' "$out/$arm-policy/curves.jsonl" > /dev/null
    /usr/bin/od -An -v -tu8 -N $((196*8)) "$out/$arm-policy/first-order.bin" | /usr/bin/tr ' ' '\n' | /usr/bin/rg '^[0-9]+$' | /usr/bin/jq -R 'tonumber' | /usr/bin/jq -s '.' > "$out/$arm-training-indices.json"
    /usr/bin/jq -e 'length==196 and (unique|length)==196' "$out/$arm-training-indices.json" > /dev/null
    if [[ "$arm" == augmented ]];then /usr/bin/jq -e 'index(203)!=null' "$out/$arm-training-indices.json" > /dev/null;fi
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
/usr/bin/jq -n --slurpfile old "$out/baseline-screen/summary.json" --slurpfile new "$out/augmented-screen/summary.json" --slurpfile oldorder "$out/baseline-training-indices.json" --slurpfile neworder "$out/augmented-training-indices.json" '{exploratory:true,episodesPerModel:4,optimizerStepsPerModel:98,initialWeightsIdentical:true,additionalFittingHistorySeen:($neworder[0]|index(203)!=null),trainingOrdersIdentical:($oldorder[0]==$neworder[0]),shuffleDifferencesLimitCausalInterpretation:true,baseline:$old[0],augmented:$new[0],reservedFinalStillRequired:true,automaticPromotion:false}' > "$out/comparison.json"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
echo 'Matched-update search-data screen complete; held-out evaluation remains required.'
