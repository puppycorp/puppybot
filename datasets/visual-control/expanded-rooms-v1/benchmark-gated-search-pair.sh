#!/usr/bin/env bash
# Evaluate both matched-update policies on the same 32 development cases.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
root="$project/build/flex/sim/expanded-rooms-v1/large-model-v1"
pair="${PUPPYBOT_GATED_PAIR_DIRECTORY:-$root/gated-search-pair-v1}"
job="${PUPPYBOT_GATED_PAIR_WAIT_RUN:-$pair/run}"
runtime="$root/phase-large-tests-v1/runtime"
benchmark="${PUPPYBOT_GATED_PAIR_BENCHMARK_SCRIPT:?Frozen benchmark script required}"
out="${PUPPYBOT_GATED_PAIR_BENCHMARK_OUT:?New output directory required}"
[[ ! -e "$out" ]]
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
while [[ ! -f "$job.exit" ]];do [[ -f "$job.pid" ]] && kill -0 "$(< "$job.pid")" || { echo 'Matched training ended without a status.' >&2;exit 1; }; /usr/bin/sleep 20;done
[[ "$(< "$job.exit")" == 0 && "$(< "$pair/run.exit")" == 0 ]]
/usr/bin/jq -e '.exploratory and .optimizerStepsPerModel==98 and .initialWeightsIdentical and .additionalFittingHistorySeen and .reservedFinalStillRequired and (.automaticPromotion|not)' "$pair/comparison.json" > /dev/null
/usr/bin/sha256sum "$benchmark" "$pair/comparison.json" "$pair/baseline-policy/weights.bin" "$pair/baseline-policy/policy" "$pair/baseline-policy/receipt.json" "$pair/augmented-policy/weights.bin" "$pair/augmented-policy/policy" "$pair/augmented-policy/receipt.json" > "$out/inputs.sha256"
for arm in baseline augmented;do
    training="$out/$arm-training"
    mkdir "$training"
    ln -s "$pair/$arm-policy" "$training/policy"
    printf '0\n' > "$training/run.exit"
    PUPPYBOT_PROJECT="$project" PUPPYBOT_RETURN_TRAINING="$training" PUPPYBOT_RETURN_RUNTIME="$runtime" PUPPYBOT_RETURN_BENCHMARK="$out/$arm" PUPPYBOT_RETURN_WAIT_BENCHMARK='' /usr/bin/bash "$benchmark" > "$out/$arm.log" 2>&1
    [[ "$(< "$out/$arm/run.exit")" == 0 ]]
    sha="$(/usr/bin/sha256sum "$pair/$arm-policy/weights.bin" | /usr/bin/cut -d' ' -f1)"
    /usr/bin/jq -e --arg sha "$sha" '.episodes==32 and .completedRecordings==32 and .auditedEpisodes==32 and ([.rows[].caseIndex]|sort)==[range(0;32)] and all(.rows[]; .recordingCompleted and .auditPassed and .policyWeightsSHA256==$sha and .maximumBrickDistanceM==0.35 and (.suppliedMap|not) and (.taskEventHint|not))' "$out/$arm/score.json" > /dev/null
done
/usr/bin/jq -n --slurpfile a "$out/baseline/score.json" --slurpfile b "$out/augmented/score.json" --slurpfile setup "$pair/comparison.json" '
    [$b[0].rows[] as $new | $a[0].rows[] | select(.caseIndex==$new.caseIndex) |
      {caseIndex,layoutId,seed,matchingCase:(.layoutId==$new.layoutId and .seed==$new.seed),baselineApproach:.found,augmentedApproach:$new.found,baselineReturn:.physicalReturned,augmentedReturn:$new.physicalReturned}] as $pairs |
    {complete:true,developmentOnly:true,identicalCases:(($pairs|length)==32 and all($pairs[];.matchingCase)),optimizerStepsPerModel:98,trainingOrdersIdentical:$setup[0].trainingOrdersIdentical,baseline:{approaches:$a[0].approaches,returns:$a[0].returns,openReturns:$a[0].openReturns,hiddenReturns:$a[0].hiddenReturns,meanClosestM:$a[0].meanClosestM,meanSuccessfulSimulationSeconds:$a[0].meanSuccessfulSimulationSeconds},augmented:{approaches:$b[0].approaches,returns:$b[0].returns,openReturns:$b[0].openReturns,hiddenReturns:$b[0].hiddenReturns,meanClosestM:$b[0].meanClosestM,meanSuccessfulSimulationSeconds:$b[0].meanSuccessfulSimulationSeconds},gainedApproaches:($pairs|map(select((.baselineApproach|not) and .augmentedApproach))|length),lostApproaches:($pairs|map(select(.baselineApproach and (.augmentedApproach|not)))|length),gainedReturns:($pairs|map(select((.baselineReturn|not) and .augmentedReturn))|length),lostReturns:($pairs|map(select(.baselineReturn and (.augmentedReturn|not)))|length),reservedFinalStillRequired:true,automaticPromotion:false,rows:$pairs}' > "$out/comparison.json"
/usr/bin/jq -e '.complete and .identicalCases and (.rows|length)==32 and .reservedFinalStillRequired and (.automaticPromotion|not)' "$out/comparison.json" > /dev/null
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
echo 'Both large gated policies were evaluated on the same 32 audited development cases.'
