#!/usr/bin/env bash
# Evaluate the longer-trained policy against the cached same-data baseline.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
root="$project/build/flex/sim/expanded-rooms-v1/large-model-v1"
screen="$root/longer-316-screen-v1";baseline="$root/coverage-v2-student-training-v1";previous="$root/coverage-v2-student-benchmark-v1"
runtime="$root/phase-large-tests-v1/runtime"
benchmark="${PUPPYBOT_LONGER_316_BENCHMARK_SCRIPT:?Frozen benchmark script required}"
capacity="${PUPPYBOT_LONGER_316_BENCHMARK_WAIT_RUN:?Previous benchmark run required}"
out="${PUPPYBOT_LONGER_316_BENCHMARK_OUT:?New output directory required}"
[[ ! -e "$out" ]];mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
for job in "$screen/run" "$previous/run";do
    while [[ ! -f "$job.exit" ]];do [[ -f "$job.pid" ]] && kill -0 "$(< "$job.pid")" || { echo "$job ended without a status." >&2;exit 1; };sleep 20;done
    [[ "$(< "$job.exit")" == 0 ]] || { echo "$job failed; benchmark not started." >&2;exit 1; }
done
while [[ ! -f "$capacity.exit" ]];do [[ -f "$capacity.pid" ]] && kill -0 "$(< "$capacity.pid")" || { echo 'Previous benchmark ended without a status.' >&2;exit 1; };sleep 20;done
printf '%s\n' "$(< "$capacity.exit")" > "$out/prior-benchmark-status.txt"
jq -e '.sameTrainingData and .initialWeightsIdentical and .firstTrainingOrderIdentical and .firstOptimizerUpdateIdentical and .baselineOptimizerSteps==98 and .candidateOptimizerSteps==1110 and .validationCheckpointSelectionCanDiffer and .reservedFinalStillRequired and (.automaticPromotion|not)' "$screen/comparison.json" > /dev/null
baseline_sha="$(sha256sum "$baseline/policy/weights.bin" | cut -d' ' -f1)";candidate_sha="$(sha256sum "$screen/policy/weights.bin" | cut -d' ' -f1)"
jq -e --arg sha "$baseline_sha" '.episodes==32 and .completedRecordings==32 and .auditedEpisodes==32 and ([.rows[].caseIndex]|sort)==[range(0;32)] and all(.rows[]; .recordingCompleted and .auditPassed and .policyWeightsSHA256==$sha and .maximumBrickDistanceM==0.35 and (.suppliedMap|not) and (.taskEventHint|not))' "$previous/candidate/score.json" > /dev/null
sha256sum "$benchmark" "$screen/comparison.json" "$baseline/policy/weights.bin" "$baseline/policy/receipt.json" "$screen/policy/weights.bin" "$screen/policy/receipt.json" "$previous/candidate/score.json" > "$out/inputs.sha256"
mkdir "$out/candidate-training";ln -s "$screen/policy" "$out/candidate-training/policy";printf '0\n' > "$out/candidate-training/run.exit"
PUPPYBOT_PROJECT="$project" PUPPYBOT_RETURN_TRAINING="$out/candidate-training" PUPPYBOT_RETURN_RUNTIME="$runtime" PUPPYBOT_RETURN_BENCHMARK="$out/candidate" PUPPYBOT_RETURN_WAIT_BENCHMARK='' bash "$benchmark" > "$out/candidate.log" 2>&1
[[ "$(< "$out/candidate/run.exit")" == 0 ]]
jq -e --arg sha "$candidate_sha" '.episodes==32 and .completedRecordings==32 and .auditedEpisodes==32 and ([.rows[].caseIndex]|sort)==[range(0;32)] and all(.rows[]; .recordingCompleted and .auditPassed and .policyWeightsSHA256==$sha and .maximumBrickDistanceM==0.35 and (.suppliedMap|not) and (.taskEventHint|not))' "$out/candidate/score.json" > /dev/null
for ((index=0;index<32;index++));do seed=$((9960000+index));for file in case.json environment.bin;do cmp "$previous/candidate/$index/$seed/scene/$file" "$out/candidate/$index/$seed/scene/$file";done;done
jq -n --slurpfile a "$previous/candidate/score.json" --slurpfile b "$out/candidate/score.json" '
    [$b[0].rows[] as $new | $a[0].rows[] | select(.caseIndex==$new.caseIndex) |
      {caseIndex,layoutId,seed,matchingCase:(.layoutId==$new.layoutId and .seed==$new.seed),baselineApproach:.found,candidateApproach:$new.found,baselineReturn:.physicalReturned,candidateReturn:$new.physicalReturned}] as $pairs |
    {complete:true,developmentOnly:true,identicalCases:(($pairs|length)==32 and all($pairs[];.matchingCase)),sameTrainingData:true,firstOptimizerUpdateIdentical:true,baselineOptimizerSteps:98,candidateOptimizerSteps:1110,validationCheckpointSelectionCanDiffer:true,
     baseline:{approaches:$a[0].approaches,returns:$a[0].returns,openReturns:$a[0].openReturns,hiddenReturns:$a[0].hiddenReturns,meanClosestM:$a[0].meanClosestM,meanSuccessfulSimulationSeconds:$a[0].meanSuccessfulSimulationSeconds},
     candidate:{approaches:$b[0].approaches,returns:$b[0].returns,openReturns:$b[0].openReturns,hiddenReturns:$b[0].hiddenReturns,meanClosestM:$b[0].meanClosestM,meanSuccessfulSimulationSeconds:$b[0].meanSuccessfulSimulationSeconds},
     gainedApproaches:($pairs|map(select((.baselineApproach|not) and .candidateApproach))|length),lostApproaches:($pairs|map(select(.baselineApproach and (.candidateApproach|not)))|length),gainedReturns:($pairs|map(select((.baselineReturn|not) and .candidateReturn))|length),lostReturns:($pairs|map(select(.baselineReturn and (.candidateReturn|not)))|length),reservedFinalStillRequired:true,automaticPromotion:false,rows:$pairs}' > "$out/comparison.json"
jq -e '.complete and .identicalCases and (.rows|length)==32 and .reservedFinalStillRequired and (.automaticPromotion|not)' "$out/comparison.json" > /dev/null
sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
echo 'Longer-trained policy compared on 32 audited development cases.'
