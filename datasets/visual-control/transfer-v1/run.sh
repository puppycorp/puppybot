#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$project/build/flex/sim/transfer-v1"
[[ ! -e "$root/evaluate.exit" ]]
trap 'status=$?; printf "%s\n" "$status" > "$root/evaluate.exit"' EXIT
printf '%s\n' "$BASHPID" > "$root/evaluate.pid"
# Let the independent decoder and standard-checkpoint screens finish first.
while [[ ! -f "$project/build/flex/sim/stochastic-v1/evaluate.exit" ]]; do
    kill -0 179871 || { echo 'Decoder evaluator disappeared without terminal status';exit 1; }
    /usr/bin/sleep 5
done
while [[ ! -f "$project/build/flex/sim/late-search-v1/selected-evaluate.exit" ]]; do
    kill -0 183096 || { echo 'Selected-checkpoint evaluator disappeared without terminal status';exit 1; }
    /usr/bin/sleep 5
done
export PUPPYBOT_BENCHMARK_ROOT="$root"
score() {
    local arm="$1"
    /usr/bin/jq -s --arg candidate "$arm" '{candidate:$candidate,episodes:length,completedRecordings:(map(select(.recordingCompleted))|length),auditFailures:(map(select(.auditPassed|not))|length),physicalReturns:(map(select(.physicalReturned))|length),auditedApproaches:(map(select(.auditPassed and .found))|length),openReturns:(map(select(.layoutId==6 and .physicalReturned))|length),hiddenReturns:(map(select(.layoutId==7 and .physicalReturned))|length),meanSimulationSeconds:(map(.simulationSeconds|select(.!=null))|add/length),rows:sort_by([.layoutId,.sceneId])}' "$root/validation-$arm/"*/benchmark-row.json > "$root/score-$arm.json"
    /usr/bin/jq -e '.episodes==32 and (.rows|map(.caseIndex)|sort)==[range(0;32)]' "$root/score-$arm.json" > /dev/null
}
cd "$project"
/usr/bin/sha256sum -c "$root/recipes.sha256" > "$root/recipes-checked.log"
/usr/bin/sha256sum -c "$root/runtime.sha256" > "$root/runtime-checked.log"
for arm in previous142 late172;do
    source="$project/build/flex/sim/forward-contact-v2/screen-contact142-20"
    policy="$project/build/flex/sim/forward-contact-v2/policy-contact142-20"
    if [[ "$arm" == late172 ]];then
        source="$project/build/flex/sim/late-search-v1/screen-late172-20"
        policy="$project/build/flex/sim/late-search-v1/policy-late172-20"
    fi
    mkdir "$root/validation-$arm"
    for index in {0..7};do
        target=$index;if (( index>=4 ));then target=$((16+index));fi
        /usr/bin/jq -e --argjson index "$target" '.caseIndex==$index and .recordingCompleted and .auditPassed' "$source/$index/benchmark-row.json" > /dev/null
        ln -s "$source/$index" "$root/validation-$arm/$target"
    done
    bash "$root/recipes/benchmark.sh" "$policy" "$arm" validation 4 16
    bash "$root/recipes/benchmark.sh" "$policy" "$arm" validation 16 20
    bash "$root/recipes/benchmark.sh" "$policy" "$arm" validation 24 32
    score "$arm"
done
/usr/bin/jq -s 'map(select(.episodes==32 and .completedRecordings==32 and .physicalReturns>=24 and .openReturns>=8 and .hiddenReturns>=8))|sort_by([(-.physicalReturns),.meanSimulationSeconds,.candidate])|{qualified:(length>0),selected:.[0],reservedFinalTestsStillRequired:(length>0),retainedPolicyOverwritten:false}' "$root/score-"{previous142,late172}.json > "$root/selection.json"
/usr/bin/sha256sum -c "$root/runtime.sha256" > "$root/runtime-after-evaluation.log"
echo 'Full32 transfer diagnostic complete; original qualification and final gates unchanged.'
