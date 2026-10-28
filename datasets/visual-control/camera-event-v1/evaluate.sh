#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$project/build/flex/sim/camera-event-v1"
models="$root/models"
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
for arm in plain cameraEvent;do
    while [[ ! -f "$models/$arm/first-after.bin" ]];do
        kill -0 "$(< "$root/train.pid")" || { echo 'Training stopped before initial conformance';exit 1; }
        /usr/bin/sleep 2
    done
    "$models/core-match" "$models/initial-policy/weights.bin" "$models/$arm/initial.bin" "$models/initial-$arm.json"
done
/usr/bin/jq -e '.passed and .extraTrainingParameters==0' "$models/initial-plain.json" > /dev/null
/usr/bin/jq -e '.passed and .extraTrainingParameters==129' "$models/initial-cameraEvent.json" > /dev/null
/usr/bin/cmp "$models/"{plain,cameraEvent}/first-order.bin
for epoch in 10 20 40 best; do
    for arm in plain cameraEvent; do
        candidate="$arm-$epoch"
        weights="$models/$arm/epoch-$epoch.bin";published_epoch="$epoch"
        if [[ "$epoch" == best ]];then
            while [[ ! -f "$root/train.exit" ]];do kill -0 "$(< "$root/train.pid")" || { echo 'Training stopped before final selection';exit 1; };/usr/bin/sleep 2;done
            [[ "$(< "$root/train.exit")" == 0 ]]
            weights="$models/$arm/weights.bin";published_epoch=40
        fi
        while [[ ! -f "$weights" ]]; do
            if [[ -f "$models/$arm.exit" || -f "$root/train.exit" ]];then echo 'Training stopped without required camera-event snapshot';exit 1;fi
            kill -0 "$(< "$root/train.pid")" || { echo 'Training handle disappeared without terminal status';exit 1; }
            /usr/bin/sleep 5
        done
        "$models/publish" "$weights" "$models/$arm/data.bin" "$models/$arm/initial.bin" "$root/policy-$candidate" "$published_epoch" "$arm" > "$models/publish-$candidate.log" 2>&1
        if [[ "$epoch" == best ]];then
            selected="$(/usr/bin/jq -s 'map(select(.selected))|last|.epoch' "$models/$arm/curves.jsonl")"
            /usr/bin/jq --argjson selected "$selected" '.+{selectedEpoch:$selected,checkpointSelection:"Minimum held-out demonstration loss including initial weights"}' "$root/policy-$candidate/receipt.json" > "$root/policy-$candidate/receipt-selected.json"
            mv "$root/policy-$candidate/receipt-selected.json" "$root/policy-$candidate/receipt.json"
        fi
        ./build/flex/control/forward-tests "$root/policy-$candidate" "$models/$arm/data.bin" "$root/forward-$candidate" > "$models/forward-$candidate.log" 2>&1
        /usr/bin/jq -e '.passed and .logitMaxAbsError==0 and .memoryMaxAbsError==0 and .resetBitIdentical' "$root/forward-$candidate/result.json" > /dev/null
        bash "$models/recipes/benchmark.sh" "$root/policy-$candidate" "$candidate" screen 0 8
        score screen "$candidate"
    done
    if ! /usr/bin/jq -se 'any(.openReturns>=1 and .hiddenReturns>=1)' "$root/score-screen-plain-$epoch.json" "$root/score-screen-cameraEvent-$epoch.json" > /dev/null;then continue;fi
    for arm in plain cameraEvent;do
        candidate="$arm-$epoch"
        mkdir "$root/validation-$candidate"
        for index in {0..7};do target=$index;if (( index>=4 ));then target=$((16+index));fi;ln -s "$root/screen-$candidate/$index" "$root/validation-$candidate/$target";done
        bash "$models/recipes/benchmark.sh" "$root/policy-$candidate" "$candidate" validation 4 16
        bash "$models/recipes/benchmark.sh" "$root/policy-$candidate" "$candidate" validation 16 20
        bash "$models/recipes/benchmark.sh" "$root/policy-$candidate" "$candidate" validation 24 32
        score validation "$candidate"
    done
done
files=("$root"/score-validation-*.json)
if [[ -f "${files[0]}" ]];then
    /usr/bin/jq -s 'map(select(.episodes==32 and .completedRecordings==32 and .physicalReturns>=24 and .openReturns>=8 and .hiddenReturns>=8))|sort_by([(-.physicalReturns),.meanSimulationSeconds,.candidate])|{qualified:(length>0),selected:.[0],finalEvaluationStillRequired:(length>0),retainedPolicyOverwritten:false}' "${files[@]}" > "$models/selection.json"
else
    /usr/bin/jq -n '{qualified:false,reason:"No checkpoint returned in both screen room types",retainedPolicyOverwritten:false}' > "$models/selection.json"
fi
echo 'Camera-event visual-supervision comparison evaluated; reserved final tests remain separate.'
