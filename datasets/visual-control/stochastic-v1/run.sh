#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$project/build/flex/sim/stochastic-v1"
[[ "$(< "$root/prepared.exit")" == 0 && ! -e "$root/evaluate.exit" ]]
trap 'status=$?; printf "%s\n" "$status" > "$root/evaluate.exit"' EXIT
printf '%s\n' "$BASHPID" > "$root/evaluate.pid"
export PUPPYBOT_BENCHMARK_ROOT="$root"
export PATH="$root/models/native-path"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1
cd "$project"
/usr/bin/sha256sum -c "$root/recipes.sha256" > "$root/recipes-checked.log"
/usr/bin/sha256sum -c "$root/runtime.sha256" > "$root/runtime-checked.log"
for arm in greedy half one; do
    "$root/forward-tests" "$root/policy-$arm" "$project/build/flex/sim/forward-contact-v2/artifacts/data142/data.bin" "$root/forward-$arm" > "$root/forward-$arm.log" 2>&1
    /usr/bin/jq -e '.passed and .logitMaxAbsError==0 and .memoryMaxAbsError==0 and .resetBitIdentical' "$root/forward-$arm/result.json" > /dev/null
done
cd "$root/runtime"
./build/flex/control/control verify --run "$project/build/flex/sim/forward-contact-v2/screen-contact142-20/0/8900000" --policy "$root/policy-greedy" --output "$root/greedy-replay" > "$root/greedy-replay.log" 2>&1
/usr/bin/jq -e '.passed and .commandReplayMaxAbsError==0 and .consumptionEventsProjected==1 and .returnPoseChecked' "$root/greedy-replay/result.json" > /dev/null
score() {
    local suite="$1" arm="$2"
    /usr/bin/jq -s --arg suite "$suite" --arg candidate "$arm" '{suite:$suite,candidate:$candidate,episodes:length,completedRecordings:(map(select(.recordingCompleted))|length),auditedEpisodes:(map(select(.auditPassed))|length),auditFailures:(map(select(.auditPassed|not))|length),physicalReturns:(map(select(.physicalReturned))|length),auditedApproaches:(map(select(.auditPassed and .found))|length),openReturns:(map(select(.layoutId==6 and .physicalReturned))|length),hiddenReturns:(map(select(.layoutId==7 and .physicalReturned))|length),meanSimulationSeconds:(map(.simulationSeconds|select(.!=null))|add/length),rows:sort_by([.layoutId,.sceneId])}' "$root/$suite-$arm/"*/benchmark-row.json > "$root/score-$suite-$arm.json"
    /usr/bin/jq -e '(.rows|map(.caseIndex)|unique|length)==.episodes' "$root/score-$suite-$arm.json" > /dev/null
}
for arm in greedy half one; do
    bash "$root/recipes/benchmark.sh" "$root/policy-$arm" "$arm" screen 0 8
    score screen "$arm"
    if [[ "$arm" == greedy ]];then
        /usr/bin/jq -e '.episodes==8 and .auditFailures==0 and .physicalReturns==1 and .hiddenReturns==0 and .auditedApproaches==1' "$root/score-screen-greedy.json" > /dev/null
    fi
done
if /usr/bin/jq -se 'any(.openReturns>=1 and .hiddenReturns>=1)' "$root/score-screen-"{half,one}.json > /dev/null;then
    for arm in greedy half one;do
        mkdir "$root/validation-$arm"
        for index in {0..7};do target=$index;if (( index>=4 ));then target=$((16+index));fi;ln -s "$root/screen-$arm/$index" "$root/validation-$arm/$target";done
        bash "$root/recipes/benchmark.sh" "$root/policy-$arm" "$arm" validation 4 16
        bash "$root/recipes/benchmark.sh" "$root/policy-$arm" "$arm" validation 16 20
        bash "$root/recipes/benchmark.sh" "$root/policy-$arm" "$arm" validation 24 32
        score validation "$arm"
    done
fi
files=("$root"/score-validation-*.json)
if [[ -f "${files[0]}" ]];then
    /usr/bin/jq -s 'map(select(.episodes==32 and .completedRecordings==32 and .physicalReturns>=24 and .openReturns>=8 and .hiddenReturns>=8))|sort_by([(-.physicalReturns),.meanSimulationSeconds,.candidate])|{qualified:(length>0),selected:.[0],reservedFinalAndSamplingRobustnessStillRequired:(length>0),retainedPolicyOverwritten:false}' "${files[@]}" > "$root/selection.json"
else
    /usr/bin/jq -n '{qualified:false,reason:"Neither sampling arm returned in both screen room types",retainedPolicyOverwritten:false}' > "$root/selection.json"
fi
cd "$project"
/usr/bin/sha256sum -c "$root/recipes.sha256" > "$root/recipes-after-evaluation.log"
/usr/bin/sha256sum -c "$root/runtime.sha256" > "$root/runtime-after-evaluation.log"
echo 'Fixed-weight decoding comparison evaluated; no automatic production policy changes.'
