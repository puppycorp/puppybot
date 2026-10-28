#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?}"
root="$project/build/flex/sim/target-aux-v1"
old="$project/build/flex/sim/memory-pose-v1"
diagnostic="$root/diagnostic20"
[[ ! -e "$diagnostic/run.exit" ]]
trap 'status=$?; printf "%s\n" "$status" > "$diagnostic/run.exit"' EXIT
export PUPPYBOT_BENCHMARK_ROOT="$diagnostic"
for arm in eventOnly target; do
    candidate="$arm-20"
    source="$root/screen-$candidate";policy="$root/policy-$candidate"
    if [[ "$arm" == eventOnly ]];then source="$old/screen-$candidate";policy="$old/policy-$candidate";fi
    mkdir "$diagnostic/diagnostic-$candidate"
    for index in {0..7}; do
        canonical=$index
        if (( index>=4 )); then canonical=$((16+index)); fi
        ln -s "$source/$index" "$diagnostic/diagnostic-$candidate/$canonical"
    done
    for bounds in '4 16' '16 20' '24 32'; do
        read -r first last <<< "$bounds"
        bash "$diagnostic/benchmark.sh" "$policy" "$candidate" diagnostic "$first" "$last"
    done
    /usr/bin/jq -s --arg candidate "$candidate" '{candidate:$candidate,selection:"exploratory, selected after observing 8-case screen",episodes:length,completedRecordings:(map(select(.recordingCompleted))|length),auditedEpisodes:(map(select(.auditPassed))|length),auditFailures:(map(select(.auditPassed|not))|length),physicalReturns:(map(select(.physicalReturned))|length),auditedApproaches:(map(select(.auditPassed and .found))|length),openReturns:(map(select(.layoutId==6 and .physicalReturned))|length),hiddenReturns:(map(select(.layoutId==7 and .physicalReturned))|length),meanSimulationSeconds:(map(.simulationSeconds|select(.!=null))|if length>0 then add/length else null end),rows:sort_by([.layoutId,.sceneId])}' "$diagnostic/diagnostic-$candidate/"*/benchmark-row.json > "$diagnostic/score-$candidate.json"
    /usr/bin/jq -e '(.episodes==32) and ([.rows[].caseIndex]|unique|length)==32' "$diagnostic/score-$candidate.json" >/dev/null
done
/usr/bin/sha256sum --check "$diagnostic/inputs.sha256" > "$diagnostic/integrity.log"
