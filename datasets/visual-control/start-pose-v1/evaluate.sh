#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$project/build/flex/sim/start-pose-v1"
models="$root/models"
data="$root/artifacts/data132/data.bin"
[[ ! -e "$models/evaluate.exit" ]]
trap 'status=$?; printf "%s\n" "$status" > "$models/evaluate.exit"' EXIT
export PUPPYBOT_BENCHMARK_ROOT="$root"
export PATH="$models/native-path"
score() {
    local suite="$1" candidate="$2"
    /usr/bin/jq -s --arg suite "$suite" --arg candidate "$candidate" '{suite:$suite,candidate:$candidate,episodes:length,completedRecordings:(map(select(.recordingCompleted))|length),auditedEpisodes:(map(select(.auditPassed))|length),auditFailures:(map(select(.auditPassed|not))|length),physicalReturns:(map(select(.physicalReturned))|length),auditedApproaches:(map(select(.auditPassed and .found))|length),openReturns:(map(select(.layoutId==6 and .physicalReturned))|length),hiddenReturns:(map(select(.layoutId==7 and .physicalReturned))|length),meanSimulationSeconds:(map(.simulationSeconds|select(.!=null))|if length>0 then add/length else null end),rows:sort_by([.layoutId,.sceneId])}' "$root/$suite-$candidate/"*/benchmark-row.json > "$root/score-$suite-$candidate.json"
    /usr/bin/jq -e '(.rows|map(.caseIndex)|unique|length)==.episodes' "$root/score-$suite-$candidate.json" > /dev/null
}
cd "$models/runtime"
for epoch in 10 20; do
    candidate="pose$epoch"
    while [[ ! -f "$models/pose/epoch-$epoch.bin" ]]; do
        if [[ -f "$models/train.exit" ]]; then echo 'Pose training stopped before its required snapshot'; exit 1; fi
        /usr/bin/sleep 5
    done
    "$models/publish" "$models/pose/epoch-$epoch.bin" "$data" "$models/pose/initial.bin" "$root/policy-$candidate" "$epoch" > "$models/publish-$candidate.log" 2>&1
    ./build/flex/control/forward-tests "$root/policy-$candidate" "$data" "$root/forward-$candidate" > "$models/forward-$candidate.log" 2>&1
    /usr/bin/jq -e '.passed and .logitMaxAbsError==0 and .memoryMaxAbsError==0 and .resetBitIdentical' "$root/forward-$candidate/result.json" > /dev/null
    bash "$models/recipes/benchmark.sh" "$root/policy-$candidate" "$candidate" screen 0 8
    score screen "$candidate"
    if ! /usr/bin/jq -e '.openReturns>=1 and .hiddenReturns>=1' "$root/score-screen-$candidate.json" > /dev/null; then continue; fi
    mkdir "$root/validation-$candidate"
    for index in {0..7}; do target=$index;if (( index>=4 )); then target=$((16+index));fi;ln -s "$root/screen-$candidate/$index" "$root/validation-$candidate/$target";done
    bash "$models/recipes/benchmark.sh" "$root/policy-$candidate" "$candidate" validation 4 16
    bash "$models/recipes/benchmark.sh" "$root/policy-$candidate" "$candidate" validation 16 20
    bash "$models/recipes/benchmark.sh" "$root/policy-$candidate" "$candidate" validation 24 32
    score validation "$candidate"
done
files=("$root"/score-validation-pose*.json)
if [[ -f "${files[0]}" ]]; then
    /usr/bin/jq -s 'map(select(.episodes==32 and .completedRecordings==32 and .physicalReturns>=24 and .openReturns>=8 and .hiddenReturns>=8))|sort_by([(-.physicalReturns),.meanSimulationSeconds,.candidate])|{qualified:(length>0),selected:.[0],finalEvaluationStillRequired:(length>0),retainedPolicyOverwritten:false}' "${files[@]}" > "$models/selection.json"
else
    /usr/bin/jq -n '{qualified:false,reason:"No expanded-data checkpoint returned in both screen room types",retainedPolicyOverwritten:false}' > "$models/selection.json"
fi
echo 'Expanded-data fixed snapshots evaluated; reserved final tests remain separate.'
