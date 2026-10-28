#!/usr/bin/env bash
# Compare the older small pose model on the large models' 32 development cases.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
base="$project/build/flex/sim/expanded-rooms-v1";root="$base/large-model-v1"
policy="${PUPPYBOT_SMALL_POSE_POLICY:?Frozen small policy required}"
runtime="$root/phase-large-tests-v1/runtime";data="$root/coverage-v2-student-admission-v1/expanded"
baseline="$root/student-only-benchmark-v1/augmented";scenes="$base/unseen-benchmark-v2/scenes"
out="${PUPPYBOT_SMALL_POSE_BENCHMARK_OUT:?New output directory required}"
[[ ! -e "$out" ]];mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
if [[ -n "${PUPPYBOT_SMALL_POSE_WAIT_RUN:-}" ]];then
    prior="$PUPPYBOT_SMALL_POSE_WAIT_RUN"
    while [[ ! -f "$prior.exit" ]];do [[ -f "$prior.pid" ]] && kill -0 "$(< "$prior.pid")" || { echo 'Previous benchmark ended without a status.' >&2;exit 1; };sleep 20;done
    printf '%s\n' "$(< "$prior.exit")" > "$out/prior-benchmark-status.txt"
fi
[[ "$(< "$root/student-only-benchmark-v1/run.exit")" == 0 ]]
sha="$(sha256sum "$policy/weights.bin" | cut -d' ' -f1)";binary_sha="$(sha256sum "$policy/policy" | cut -d' ' -f1)"
jq -e --arg sha "$sha" --arg binary "$binary_sha" '.weightsSHA256==$sha and .binarySHA256==$binary and (.memoryWidth // 128)==128 and .memoryPoseAuxiliary and (.taskFeedback|not)' "$policy/receipt.json" > /dev/null
jq -e '.episodes==32 and .completedRecordings==32 and .auditedEpisodes==32' "$baseline/score.json" > /dev/null
jq -e '.passed and .episodes==316 and .newHistoriesIndependentlyAudited and .existingDataBytePreserved' "$root/coverage-v2-student-admission-v1/coverage.json" > /dev/null
for ((i=0;i<316;i++));do for file in case.json environment.bin;do sha256sum "$data/expert-$i/scene/$file" | tee -a "$out/training-inputs.sha256" | cut -d' ' -f1;done;done > "$out/training-hashes.txt"
for layout in 18 19;do for scene in {0..15};do for file in case.json environment.bin;do
    path="$scenes/$layout/$scene/$file";digest="$(sha256sum "$path" | cut -d' ' -f1)";status=0;rg -Fxq "$digest" "$out/training-hashes.txt" || status=$?
    if (( status==0 ));then echo "Development scene overlaps a training file: $path" >&2;exit 1;fi
    if (( status!=1 ));then echo 'Cannot check prior scene hashes.' >&2;exit "$status";fi
    sha256sum "$path" >> "$out/scene-inputs.sha256"
done;done;done
sha256sum "$policy/weights.bin" "$policy/policy" "$policy/receipt.json" "$runtime/build/flex/control/control" "$runtime/build/flex/control/simulator" "$root/runtime/measure-brick-distance" "$baseline/score.json" > "$out/inputs.sha256"
find "$policy/kernels" -type f -print0 | sort -z | xargs -0 sha256sum >> "$out/inputs.sha256"
sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
sha256sum -c "$out/scene-inputs.sha256" > "$out/scenes-before.log"
cmp "$runtime/build/flex/control/simulator" "$root/workspace/build/flex/control/simulator"
export PATH="$base/unseen-benchmark-v2/native-path:$PATH" XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1 PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
cd "$runtime"
attempt() {
    local index="$1" layout=$((18+$1/16)) scene=$(($1%16)) case_seed=$((9960000+$1))
    local source="$scenes/$layout/$scene" destination="$out/$index" valid=false returned=false
    local extra=();if (( layout%2 ));then extra+=(--hidden-target);fi
    if ./build/flex/control/control run --policy "$policy" --scene "$source" --output "$destination" --episodes 1 --seed "$case_seed" --horizon 300 "${extra[@]}" > "$destination.log" 2>&1;then
        jq -e --arg sha "$sha" '.complete and .episodes==1 and .rows[0].policyWeightsSHA256==$sha and .rows[0].maximumBrickDistanceM==0.35 and (.rows[0].suppliedMap|not) and (.rows[0].taskEventHint|not)' "$destination/summary.json" > /dev/null
        for file in case.json environment.bin;do cmp "$destination/$case_seed/scene/$file" "$source/$file";cmp "$destination/$case_seed/scene/$file" "$baseline/$index/$case_seed/scene/$file";done
        if ./build/flex/control/control verify --run "$destination/$case_seed" --policy "$destination/policy" --output "$destination/verified" > "$destination/verified.log" 2>&1;then
            jq -e --arg sha "$sha" '.passed and .commandReplayMaxAbsError==0 and .weightsSHA256==$sha' "$destination/verified/result.json" > /dev/null;valid=true
        fi
        "$root/runtime/measure-brick-distance" "$destination/$case_seed" "$destination/distance" > "$destination/distance.log"
        returned="$(tail -n1 "$destination/$case_seed/decisions.jsonl" | jq -r '.state.case.passed')"
        jq --slurpfile distance "$destination/distance/result.json" --argjson index "$index" --argjson layout "$layout" --argjson valid "$valid" --argjson returned "$returned" '.rows[0]+{caseIndex:$index,layoutId:$layout,recordingCompleted:true,auditPassed:$valid,physicalReturned:($valid and $returned),closestBrickDistanceM:$distance[0].closestPlanarBaseToBrickM}' "$destination/summary.json" > "$destination/benchmark-row.json"
    else
        mkdir -p "$destination";jq -n --argjson index "$index" --argjson layout "$layout" '{caseIndex:$index,layoutId:$layout,recordingCompleted:false,auditPassed:false,physicalReturned:false,found:false,closestBrickDistanceM:null}' > "$destination/benchmark-row.json"
    fi
}
for ((wave=0;wave<32;wave+=2));do
    attempt "$wave" & a=$!;attempt "$((wave+1))" & b=$!;status=0
    wait "$a" || status=1;wait "$b" || status=1
    (( status==0 )) || { echo 'A benchmark worker failed; recordings retained.' >&2;exit 1; }
done
jq -s '{episodes:length,completedRecordings:(map(select(.recordingCompleted))|length),auditedEpisodes:(map(select(.auditPassed))|length),approaches:(map(select(.auditPassed and .found))|length),returns:(map(select(.physicalReturned))|length),openReturns:(map(select(.layoutId==18 and .physicalReturned))|length),hiddenReturns:(map(select(.layoutId==19 and .physicalReturned))|length),meanClosestM:(map(select(.auditPassed)|.closestBrickDistanceM)|if length>0 then add/length else null end),meanSuccessfulSimulationSeconds:(map(select(.physicalReturned)|.simulationSeconds)|if length>0 then add/length else null end),rows:sort_by(.caseIndex)}' "$out/"*/benchmark-row.json > "$out/score.json"
jq -e '.episodes==32 and .completedRecordings==32 and .auditedEpisodes==32 and ([.rows[].caseIndex]|sort)==[range(0;32)]' "$out/score.json" > /dev/null
sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
sha256sum -c "$out/scene-inputs.sha256" > "$out/scenes-after.log"
sha256sum -c "$out/training-inputs.sha256" > "$out/training-after.log"
jq -n --slurpfile small "$out/score.json" --slurpfile large "$baseline/score.json" '{complete:true,developmentOnly:true,identicalSceneBytesChecked:true,noExactTrainingSceneFileOverlap:true,smallerPoseModel:$small[0],largeModel:$large[0],smallModelSelectedOnEarlierDevelopmentTests:true,reservedFinalStillRequired:true,automaticPromotion:false}' > "$out/comparison.json"
echo 'Older small pose model evaluated on the same 32 development cases.'
