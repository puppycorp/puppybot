#!/usr/bin/env bash
# Compare the matched reversal-penalty pair in eight distinct-start rooms.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
root="$project/build/flex/sim/expanded-rooms-v1/large-model-v1"
pair="$root/return-reversal-screen-v1";baseline="$root/coverage-return-pair-v1/augmented-policy";candidate="$pair/policy"
audit="$root/diverse-development-310-corpus-audit-v1";prior="$root/return-reversal-benchmark-v1/run"
capacity="${PUPPYBOT_REVERSAL_DIVERSE_WAIT_RUN:?Previous benchmark required}"
driver="${PUPPYBOT_REVERSAL_DIVERSE_BENCHMARK:?Frozen diverse benchmark required}"
out="${PUPPYBOT_REVERSAL_DIVERSE_OUT:?New output directory required}"
[[ ! -e "$out" ]];mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
for job in "$pair/run" "$prior";do
    while [[ ! -f "$job.exit" ]];do [[ -f "$job.pid" ]] && kill -0 "$(< "$job.pid")" || { echo "$job ended without a status." >&2;exit 1; };sleep 20;done
    [[ "$(< "$job.exit")" == 0 ]] || { echo "$job failed; comparison not started." >&2;exit 1; }
done
while [[ ! -f "$capacity.exit" ]];do [[ -f "$capacity.pid" ]] && kill -0 "$(< "$capacity.pid")" || { echo 'Previous benchmark ended without a status.' >&2;exit 1; };sleep 20;done
printf '%s\n' "$(< "$capacity.exit")" > "$out/prior-benchmark-status.txt"
jq -e '.sameTrainingData and .initialWeightsIdentical and .trainingOrdersIdentical and .mirrorMasksIdentical and .optimizerStepsPerModel==109 and .reversalPenaltyMilli==1000 and .reservedFinalStillRequired and (.automaticPromotion|not)' "$pair/comparison.json" > /dev/null
data_sha="$(jq -er '.dataSHA256' "$baseline/receipt.json")";baseline_sha="$(sha256sum "$baseline/weights.bin" | cut -d' ' -f1)";candidate_sha="$(sha256sum "$candidate/weights.bin" | cut -d' ' -f1)"
jq -e --arg data "$data_sha" --arg sha "$baseline_sha" '.dataSHA256==$data and .weightsSHA256==$sha and .memoryWidth==256 and (.taskFeedback|not)' "$baseline/receipt.json" > /dev/null
jq -e --arg data "$data_sha" --arg sha "$candidate_sha" '.dataSHA256==$data and .weightsSHA256==$sha and .memoryWidth==256 and .reversalPenaltyMilli==1000 and (.taskFeedback|not)' "$candidate/receipt.json" > /dev/null
jq -e --arg data "$data_sha" '.passed and .dataSHA256==$data and .corpusHistories==310 and .episodes==8 and .exactCaseAndEnvironmentFilesDisjoint and .reservedFinalUntouched' "$audit/summary.json" > /dev/null
sha256sum "$driver" "$pair/comparison.json" "$baseline/weights.bin" "$baseline/receipt.json" "$candidate/weights.bin" "$candidate/receipt.json" "$audit/summary.json" > "$out/inputs.sha256"
for arm in baseline candidate;do
    policy="$baseline";if [[ "$arm" == candidate ]];then policy="$candidate";fi
    PUPPYBOT_PROJECT="$project" PUPPYBOT_DIVERSE_POLICY="$policy" PUPPYBOT_DIVERSE_CORPUS_AUDIT="$audit" PUPPYBOT_DIVERSE_WAIT_RUN="$capacity" PUPPYBOT_DIVERSE_BENCHMARK_OUT="$out/$arm" bash "$driver" > "$out/$arm.log" 2>&1
    [[ "$(< "$out/$arm/run.exit")" == 0 ]]
done
for arm in baseline candidate;do
    sha="$baseline_sha";if [[ "$arm" == candidate ]];then sha="$candidate_sha";fi
    jq -e --arg sha "$sha" '.passed and .developmentOnly and .episodes==8 and .auditedEpisodes==8 and .uniqueStartingPoses==8 and ([.rows[].caseIndex]|sort)==[range(0;8)] and .policyWeightsSHA256==$sha and all(.rows[]; .auditPassed and .policyWeightsSHA256==$sha and (.suppliedMap|not) and (.taskEventHint|not))' "$out/$arm/score.json" > /dev/null
done
for ((index=0;index<8;index++));do seed=$((9980000+index));for file in case.json environment.bin;do cmp "$out/baseline/$index/$seed/scene/$file" "$out/candidate/$index/$seed/scene/$file";done;done
jq -n --slurpfile a "$out/baseline/score.json" --slurpfile b "$out/candidate/score.json" '
  [$b[0].rows[] as $new | $a[0].rows[] | select(.caseIndex==$new.caseIndex) |
   {caseIndex,layoutId,seed,startPose,matchingCase:(.layoutId==$new.layoutId and .seed==$new.seed and .startPose==$new.startPose),baselineApproach:.found,candidateApproach:$new.found,baselineReturn:.physicalReturned,candidateReturn:$new.physicalReturned}] as $pairs |
  {complete:true,developmentOnly:true,selectedUsingPreviousDevelopmentCases:true,identicalCases:(($pairs|length)==8 and all($pairs[];.matchingCase)),uniqueStartingPoses:($pairs|map(.startPose)|unique|length),sameTrainingData:true,trainingOrdersIdentical:true,reversalPenaltyMilli:1000,optimizerStepsPerModel:109,
   baseline:{approaches:$a[0].approaches,returns:$a[0].returns,twoRoomExits:$a[0].twoRoomExits,meanSuccessfulSimulationSeconds:$a[0].meanSuccessfulSimulationSeconds},candidate:{approaches:$b[0].approaches,returns:$b[0].returns,twoRoomExits:$b[0].twoRoomExits,meanSuccessfulSimulationSeconds:$b[0].meanSuccessfulSimulationSeconds},
   gainedApproaches:($pairs|map(select((.baselineApproach|not) and .candidateApproach))|length),lostApproaches:($pairs|map(select(.baselineApproach and (.candidateApproach|not)))|length),reservedFinalStillRequired:true,automaticPromotion:false,rows:$pairs}' > "$out/comparison.json"
jq -e '.complete and .identicalCases and .uniqueStartingPoses==8 and .reservedFinalStillRequired and (.automaticPromotion|not)' "$out/comparison.json" > /dev/null
sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
echo 'Reversal penalty and matched baseline compared on eight distinct starts.'
