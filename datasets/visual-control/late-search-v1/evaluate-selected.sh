#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$project/build/flex/sim/late-search-v1"
models="$root/models"
[[ "$(< "$models/train.exit")" == 0 && ! -e "$root/selected-evaluate.exit" ]]
trap 'status=$?; printf "%s\n" "$status" > "$root/selected-evaluate.exit"' EXIT
printf '%s\n' "$BASHPID" > "$root/selected-evaluate.pid"
while [[ ! -f "$models/evaluate.exit" ]]; do
    kill -0 155811 || { echo 'Fixed-snapshot evaluator disappeared without terminal status';exit 1; }
    /usr/bin/sleep 5
done
[[ "$(< "$models/evaluate.exit")" == 0 ]]
export PUPPYBOT_BENCHMARK_ROOT="$root"
export PATH="$models/native-path"
score() {
    local suite="$1" candidate="$2"
    /usr/bin/jq -s --arg candidate "$candidate" --arg suite "$suite" '{candidate:$candidate,suite:$suite,episodes:length,completedRecordings:(map(select(.recordingCompleted))|length),auditFailures:(map(select(.auditPassed|not))|length),physicalReturns:(map(select(.physicalReturned))|length),auditedApproaches:(map(select(.auditPassed and .found))|length),openReturns:(map(select(.layoutId==6 and .physicalReturned))|length),hiddenReturns:(map(select(.layoutId==7 and .physicalReturned))|length),meanSimulationSeconds:(map(.simulationSeconds|select(.!=null))|add/length),rows:sort_by([.layoutId,.sceneId])}' "$root/$suite-$candidate/"*/benchmark-row.json > "$root/score-$suite-$candidate.json"
    /usr/bin/jq -e '(.rows|map(.caseIndex)|unique|length)==.episodes' "$root/score-$suite-$candidate.json" > /dev/null
}
for arm in baseline142 late172;do
    candidate="best-$arm"
    policy="$root/policy-$candidate"
    mkdir "$policy"
    cp "$models/$arm/"{weights.bin,policy,receipt.json,model.pup,factory.flex} "$policy/"
    cp -a "$models/$arm/kernels" "$policy/kernels"
    epoch="$(/usr/bin/jq -s 'map(select(.selected))|last|.epoch' "$models/$arm/curves.jsonl")"
    /usr/bin/jq --argjson epoch "$epoch" '.+{selectedEpoch:$epoch,checkpointSelection:"Minimum held-out demonstration loss in completed 20-epoch run; not selected by autonomous score"}' "$models/$arm/receipt.json" > "$policy/receipt.json"
    /usr/bin/cmp "$models/$arm/weights.bin" "$policy/weights.bin"
    "$models/runtime/build/flex/control/forward-tests" "$policy" "$models/$arm/data.bin" "$root/forward-$candidate" > "$models/forward-$candidate.log" 2>&1
    /usr/bin/jq -e '.passed and .logitMaxAbsError==0 and .memoryMaxAbsError==0 and .resetBitIdentical' "$root/forward-$candidate/result.json" > /dev/null
    bash "$root/selected-recipes/benchmark.sh" "$policy" "$candidate" screen 0 8
    score screen "$candidate"
done
if /usr/bin/jq -se 'any(.openReturns>=1 and .hiddenReturns>=1)' "$root/score-screen-best-"{baseline142,late172}.json > /dev/null;then
    for arm in baseline142 late172;do
        candidate="best-$arm"
        mkdir "$root/validation-$candidate"
        for index in {0..7};do target=$index;if (( index>=4 ));then target=$((16+index));fi;ln -s "$root/screen-$candidate/$index" "$root/validation-$candidate/$target";done
        bash "$root/selected-recipes/benchmark.sh" "$root/policy-$candidate" "$candidate" validation 4 16
        bash "$root/selected-recipes/benchmark.sh" "$root/policy-$candidate" "$candidate" validation 16 20
        bash "$root/selected-recipes/benchmark.sh" "$root/policy-$candidate" "$candidate" validation 24 32
        score validation "$candidate"
    done
fi
echo 'Standard loss-selected checkpoints evaluated; original task and promotion gates unchanged.'
