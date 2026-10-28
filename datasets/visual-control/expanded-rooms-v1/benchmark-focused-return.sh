#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
base="$project/build/flex/sim/expanded-rooms-v1"
root="$base/large-model-v1"
training="$root/focused-return-training-v1"
runtime="$root/correction-v3/runtime"
out="$root/focused-return-benchmark-v1"
scenes="$base/unseen-benchmark-v2/scenes"
[[ ! -e "$out" ]]
/usr/bin/mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
while [[ ! -f "$training/run.exit" ]]; do
    [[ -f "$training/run.pid" ]] && kill -0 "$(< "$training/run.pid")" || { echo 'Correction training ended without a status.' >&2; exit 1; }
    /usr/bin/sleep 20
done
[[ "$(< "$training/run.exit")" == 0 ]]
while [[ ! -f "$root/return-benchmark-v1/run.exit" ]]; do
    [[ -f "$root/return-benchmark-v1/run.pid" ]] && kill -0 "$(< "$root/return-benchmark-v1/run.pid")" || { echo 'Baseline benchmark ended without a status.' >&2; exit 1; }
    /usr/bin/sleep 20
done
[[ "$(< "$root/return-benchmark-v1/run.exit")" == 0 ]]
policy="$training/policy"
sha="$(/usr/bin/sha256sum "$policy/weights.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$sha" '.memoryWidth==256 and .weightsSHA256==$sha and (.taskFeedback|not)' "$policy/receipt.json" > /dev/null
/usr/bin/jq -e '.episodes==32 and .completedRecordings==32 and .auditedEpisodes==32' "$root/return-benchmark-v1/score.json" > /dev/null
cd "$root/workspace"
/usr/bin/sha256sum -c "$root/comparison-inputs.sha256" > "$out/scenes-integrity-before.log"
/usr/bin/cmp "$runtime/build/flex/control/simulator" build/flex/control/simulator
/usr/bin/sha256sum "$policy/weights.bin" "$policy/policy" "$policy/receipt.json" "$runtime/build/flex/control/control" "$runtime/build/flex/control/simulator" "$root/runtime/measure-brick-distance" "$root/return-benchmark-v1/score.json" > "$out/inputs.sha256"
export PATH="$base/unseen-benchmark-v2/native-path"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1
cd "$runtime"
attempt() {
    local index="$1"
    local layout=$((18+index/16)) scene=$((index%16)) seed=$((9960000+index))
    local source="$scenes/$layout/$scene" destination="$out/$index" valid=false returned=false
    local extra=(--large-model); if (( layout%2 )); then extra+=(--hidden-target); fi
    if ./build/flex/control/control run --policy "$policy" --scene "$source" --output "$destination" --episodes 1 --seed "$seed" --horizon 300 "${extra[@]}" > "$destination.log" 2>&1; then
        /usr/bin/jq -e --arg sha "$sha" '.complete and .episodes==1 and .rows[0].policyWeightsSHA256==$sha and .rows[0].maximumBrickDistanceM==0.35 and (.rows[0].suppliedMap|not) and (.rows[0].taskEventHint|not)' "$destination/summary.json" > /dev/null
        /usr/bin/cmp "$destination/$seed/scene/case.json" "$source/case.json"
        /usr/bin/cmp "$destination/$seed/scene/environment.bin" "$source/environment.bin"
        if ./build/flex/control/control verify --run "$destination/$seed" --policy "$destination/policy" --output "$destination/verified" --large-model > "$destination/verified.log" 2>&1; then
            /usr/bin/jq -e --arg sha "$sha" '.passed and .commandReplayMaxAbsError==0 and .weightsSHA256==$sha' "$destination/verified/result.json" > /dev/null
            valid=true
        fi
        "$root/runtime/measure-brick-distance" "$destination/$seed" "$destination/distance" > "$destination/distance.log"
        returned="$(/usr/bin/tail -n 1 "$destination/$seed/decisions.jsonl" | /usr/bin/jq -r '.state.case.passed')"
        /usr/bin/jq --slurpfile distance "$destination/distance/result.json" --argjson index "$index" --argjson layout "$layout" --argjson valid "$valid" --argjson returned "$returned" '.rows[0]+{caseIndex:$index,layoutId:$layout,recordingCompleted:true,auditPassed:$valid,physicalReturned:($valid and $returned),closestBrickDistanceM:$distance[0].closestPlanarBaseToBrickM}' "$destination/summary.json" > "$destination/benchmark-row.json"
    else
        /usr/bin/mkdir -p "$destination"
        /usr/bin/jq -n --argjson index "$index" --argjson layout "$layout" '{caseIndex:$index,layoutId:$layout,recordingCompleted:false,auditPassed:false,physicalReturned:false,found:false,closestBrickDistanceM:null}' > "$destination/benchmark-row.json"
    fi
}
for ((wave=0;wave<32;wave+=2)); do
    attempt "$wave" & a=$!
    attempt "$((wave+1))" & b=$!
    wait "$a"; wait "$b"
done
/usr/bin/jq -s '{episodes:length,completedRecordings:(map(select(.recordingCompleted))|length),auditedEpisodes:(map(select(.auditPassed))|length),approaches:(map(select(.auditPassed and .found))|length),returns:(map(select(.physicalReturned))|length),openReturns:(map(select(.layoutId==18 and .physicalReturned))|length),hiddenReturns:(map(select(.layoutId==19 and .physicalReturned))|length),meanClosestM:(map(select(.auditPassed)|.closestBrickDistanceM)|if length>0 then add/length else null end),meanSuccessfulSimulationSeconds:(map(select(.physicalReturned)|.simulationSeconds)|if length>0 then add/length else null end),rows:sort_by(.caseIndex)}' "$out/"*/benchmark-row.json > "$out/score.json"
/usr/bin/jq -e '.episodes==32 and ([.rows[].caseIndex]|unique|length)==32' "$out/score.json" > /dev/null
cd "$root/workspace"
/usr/bin/sha256sum -c "$root/comparison-inputs.sha256" > "$out/scenes-integrity-after.log"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
/usr/bin/jq -n --slurpfile parent "$root/return-benchmark-v1/score.json" --slurpfile parentDistance "$root/return-benchmark-v1/score.json" --slurpfile candidate "$out/score.json" '{method:"same 32 development cases; same initialization, data and updates, with one fitting return history sampled 20 times per epoch",parent:$parent[0],parentMeanClosestM:$parentDistance[0].meanClosestM,candidate:$candidate[0],passedDevelopmentGate:($candidate[0].auditedEpisodes==32 and $candidate[0].returns>=24 and $candidate[0].openReturns>=8 and $candidate[0].hiddenReturns>=8),reservedFinalStillRequired:true,automaticPromotion:false}' > "$out/comparison.json"
