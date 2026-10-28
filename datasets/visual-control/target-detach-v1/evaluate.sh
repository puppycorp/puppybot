#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$project/build/flex/sim/target-detach-v1"
old="$project/build/flex/sim/target-actor-v1"
models="$root/models"
[[ ! -e "$models/evaluate.exit" ]]
trap 'status=$?; printf "%s\n" "$status" > "$models/evaluate.exit"' EXIT
export PUPPYBOT_BENCHMARK_ROOT="$root"
export PATH="$models/native-path"
score() {
    local suite="$1" candidate="$2"
    /usr/bin/jq -s --arg suite "$suite" --arg candidate "$candidate" '{suite:$suite,candidate:$candidate,episodes:length,completedRecordings:(map(select(.recordingCompleted))|length),auditedEpisodes:(map(select(.auditPassed))|length),auditFailures:(map(select(.auditPassed|not))|length),physicalReturns:(map(select(.physicalReturned))|length),auditedApproaches:(map(select(.auditPassed and .found))|length),openReturns:(map(select(.layoutId==6 and .physicalReturned))|length),hiddenReturns:(map(select(.layoutId==7 and .physicalReturned))|length),meanSimulationSeconds:(map(.simulationSeconds|select(.!=null))|if length>0 then add/length else null end),rows:sort_by([.layoutId,.sceneId])}' "$root/$suite-$candidate/"*/benchmark-row.json > "$root/score-$suite-$candidate.json"
    /usr/bin/jq -e '(.rows|map(.caseIndex)|unique|length)==.episodes' "$root/score-$suite-$candidate.json" >/dev/null
}
cd "$models/runtime"
while [[ ! -f "$models/target/first-after.bin" ]];do
    [[ ! -f "$root/train.exit" ]] || { echo 'Actor training stopped before initial conformance';exit 1; }
    kill -0 "$(< "$root/train.pid")" || { echo 'Actor training handle disappeared';exit 1; }
    /usr/bin/sleep 2
done
"$models/core-match" "$old/models/target/initial.bin" "$models/target/initial.bin" "$models/initial-early-match.json"
/usr/bin/jq -e '.passed and .originalParameters==375658 and .extraTrainingParameters==0' "$models/initial-early-match.json" >/dev/null
/usr/bin/cmp "$old/models/target/initial.bin" "$models/target/initial.bin"
"$models/target-zero" "$models/target/initial.bin" --merge
/usr/bin/cmp "$old/models/target/first-order.bin" "$models/target/first-order.bin"
"$old/models/publish" "$old/models/target/initial.bin" "$old/models/target/data.bin" "$old/models/target/initial.bin" "$root/initial-control" 1 "$old/models/target/target-position" > "$models/initial-control-publish.log" 2>&1
"$models/publish" "$models/target/initial.bin" "$models/target/data.bin" "$models/target/initial.bin" "$root/initial-actor" 0 "$models/target/target-position" > "$models/initial-actor-publish.log" 2>&1
"$models/initial-parity" "$root/initial-control" "$root/initial-actor" "$models/target/data.bin" "$root/initial-parity-check" > "$models/initial-parity.log" 2>&1
/usr/bin/jq -e '.passed and .rawActorAndMemoryBitIdentical and .framesCompared==708' "$root/initial-parity-check/result.json" >/dev/null
for epoch in 1 5 10 20 40 best; do
    candidate="target-$epoch"
    weights="$models/target/epoch-$epoch.bin"; published_epoch="$epoch"
    if [[ "$epoch" == best ]];then
        while [[ ! -f "$root/train.exit" ]];do kill -0 "$(< "$root/train.pid")" || { echo 'Actor training stopped before final selection';exit 1; };/usr/bin/sleep 2;done
        [[ "$(< "$root/train.exit")" == 0 ]]
        weights="$models/target/weights.bin"; published_epoch=40
    fi
    while [[ ! -f "$weights" ]];do
        [[ ! -f "$root/train.exit" ]] || { echo 'Actor training stopped without required snapshot';exit 1; }
        kill -0 "$(< "$root/train.pid")" || { echo 'Actor training handle disappeared without terminal status';exit 1; }
        /usr/bin/sleep 5
    done
    "$models/publish" "$weights" "$models/target/data.bin" "$models/target/initial.bin" "$root/policy-$candidate" "$published_epoch" "$models/target/target-position" > "$models/publish-$candidate.log" 2>&1
    /usr/bin/jq -e '.heatmapActorGradientDetached and .heatmapActorFeatures and .targetHeatmapAuxiliary and .cameraEventAuxiliary and (.taskFeedback|not) and .targetPositionTargetsSHA256=="9846229a1a28aa77c7e8653d1bbe14dbe6185c27d90a46b77d68b5e1bf0e5294"' "$root/policy-$candidate/receipt.json" >/dev/null
    if [[ "$epoch" == best ]];then
        selected="$(/usr/bin/jq -s 'map(select(.selected))|last|.epoch' "$models/target/curves.jsonl")"
        /usr/bin/jq --argjson selected "$selected" '.+{selectedEpoch:$selected,checkpointSelection:"Minimum held-out demonstration loss including initial weights"}' "$root/policy-$candidate/receipt.json" > "$root/policy-$candidate/receipt-selected.json"
        mv "$root/policy-$candidate/receipt-selected.json" "$root/policy-$candidate/receipt.json"
    fi
    ./build/flex/control/forward-tests "$root/policy-$candidate" "$models/target/data.bin" "$root/forward-$candidate" > "$models/forward-$candidate.log" 2>&1
    /usr/bin/jq -e '.passed and .logitMaxAbsError==0 and .memoryMaxAbsError==0 and .resetBitIdentical' "$root/forward-$candidate/result.json" >/dev/null
    bash "$models/recipes/benchmark.sh" "$root/policy-$candidate" "$candidate" screen 0 8
    score screen "$candidate"
    oldscore="$old/score-screen-target-$epoch.json"
    until [[ -s "$oldscore" ]] && /usr/bin/jq -e '.episodes==8 and (.rows|length)==8' "$oldscore" >/dev/null 2>&1;do
        [[ ! -f "$old/models/evaluate-v2.exit" ]] || { echo 'Heatmap control evaluation stopped without required score';exit 1; }
        /usr/bin/sleep 5
    done
    if ! /usr/bin/jq -se 'any(.openReturns>=1 and .hiddenReturns>=1)' "$oldscore" "$root/score-screen-$candidate.json" >/dev/null;then continue;fi
    for arm in target attached;do
        source="$root/screen-target-$epoch"; policy="$root/policy-target-$epoch"; name="target-$epoch"
        if [[ "$arm" == attached ]];then source="$old/screen-target-$epoch";policy="$old/policy-target-$epoch";name="attached-$epoch";fi
        mkdir "$root/validation-$name"
        for index in {0..7};do dest=$index;if (( index>=4 ));then dest=$((16+index));fi;ln -s "$source/$index" "$root/validation-$name/$dest";done
        bash "$models/recipes/benchmark.sh" "$policy" "$name" validation 4 16
        bash "$models/recipes/benchmark.sh" "$policy" "$name" validation 16 20
        bash "$models/recipes/benchmark.sh" "$policy" "$name" validation 24 32
        score validation "$name"
    done
done
files=("$root"/score-validation-target-*.json)
if [[ -f "${files[0]}" ]];then
    /usr/bin/jq -s 'map(select(.episodes==32 and .completedRecordings==32 and .physicalReturns>=24 and .openReturns>=8 and .hiddenReturns>=8))|sort_by([(-.physicalReturns),.meanSimulationSeconds,.candidate])|{qualified:(length>0),selected:.[0],finalEvaluationStillRequired:(length>0),retainedPolicyOverwritten:false}' "${files[@]}" > "$models/selection.json"
else
    /usr/bin/jq -n '{qualified:false,reason:"No checkpoint returned in both screen room types",retainedPolicyOverwritten:false}' > "$models/selection.json"
fi
echo 'Gradient-separated actor comparison evaluated; reserved final tests remain separate.'
