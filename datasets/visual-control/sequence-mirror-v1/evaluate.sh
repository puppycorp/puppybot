#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$project/build/flex/sim/sequence-mirror-v1"
models="$root/models"
[[ ! -e "$models/evaluate.exit" ]]
trap 'status=$?; printf "%s\n" "$status" > "$models/evaluate.exit"' EXIT
export PATH="$models/native-path"
benchmark="$models/evaluate-scripts/benchmark.sh"
data="$project/datasets/visual-control/return-recovery-v1/artifacts-primitive/data96/data.bin"
score() {
    local suite="$1" candidate="$2"
    /usr/bin/jq -s --arg suite "$suite" --arg candidate "$candidate" '{candidate:$candidate,suite:$suite,episodes:length,completedRecordings:(map(select(.recordingCompleted))|length),auditedEpisodes:(map(select(.auditPassed))|length),auditFailures:(map(select(.auditPassed|not))|length),physicalReturns:(map(select(.physicalReturned))|length),auditedApproaches:(map(select(.auditPassed and .found))|length),openReturns:(map(select(.layoutId==6 and .physicalReturned))|length),hiddenReturns:(map(select(.layoutId==7 and .physicalReturned))|length),meanSimulationSeconds:(map(.simulationSeconds|select(.!=null))|if length>0 then add/length else null end),rows:sort_by([.layoutId,.sceneId])}' "$root/$suite-$candidate/"*/benchmark-row.json > "$root/score-$suite-$candidate.json"
}
cd "$models/runtime"
for epoch in 10 20; do
    for arm in plain mirror; do
        candidate="$arm$epoch"
        while [[ ! -f "$models/$arm/epoch-$epoch.bin" ]]; do
            if [[ -f "$models/$arm.exit" || -f "$models/train.exit" ]]; then echo 'Training stopped before the required checkpoint'; exit 1; fi
            /usr/bin/sleep 5
        done
        mirror=0;if [[ "$arm" == mirror ]]; then mirror=1; fi
        "$models/publish" "$models/$arm/epoch-$epoch.bin" "$data" "$models/$arm/initial.bin" "$root/policy-$candidate" "$epoch" "$mirror" > "$models/publish-$candidate.log" 2>&1
        ./build/flex/control/forward-tests "$root/policy-$candidate" "$data" "$root/forward-$candidate" > "$models/forward-$candidate.log" 2>&1
        /usr/bin/jq -e '.passed and .logitMaxAbsError==0 and .memoryMaxAbsError==0 and .resetBitIdentical' "$root/forward-$candidate/result.json" > /dev/null
        bash "$benchmark" "$root/policy-$candidate" "$candidate" screen 0 8
        score screen "$candidate"
    done
    if ! /usr/bin/jq -se 'any(.openReturns>=1 and .hiddenReturns>=1)' "$root/score-screen-plain$epoch.json" "$root/score-screen-mirror$epoch.json" > /dev/null; then continue; fi
    for arm in plain mirror; do
        candidate="$arm$epoch"
        mkdir "$root/validation-$candidate"
        for index in {0..7}; do target=$index;if (( index>=4 )); then target=$((16+index));fi;ln -s "$root/screen-$candidate/$index" "$root/validation-$candidate/$target";done
        bash "$benchmark" "$root/policy-$candidate" "$candidate" validation 4 16
        bash "$benchmark" "$root/policy-$candidate" "$candidate" validation 16 20
        bash "$benchmark" "$root/policy-$candidate" "$candidate" validation 24 32
        score validation "$candidate"
    done
done
files=("$root"/score-validation-*.json)
if [[ -f "${files[0]}" ]]; then
    /usr/bin/jq -s 'map(select(.episodes==32 and .completedRecordings==32 and .physicalReturns>=24 and .openReturns>=8 and .hiddenReturns>=8))|sort_by([(-.physicalReturns),.meanSimulationSeconds,.candidate])|{qualified:(length>0),selected:.[0],finalEvaluationStillRequired:(length>0),retainedPolicyOverwritten:false}' "${files[@]}" > "$models/selection.json"
else
    /usr/bin/jq -n '{qualified:false,reason:"No checkpoint returned successfully in both screen room types",retainedPolicyOverwritten:false}' > "$models/selection.json"
fi
/usr/bin/jq -s '{screens:.,finalLayoutsEvaluated:false}' "$root"/score-screen-*.json > "$models/screens.json"
echo 'Fixed10/20 native screens and any qualifying paired full32 validation completed.'
