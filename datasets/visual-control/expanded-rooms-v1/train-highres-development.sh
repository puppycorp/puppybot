#!/usr/bin/env bash
set -euo pipefail

project="${PUPPYBOT_PROJECT:?Project root is required}"
base="$project/build/flex/sim/expanded-rooms-v1"
dev="$base/highres-training-dev-v1"
out="$base/highres-development-run-v2"
probe="$base/correction-probe-v1"
data="$base/highres-development-data-v1/data.bin"
targets="$dev/targets"
initial="$base/highres-warmstart-v1/weights.bin"
[[ ! -e "$out/run.exit" && ! -e "$out/model" ]]
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
for dependency in contact-training-v1 return-training-v1; do
    while [[ ! -f "$base/$dependency/run.exit" ]]; do
        [[ -f "$base/$dependency/run.pid" ]] && kill -0 "$(< "$base/$dependency/run.pid")" || { echo "$dependency ended without a terminal status" >&2; exit 1; }
        /usr/bin/sleep 10
    done
    [[ "$(< "$base/$dependency/run.exit")" == 0 ]] || { echo "$dependency did not complete successfully" >&2; exit 1; }
done
cd "$project"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1
mkdir "$out/model"
"$out/trainer" "$initial" 1dc057cf885d47fcd2a5dea609c810535bb7f926870fccb414cfc61629234a90 "$out/runtime/build/flex/control/kernels" "$data" "$out/model" 20 2 100 197 --categorical --event-aux --target-heatmap "$targets" --heat-actor --heat-stop-gradient --checkpoint-every 1 --image-128 > "$out/train.log" 2>&1
/usr/bin/jq -s -e 'length==21 and .[-1].epoch==20 and .[-1].optimizerSteps==120' "$out/model/curves.jsonl" > /dev/null
cd "$out/runtime"
"$out/publish" "$initial" "$data" "$targets" "$initial" "$out/initial-policy" 0 2
"$out/publish" "$out/model/weights.bin" "$data" "$targets" "$initial" "$out/selected-policy" 20 2
"$out/publish" "$out/model/epoch-20.bin" "$data" "$targets" "$initial" "$out/epoch20-policy" 20 2
"$out/forward-tests" "$out/selected-policy" "$dev/smoke/data.bin" "$out/forward" > "$out/forward.log" 2>&1
/usr/bin/jq -e '.passed and .logitMaxAbsError==0 and .memoryMaxAbsError==0 and .resetBitIdentical' "$out/forward/result.json" > /dev/null
benchmark() {
    local candidate="$1" policy="$2" index layout scene seed source destination expected returned
    expected="$(/usr/bin/sha256sum "$policy/weights.bin" | /usr/bin/cut -d' ' -f1)"
    mkdir -p "$out/screens/$candidate"
    for index in 0 1 2 3 16 17 18 19; do
        layout=$((18+index/16)); scene=$((index%16)); seed=$((9960000+index))
        source="$probe/scenes/$layout/$scene"; destination="$out/screens/$candidate/$index"
        local extra=(); if (( layout%2 )); then extra+=(--hidden-target); fi
        ./build/flex/control/control run --image-128 --policy "$policy" --scene "$source" --output "$destination" --episodes 1 --seed "$seed" --horizon 300 "${extra[@]}" > "$destination.log" 2>&1
        /usr/bin/jq -e --arg sha "$expected" '.complete and .episodes==1 and (.rows|length)==1 and .rows[0].policyWeightsSHA256==$sha and .rows[0].maximumBrickDistanceM==0.35 and (.rows[0].suppliedMap|not) and (.rows[0].taskEventHint|not)' "$destination/summary.json" > /dev/null
        /usr/bin/cmp "$destination/$seed/scene/case.json" "$source/case.json"
        /usr/bin/cmp "$destination/$seed/scene/environment.bin" "$source/environment.bin"
        ./build/flex/control/control verify --image-128 --run "$destination/$seed" --policy "$destination/policy" --output "$destination/verified" > "$destination/verified.log" 2>&1
        /usr/bin/jq -e --arg sha "$expected" '.passed and .commandReplayMaxAbsError==0 and .weightsSHA256==$sha' "$destination/verified/result.json" > /dev/null
        returned="$(/usr/bin/tail -n 1 "$destination/$seed/decisions.jsonl" | /usr/bin/jq -r '.state.case.passed')"
        /usr/bin/jq --argjson index "$index" --argjson layout "$layout" --argjson scene "$scene" --argjson returned "$returned" '.rows[0]+{caseIndex:$index,layoutId:$layout,sceneId:$scene,recordingCompleted:true,auditPassed:true,recordedPhysicalReturn:$returned,physicalReturned:$returned}' "$destination/summary.json" > "$destination/benchmark-row.json"
    done
    /usr/bin/jq -s --arg candidate "$candidate" '{candidate:$candidate,episodes:length,completedRecordings:(map(select(.recordingCompleted))|length),auditedEpisodes:(map(select(.auditPassed))|length),physicalReturns:(map(select(.physicalReturned))|length),auditedApproaches:(map(select(.found))|length),openReturns:(map(select(.layoutId==18 and .physicalReturned))|length),hiddenReturns:(map(select(.layoutId==19 and .physicalReturned))|length),meanSuccessfulSimulationSeconds:(map(select(.physicalReturned)|.simulationSeconds)|if length>0 then add/length else null end),rows:sort_by(.caseIndex)}' "$out/screens/$candidate/"*/benchmark-row.json > "$out/score-$candidate.json"
    /usr/bin/jq -e '.episodes==8 and .auditedEpisodes==8 and ([.rows[].caseIndex]|unique)==[0,1,2,3,16,17,18,19]' "$out/score-$candidate.json" > /dev/null
}
benchmark initial "$out/initial-policy"
benchmark epoch20 "$out/epoch20-policy"
if /usr/bin/cmp -s "$out/selected-policy/weights.bin" "$out/initial-policy/weights.bin"; then
    /usr/bin/cp "$out/score-initial.json" "$out/score-selected.json"
elif /usr/bin/cmp -s "$out/selected-policy/weights.bin" "$out/epoch20-policy/weights.bin"; then
    /usr/bin/cp "$out/score-epoch20.json" "$out/score-selected.json"
else
    benchmark selected "$out/selected-policy"
fi
cd "$project"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
/usr/bin/jq -n --slurpfile old "$probe/score-screen-return-quick-v1.json" --slurpfile old20 "$probe/score-screen-return-epoch20-v1.json" --slurpfile initial "$out/score-initial.json" --slurpfile selected "$out/score-selected.json" --slurpfile epoch20 "$out/score-epoch20.json" '{exploratory:true,independentHeldOut:false,trainingHistories:16,selection:"development screen; selected checkpoint uses demonstration validation loss",baseline84:$old[0],baseline84Epoch20:$old20[0],initial128:$initial[0],selected128:$selected[0],epoch20128:$epoch20[0],qualifiesForPromotion:false,retainedPolicyOverwritten:false}' > "$out/comparison.json"
echo '128x128 development screen completed; no promotion claim.'
