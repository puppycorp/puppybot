#!/usr/bin/env bash
set -euo pipefail

project="${PUPPYBOT_PROJECT:?Project root is required}"
base="$project/build/flex/sim/expanded-rooms-v1"
root="$base/large-model-v1"
scenes="$base/unseen-benchmark-v2/scenes"
out="$root/expanded-benchmark"
[[ ! -e "$out" && ! -e "$root/expanded-benchmark.exit" ]]
trap 'status=$?; printf "%s\n" "$status" > "$root/expanded-benchmark.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$root/expanded-benchmark.pid"
wait_training() {
    local job="$1"
    while [[ ! -f "$root/$job.exit" ]]; do
        [[ -f "$root/$job.pid" ]] && kill -0 "$(< "$root/$job.pid")" || { echo "$job exited without a status." >&2; exit 1; }
        /usr/bin/sleep 20
    done
    [[ "$(< "$root/$job.exit")" == 0 ]] || { echo "$job failed; benchmark not started." >&2; exit 1; }
}
wait_training expanded-236
export PATH="$base/unseen-benchmark-v2/native-path"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1
cd "$root/workspace"
/usr/bin/sha256sum -c "$root/comparison-inputs.sha256" > "$root/expanded-benchmark-integrity-before.log"
attempt() {
    local arm="$1" index="$2"
    local layout=$((18+index/16)) scene=$((index%16)) seed=$((9960000+index))
    local policy="$root/expanded-236" source="$scenes/$layout/$scene" destination="$out/$arm/$index"
    if [[ "$arm" == mirrored ]]; then policy="$root/expanded-236-mirrored"; fi
    local expected valid=false returned=false
    expected="$(/usr/bin/sha256sum "$policy/weights.bin" | /usr/bin/cut -d' ' -f1)"
    local extra=(--large-model); if (( layout%2 )); then extra+=(--hidden-target); fi
    if ../runtime/control run --policy "$policy" --scene "$source" --output "$destination" --episodes 1 --seed "$seed" --horizon 300 "${extra[@]}" > "$destination.log" 2>&1; then
        /usr/bin/jq -e --arg sha "$expected" '.complete and .episodes==1 and .rows[0].policyWeightsSHA256==$sha and .rows[0].maximumBrickDistanceM==0.35 and (.rows[0].suppliedMap|not) and (.rows[0].taskEventHint|not)' "$destination/summary.json" > /dev/null
        /usr/bin/cmp "$destination/$seed/scene/case.json" "$source/case.json"
        /usr/bin/cmp "$destination/$seed/scene/environment.bin" "$source/environment.bin"
        if ../runtime/control verify --run "$destination/$seed" --policy "$destination/policy" --output "$destination/verified" --large-model > "$destination/verified.log" 2>&1; then
            /usr/bin/jq -e --arg sha "$expected" '.passed and .commandReplayMaxAbsError==0 and .weightsSHA256==$sha' "$destination/verified/result.json" > /dev/null
            valid=true
        fi
        returned="$(/usr/bin/tail -n 1 "$destination/$seed/decisions.jsonl" | /usr/bin/jq -r '.state.case.passed')"
        /usr/bin/jq --argjson index "$index" --argjson layout "$layout" --argjson valid "$valid" --argjson returned "$returned" '.rows[0]+{caseIndex:$index,layoutId:$layout,recordingCompleted:true,auditPassed:$valid,physicalReturned:($valid and $returned)}' "$destination/summary.json" > "$destination/benchmark-row.json"
    else
        /usr/bin/mkdir -p "$destination"
        /usr/bin/jq -n --argjson index "$index" --argjson layout "$layout" '{caseIndex:$index,layoutId:$layout,recordingCompleted:false,auditPassed:false,physicalReturned:false,found:false}' > "$destination/benchmark-row.json"
    fi
}
for arm in expanded mirrored; do
    if [[ "$arm" == mirrored ]]; then
        wait_training expanded-236-mirrored
        /usr/bin/cmp "$root/expanded-236/seed.bin" "$root/expanded-236-mirrored/seed.bin"
    fi
    /usr/bin/mkdir -p "$out/$arm"
    for ((wave=0;wave<32;wave+=2)); do
        attempt "$arm" "$wave" & a=$!
        attempt "$arm" "$((wave+1))" & b=$!
        wait "$a"; wait "$b"
    done
    /usr/bin/jq -s --arg arm "$arm" '{arm:$arm,episodes:length,completedRecordings:(map(select(.recordingCompleted))|length),auditedEpisodes:(map(select(.auditPassed))|length),approaches:(map(select(.auditPassed and .found))|length),returns:(map(select(.physicalReturned))|length),openReturns:(map(select(.layoutId==18 and .physicalReturned))|length),hiddenReturns:(map(select(.layoutId==19 and .physicalReturned))|length),meanSuccessfulSimulationSeconds:(map(select(.physicalReturned)|.simulationSeconds)|if length>0 then add/length else null end),rows:sort_by(.caseIndex)}' "$out/$arm/"*/benchmark-row.json > "$root/score-236-$arm.json"
    /usr/bin/jq -e '.episodes==32 and ([.rows[].caseIndex]|unique|length)==32' "$root/score-236-$arm.json" > /dev/null
done
/usr/bin/sha256sum -c "$root/comparison-inputs.sha256" > "$root/expanded-benchmark-integrity-after.log"
/usr/bin/jq -n --slurpfile expanded "$root/score-236-expanded.json" --slurpfile mirrored "$root/score-236-mirrored.json" '{method:"same 236 histories, initial checkpoint, seed, optimizer settings and 32 development cases; mirrored training only differs by sequence reflection",expanded:$expanded[0],mirrored:$mirrored[0],heldOutFinalEvaluationStillRequired:true,retainedPolicyOverwritten:false}' > "$root/expanded-comparison.json"
