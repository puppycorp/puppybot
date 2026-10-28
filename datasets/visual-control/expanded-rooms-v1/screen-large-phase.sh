#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
base="$project/build/flex/sim/expanded-rooms-v1"
root="$base/large-model-v1"
admission="$root/return-cohort-admission-v2"
initial="$root/expanded-236-mirrored"
baseline="$root/reversal-screen-v1"
runtime="$root/phase-large-tests-v1/runtime"
source="$root/source/phase-screen-v1"
out="$root/phase-screen-v1"
[[ ! -e "$out" ]]
/usr/bin/mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
for job in "$admission/run" "$baseline/run"; do
    while [[ ! -f "$job.exit" ]]; do
        [[ -f "$job.pid" ]] && kill -0 "$(< "$job.pid")" || { echo "$job ended without a status." >&2; exit 1; }
        /usr/bin/sleep 20
    done
    [[ "$(< "$job.exit")" == 0 ]] || { echo "$job failed; phase screen not started." >&2; exit 1; }
done
data="$admission/expanded/data.bin"; targets="$admission/targets"
data_sha="$(/usr/bin/sha256sum "$data" | /usr/bin/cut -d' ' -f1)"
initial_sha="$(/usr/bin/sha256sum "$initial/weights.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$data_sha" '.passed and .episodes==264 and .dataSHA256==$sha and .newHistoriesIndependentlyAudited and .teacherLabelsTrainingOnly and .actorInputsUnchanged' "$admission/coverage.json" > /dev/null
/usr/bin/jq -e --arg data "$data_sha" --arg initial "$initial_sha" '.dataSHA256==$data and .initialWeightsSHA256==$initial and .memoryWidth==256 and .epochs==1 and .batch==2 and .learningRateMicros==100 and .seed==197 and .sequenceMirrorAugmentation and .heatmapActorGradientDetached and (.taskFeedback|not)' "$baseline/plain-policy/receipt.json" > /dev/null
/usr/bin/jq -se 'last | .epoch==1 and .optimizerSteps==98' "$baseline/plain-policy/curves.jsonl" > /dev/null
/usr/bin/jq -e '.exploratory and .episodes==4' "$baseline/plain-screen/summary.json" > /dev/null
/usr/bin/sha256sum "$data" "$targets/targets.bin" "$targets/receipt.json" "$initial/weights.bin" "$initial/receipt.json" "$baseline/plain-policy/receipt.json" "$baseline/plain-screen/summary.json" "$runtime/build/flex/control/control" "$runtime/build/flex/control/trainer" "$runtime/build/flex/control/policy-categorical-heat-phase-large" "$runtime/build/flex/control/large-phase-initial-tests" "$runtime/build/flex/control/large-forward-tests" "$source/screen-large-model.sh" "$source/diagnose-return-progress.sh" "$source/fixture/data/data.bin" "$source/fixture/targets/target-0/targets.bin" "$source/fixture/targets/target-0/receipt.json" > "$out/inputs.sha256"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
export PATH="$base/unseen-benchmark-v2/native-path"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1 PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
cd "$runtime"
./build/flex/control/control train --initial-policy "$initial" --data "$source/fixture/data/data.bin" --output "$out/gated-initial" --epochs 0 --batch 1 --learning-rate-micros 100 --seed 197 --event-aux --target-heatmap "$source/fixture/targets/target-0" --heat-actor --heat-stop-gradient --large-model --phase-gated > "$out/gated-initial.log" 2>&1
./build/flex/control/large-phase-initial-tests "$initial" "$out/gated-initial" "$source/fixture/data/data.bin" "$out/initial-parity" > "$out/initial-parity.log" 2>&1
/usr/bin/jq -e '.passed and .maximumLogitDifference<0.00001 and .maximumMemoryDifference==0 and .actionsIdentical and .actorInputsUnchanged' "$out/initial-parity/result.json" > /dev/null
./build/flex/control/control train --initial-policy "$initial" --data "$data" --output "$out/policy" --epochs 1 --batch 2 --learning-rate-micros 100 --seed 197 --checkpoint-every 1 --event-aux --target-heatmap "$targets" --heat-actor --heat-stop-gradient --mirror-augment --large-model --phase-gated > "$out/training.log" 2>&1
/usr/bin/cmp "$initial/weights.bin" "$out/policy/seed.bin"
/usr/bin/cmp "$out/gated-initial/weights.bin" "$out/policy/initial.bin"
/usr/bin/cmp "$baseline/plain-policy/first-order.bin" "$out/policy/first-order.bin"
/usr/bin/cmp "$baseline/plain-policy/first-mirror-mask.bin" "$out/policy/first-mirror-mask.bin"
/usr/bin/jq -e --arg data "$data_sha" --arg initial "$initial_sha" '.dataSHA256==$data and .initialWeightsSHA256==$initial and .memoryWidth==256 and .phaseGatedNavigation and .heatmapActorFeatures and .heatmapActorGradientDetached and .sequenceMirrorAugmentation and (.taskFeedback|not)' "$out/policy/receipt.json" > /dev/null
/usr/bin/jq -se 'last | .epoch==1 and .optimizerSteps==98' "$out/policy/curves.jsonl" > /dev/null
./build/flex/control/large-forward-tests "$out/policy" "$source/fixture/data/data.bin" "$out/forward" > "$out/forward.log" 2>&1
/usr/bin/jq -e '.passed and .logitMaxAbsError<0.00001 and .memoryMaxAbsError<0.00001 and .resetBitIdentical' "$out/forward/result.json" > /dev/null
PUPPYBOT_POLICY="$out/policy" PUPPYBOT_SCREEN_OUTPUT="$out/screen" PUPPYBOT_SCREEN_CASES=observed /usr/bin/bash "$source/screen-large-model.sh" > "$out/screen.log" 2>&1
for index in 2 15 16 17; do
    seed=$((9960000+index)); run="$out/screen/$index"; prior="$baseline/plain-screen/$index"
    /usr/bin/cmp "$run/$seed/scene/case.json" "$prior/$seed/scene/case.json"
    /usr/bin/cmp "$run/$seed/scene/environment.bin" "$prior/$seed/scene/environment.bin"
    /usr/bin/bash "$source/diagnose-return-progress.sh" "$run/$seed" "$run/verified/result.json" "$run/return-diagnostic.json"
done
/usr/bin/jq -n --slurpfile plain "$baseline/plain-screen/summary.json" --slurpfile gated "$out/screen/summary.json" '{exploratory:true,selectionNote:"Two cases were selected because an earlier model reached the brick; these are development cases.",episodesPerModel:4,optimizerStepsPerModel:98,warmStartActionsPreserved:true,baseline:$plain[0],gated:$gated[0],independentFinalHoldout:false,automaticPromotion:false}' > "$out/comparison.json"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
