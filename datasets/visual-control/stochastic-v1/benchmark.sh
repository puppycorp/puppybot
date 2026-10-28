#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
root="${PUPPYBOT_BENCHMARK_ROOT:-$project/build/flex/sim/sequence-mirror-v1}"
runtime="$root/runtime"
policy="$1"; candidate="$2"; suite="$3"; first="$4"; last="$5"
export PATH="$root/models/native-path"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1
expected="$(/usr/bin/sha256sum "$policy/weights.bin" | /usr/bin/cut -d' ' -f1)"
cd "$runtime"
attempt() {
    local index="$1"
    local layout=$((6+index/16)) scene=$((index%16))
    if [[ "$suite" == screen ]]; then if (( index<4 )); then layout=6; scene=$index; else layout=7; scene=$index; fi; fi
    local canonical=$(((layout-6)*16+scene))
    local seed=$((8900000+canonical))
    local source="$project/datasets/visual-control/approach35-v1/artifacts/scenes/$layout/$scene"
    local destination="$root/$suite-$candidate/$index"
    local completed=false valid=false returned=false
    local extra=(); if (( layout%2 )); then extra+=(--hidden-target); fi
    if ./build/flex/control/control run --policy "$policy" --scene "$source" --output "$destination" --episodes 1 --seed "$seed" --horizon 300 "${extra[@]}" > "$destination.log" 2>&1; then
        /usr/bin/jq -e '.complete and .episodes==1 and (.rows|length)==1' "$destination/summary.json" > /dev/null
        completed=true
        /usr/bin/cmp "$destination/$seed/scene/case.json" "$source/case.json"
        /usr/bin/cmp "$destination/$seed/scene/environment.bin" "$source/environment.bin"
        /usr/bin/jq -e --arg sha "$expected" '.rows[0].policyWeightsSHA256==$sha' "$destination/summary.json" > /dev/null
        if ./build/flex/control/control verify --run "$destination/$seed" --policy "$destination/policy" --output "$destination/verified" > "$destination/verified.log" 2>&1; then
            /usr/bin/jq -e --arg sha "$expected" '.passed and .commandReplayMaxAbsError==0 and .weightsSHA256==$sha' "$destination/verified/result.json" > /dev/null
            valid=true
        fi
        returned="$(/usr/bin/tail -n 1 "$destination/$seed/decisions.jsonl" | /usr/bin/jq -r '.state.case.passed')"
        /usr/bin/jq --argjson index "$canonical" --argjson layout "$layout" --argjson scene "$scene" --argjson valid "$valid" --argjson returned "$returned" '.rows[0]+{caseIndex:$index,layoutId:$layout,sceneId:$scene,recordingCompleted:true,auditPassed:$valid,recordedPhysicalReturn:$returned,physicalReturned:($valid and $returned)}' "$destination/summary.json" > "$destination/benchmark-row.json"
    else
        mkdir -p "$destination"
        /usr/bin/jq -n --argjson index "$canonical" --argjson layout "$layout" --argjson scene "$scene" --arg sha "$expected" '{caseIndex:$index,layoutId:$layout,sceneId:$scene,policyWeightsSHA256:$sha,recordingCompleted:false,auditPassed:false,recordedPhysicalReturn:false,physicalReturned:false,found:false}' > "$destination/benchmark-row.json"
    fi
}
mkdir -p "$root/$suite-$candidate"
for (( wave=first;wave<last;wave+=4 )); do
    pids=()
    for (( index=wave;index<wave+4 && index<last;index++ )); do attempt "$index" & pids+=("$!"); done
    status=0
    for pid in "${pids[@]}"; do if ! wait "$pid"; then status=1; fi; done
    if (( status )); then echo 'Benchmark identity or receipt integrity failed; preserve all recordings'; exit 1; fi
done
