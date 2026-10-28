#!/usr/bin/env bash
set -euo pipefail

# Run only against the frozen workspace and data prepared for this experiment.
project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$project/build/flex/sim/expanded-rooms-v1/large-model-v1"
workspace="$root/workspace"
data="$project/build/flex/sim/expanded-rooms-v1/return-quick-v1/merged-16/data.bin"
targets="$project/build/flex/sim/expanded-rooms-v1/return-quick-v1/targets"
scenes="$project/build/flex/sim/expanded-rooms-v1/unseen-benchmark-v2/scenes"
export PATH="$project/build/flex/sim/expanded-rooms-v1/unseen-benchmark-v2/native-path"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1

[[ ! -e "$root/small" && ! -e "$root/large" && ! -e "$root/benchmark" ]]
cd "$workspace"
/usr/bin/sha256sum "$data" "$targets/targets.bin" "$targets/receipt.json" build/flex/control/trainer build/flex/control/policy-categorical-heat build/flex/control/policy-categorical-heat-large build/flex/control/simulator ../runtime/control > "$root/comparison-inputs.sha256"
/usr/bin/find "$scenes/18" "$scenes/19" -type f -print0 | /usr/bin/sort -z | /usr/bin/xargs -0 /usr/bin/sha256sum >> "$root/comparison-inputs.sha256"
/usr/bin/sha256sum build/flex/control/kernels/*.ptx flex/control/model-categorical-heat*.pup build/flex/pixel-control-categorical-heat*-model.flex >> "$root/comparison-inputs.sha256"
for arm in small large; do
    extra=(); if [[ "$arm" == large ]]; then extra+=(--large-model); fi
    ../runtime/control train --data "$data" --output "$root/$arm" --epochs 20 --batch 2 --learning-rate-micros 100 --seed 197 --checkpoint-every 1 --from-scratch --categorical --event-aux --target-heatmap "$targets" --heat-actor --heat-stop-gradient "${extra[@]}" > "$root/$arm.log" 2>&1
    /usr/bin/jq -e --argjson width "$([[ "$arm" == large ]] && echo 256 || echo 128)" '.memoryWidth==$width and .imageSide==84 and .heatmapActorFeatures and .heatmapActorGradientDetached and .fromScratch' "$root/$arm/receipt.json" > /dev/null
done
/usr/bin/sha256sum -c "$root/comparison-inputs.sha256" > "$root/comparison-integrity.log"

attempt() {
    local arm="$1" index="$2"
    local layout=$((18+index/16)) scene=$((index%16)) seed=$((9960000+index))
    local policy="$root/$arm" source="$scenes/$layout/$scene" destination="$root/benchmark/$arm/$index"
    local expected valid=false returned=false
    expected="$(/usr/bin/sha256sum "$policy/weights.bin" | /usr/bin/cut -d' ' -f1)"
    local extra=(); if [[ "$arm" == large ]]; then extra+=(--large-model); fi
    if (( layout%2 )); then extra+=(--hidden-target); fi
    if ../runtime/control run --policy "$policy" --scene "$source" --output "$destination" --episodes 1 --seed "$seed" --horizon 300 "${extra[@]}" > "$destination.log" 2>&1; then
        /usr/bin/jq -e --arg sha "$expected" '.complete and .episodes==1 and .rows[0].policyWeightsSHA256==$sha and .rows[0].maximumBrickDistanceM==0.35 and (.rows[0].suppliedMap|not) and (.rows[0].taskEventHint|not)' "$destination/summary.json" > /dev/null
        /usr/bin/cmp "$destination/$seed/scene/case.json" "$source/case.json"
        /usr/bin/cmp "$destination/$seed/scene/environment.bin" "$source/environment.bin"
        local audit=(); if [[ "$arm" == large ]]; then audit+=(--large-model); fi
        if ../runtime/control verify --run "$destination/$seed" --policy "$destination/policy" --output "$destination/verified" "${audit[@]}" > "$destination/verified.log" 2>&1; then
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

for arm in small large; do
    /usr/bin/mkdir -p "$root/benchmark/$arm"
    for ((wave=0;wave<32;wave+=2)); do
        attempt "$arm" "$wave" & a=$!
        attempt "$arm" "$((wave+1))" & b=$!
        wait "$a"; wait "$b"
    done
    /usr/bin/jq -s --arg arm "$arm" '{arm:$arm,episodes:length,completedRecordings:(map(select(.recordingCompleted))|length),auditedEpisodes:(map(select(.auditPassed))|length),approaches:(map(select(.auditPassed and .found))|length),returns:(map(select(.physicalReturned))|length),openReturns:(map(select(.layoutId==18 and .physicalReturned))|length),hiddenReturns:(map(select(.layoutId==19 and .physicalReturned))|length),meanSuccessfulSimulationSeconds:(map(select(.physicalReturned)|.simulationSeconds)|if length>0 then add/length else null end),rows:sort_by(.caseIndex)}' "$root/benchmark/$arm/"*/benchmark-row.json > "$root/score-$arm.json"
    /usr/bin/jq -e '.episodes==32 and ([.rows[].caseIndex]|unique|length)==32' "$root/score-$arm.json" > /dev/null
done
/usr/bin/sha256sum -c "$root/comparison-inputs.sha256" > "$root/comparison-integrity-after.log"
/usr/bin/jq -n --slurpfile small "$root/score-small.json" --slurpfile large "$root/score-large.json" '{method:"same 16 histories, seed, training settings and 32 development cases; both initialized from scratch",small:$small[0],large:$large[0],heldOutFinalEvaluationStillRequired:true,retainedPolicyOverwritten:false}' > "$root/comparison.json"
