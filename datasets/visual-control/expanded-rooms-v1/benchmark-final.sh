#!/usr/bin/env bash
set -euo pipefail

project="${PUPPYBOT_PROJECT:?Project root is required}"
root="${PUPPYBOT_FINAL_OUTPUT:-$project/build/flex/sim/expanded-rooms-v1/final-benchmark-v1}"
policy="$1";candidate="$2";blackout="$3"
[[ "$blackout" == true || "$blackout" == false ]]
[[ ! -e "$root/$candidate" ]]
export PATH="$root/native-path"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1
expected="$(/usr/bin/sha256sum "$policy/weights.bin" | /usr/bin/cut -d' ' -f1)"
width="$(/usr/bin/jq -r '.memoryWidth // 128' "$policy/receipt.json")"
[[ "$width" == 128 || "$width" == 256 ]]
cd "$root/runtime"
if [[ "$width" == 256 ]]; then ./build/flex/control/control help | /usr/bin/rg -Fq -- '--large-model' || { echo 'Runtime cannot evaluate 256-value policies.' >&2; exit 1; }; fi
attempt() {
    local index="$1"
    local layout=$((10+index/8)) scene=$((index%8)) seed=$((9980000+index))
    local source="$root/scenes/$layout/$scene" destination="$root/$candidate/$index"
    local valid=false returned=false
    local extra=() verify_extra=();if (( layout%2 ));then extra+=(--hidden-target);fi
    if [[ "$width" == 256 ]];then extra+=(--large-model);verify_extra+=(--large-model);fi
    if [[ "$blackout" == true ]];then extra+=(--blackout);verify_extra+=(--blackout);fi
    if ./build/flex/control/control run --policy "$policy" --scene "$source" --output "$destination" --episodes 1 --seed "$seed" --horizon 300 "${extra[@]}" > "$destination.log" 2>&1;then
        /usr/bin/jq -e --arg sha "$expected" --argjson blackout "$blackout" '.complete and .episodes==1 and (.rows|length)==1 and .rows[0].policyWeightsSHA256==$sha and .rows[0].blackout==$blackout and .rows[0].maximumBrickDistanceM==0.35 and (.rows[0].suppliedMap|not) and (.rows[0].taskEventHint|not)' "$destination/summary.json" > /dev/null
        /usr/bin/cmp "$destination/$seed/scene/case.json" "$source/case.json"
        /usr/bin/cmp "$destination/$seed/scene/environment.bin" "$source/environment.bin"
        if ./build/flex/control/control verify --run "$destination/$seed" --policy "$destination/policy" --output "$destination/verified" "${verify_extra[@]}" > "$destination/verified.log" 2>&1;then
            /usr/bin/jq -e --arg sha "$expected" --argjson blackout "$blackout" '.passed and .commandReplayMaxAbsError==0 and .weightsSHA256==$sha and .blackout==$blackout' "$destination/verified/result.json" > /dev/null
            valid=true
        fi
        returned="$(/usr/bin/tail -n 1 "$destination/$seed/decisions.jsonl" | /usr/bin/jq -r '.state.case.passed')"
        /usr/bin/jq --argjson index "$index" --argjson layout "$layout" --argjson scene "$scene" --argjson valid "$valid" --argjson returned "$returned" '.rows[0]+{caseIndex:$index,layoutId:$layout,sceneId:$scene,recordingCompleted:true,auditPassed:$valid,recordedPhysicalReturn:$returned,physicalReturned:($valid and $returned)}' "$destination/summary.json" > "$destination/benchmark-row.json"
    else
        mkdir -p "$destination"
        /usr/bin/jq -n --argjson index "$index" --argjson layout "$layout" --argjson scene "$scene" --arg sha "$expected" '{caseIndex:$index,layoutId:$layout,sceneId:$scene,policyWeightsSHA256:$sha,recordingCompleted:false,auditPassed:false,recordedPhysicalReturn:false,physicalReturned:false,found:false}' > "$destination/benchmark-row.json"
    fi
}
mkdir "$root/$candidate"
for ((wave=0;wave<16;wave+=2));do
    pids=()
    for ((index=wave;index<wave+2;index++));do attempt "$index" & pids+=("$!");done
    status=0
    for pid in "${pids[@]}";do if ! wait "$pid";then status=1;fi;done
    (( status==0 )) || { echo 'Benchmark integrity check failed; preserve all recordings.';exit 1; }
done
/usr/bin/jq -s --arg candidate "$candidate" --argjson blackout "$blackout" '{candidate:$candidate,blackout:$blackout,episodes:length,completedRecordings:(map(select(.recordingCompleted))|length),auditedEpisodes:(map(select(.auditPassed))|length),auditFailures:(map(select(.auditPassed|not))|length),physicalReturns:(map(select(.physicalReturned))|length),auditedApproaches:(map(select(.auditPassed and .found))|length),openReturns:(map(select(.layoutId==10 and .physicalReturned))|length),hiddenReturns:(map(select(.layoutId==11 and .physicalReturned))|length),meanSuccessfulSimulationSeconds:(map(select(.physicalReturned)|.simulationSeconds)|if length>0 then add/length else null end),rows:sort_by(.caseIndex)}' "$root/$candidate/"*/benchmark-row.json > "$root/score-$candidate.json"
/usr/bin/jq -e '.episodes==16 and ([.rows[].caseIndex]|unique|length)==16' "$root/score-$candidate.json" > /dev/null
