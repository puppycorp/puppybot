#!/usr/bin/env bash
# Compare expanded teacher data with the 316-history baseline on varied starts.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
root="$project/build/flex/sim/expanded-rooms-v1/large-model-v1"
screen="$root/coverage-scale-training-v1";admission="$root/coverage-scale-admission-v1";baseline="$root/diverse-development-316-baseline-v1";scenes="$root/diverse-development-v1"
audit_driver="${PUPPYBOT_SCALE_DIVERSE_AUDIT:?Frozen corpus audit required}"
benchmark="${PUPPYBOT_SCALE_DIVERSE_BENCHMARK:?Frozen diverse benchmark required}"
capacity="${PUPPYBOT_SCALE_DIVERSE_WAIT_RUN:?Previous benchmark required}"
out="${PUPPYBOT_SCALE_DIVERSE_OUT:?New output directory required}"
[[ ! -e "$out" ]];mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
for job in "$screen/run" "$admission/run" "$baseline/run";do
    while [[ ! -f "$job.exit" ]];do [[ -f "$job.pid" ]] && kill -0 "$(< "$job.pid")" || { echo "$job ended without a status." >&2;exit 1; };sleep 20;done
    [[ "$(< "$job.exit")" == 0 ]] || { echo "$job failed; comparison not started." >&2;exit 1; }
done
while [[ ! -f "$capacity.exit" ]];do [[ -f "$capacity.pid" ]] && kill -0 "$(< "$capacity.pid")" || { echo 'Previous benchmark ended without a status.' >&2;exit 1; };sleep 20;done
printf '%s\n' "$(< "$capacity.exit")" > "$out/prior-benchmark-status.txt"
jq -e '.initialWeightsIdentical and .differentTrainingData and .optimizerStepsPerModel==98 and .addedFittingHistoriesSeen>0 and .validationSetsDiffer and .shuffleAndCheckpointSelectionLimitCausalInterpretation and .reservedFinalStillRequired and (.automaticPromotion|not)' "$screen/comparison.json" > /dev/null
baseline_sha="$(sha256sum "$root/coverage-v2-student-training-v1/policy/weights.bin" | cut -d' ' -f1)";candidate_sha="$(sha256sum "$screen/policy/weights.bin" | cut -d' ' -f1)";data_sha="$(jq -er '.dataSHA256' "$screen/policy/receipt.json")"
jq -e --arg sha "$baseline_sha" '.passed and .developmentOnly and .episodes==8 and .auditedEpisodes==8 and .uniqueStartingPoses==8 and ([.rows[].caseIndex]|sort)==[range(0;8)] and .policyWeightsSHA256==$sha and all(.rows[]; .auditPassed and .policyWeightsSHA256==$sha and (.suppliedMap|not) and (.taskEventHint|not))' "$baseline/score.json" > /dev/null
sha256sum "$audit_driver" "$benchmark" "$screen/comparison.json" "$screen/policy/weights.bin" "$screen/policy/receipt.json" "$baseline/score.json" "$root/coverage-v2-student-training-v1/policy/weights.bin" > "$out/inputs.sha256"
bash "$audit_driver" "$scenes" "$admission" "$out/corpus-audit" > "$out/corpus-audit.log" 2>&1
jq -e --arg sha "$data_sha" '.passed and .dataSHA256==$sha and .corpusHistories==348 and .episodes==8 and .exactCaseAndEnvironmentFilesDisjoint and .reservedFinalUntouched' "$out/corpus-audit/summary.json" > /dev/null
PUPPYBOT_PROJECT="$project" PUPPYBOT_DIVERSE_POLICY="$screen/policy" PUPPYBOT_DIVERSE_CORPUS_AUDIT="$out/corpus-audit" PUPPYBOT_DIVERSE_WAIT_RUN="$capacity" PUPPYBOT_DIVERSE_BENCHMARK_OUT="$out/candidate" bash "$benchmark" > "$out/candidate.log" 2>&1
[[ "$(< "$out/candidate/run.exit")" == 0 ]]
jq -e --arg sha "$candidate_sha" '.passed and .developmentOnly and .episodes==8 and .auditedEpisodes==8 and .uniqueStartingPoses==8 and ([.rows[].caseIndex]|sort)==[range(0;8)] and .policyWeightsSHA256==$sha and all(.rows[]; .auditPassed and .policyWeightsSHA256==$sha and (.suppliedMap|not) and (.taskEventHint|not))' "$out/candidate/score.json" > /dev/null
for ((index=0;index<8;index++));do seed=$((9980000+index));for file in case.json environment.bin;do cmp "$baseline/$index/$seed/scene/$file" "$out/candidate/$index/$seed/scene/$file";done;done
jq -n --slurpfile a "$baseline/score.json" --slurpfile b "$out/candidate/score.json" --slurpfile screen "$screen/comparison.json" '
  [$b[0].rows[] as $new | $a[0].rows[] | select(.caseIndex==$new.caseIndex) |
   {caseIndex,layoutId,seed,startPose,matchingCase:(.layoutId==$new.layoutId and .seed==$new.seed and .startPose==$new.startPose),baselineApproach:.found,candidateApproach:$new.found,baselineReturn:.physicalReturned,candidateReturn:$new.physicalReturned}] as $pairs |
  {complete:true,developmentOnly:true,identicalCases:(($pairs|length)==8 and all($pairs[];.matchingCase)),uniqueStartingPoses:($pairs|map(.startPose)|unique|length),differentTrainingData:true,initialWeightsIdentical:true,optimizerStepsPerModel:98,trainingOrdersIdentical:$screen[0].trainingOrdersIdentical,addedFittingHistoriesSeen:$screen[0].addedFittingHistoriesSeen,validationSetsDiffer:true,shuffleAndCheckpointSelectionLimitCausalInterpretation:true,
   baseline:{approaches:$a[0].approaches,returns:$a[0].returns,twoRoomExits:$a[0].twoRoomExits,meanSuccessfulSimulationSeconds:$a[0].meanSuccessfulSimulationSeconds},candidate:{approaches:$b[0].approaches,returns:$b[0].returns,twoRoomExits:$b[0].twoRoomExits,meanSuccessfulSimulationSeconds:$b[0].meanSuccessfulSimulationSeconds},reservedFinalStillRequired:true,automaticPromotion:false,rows:$pairs}' > "$out/comparison.json"
jq -e '.complete and .identicalCases and .uniqueStartingPoses==8 and .addedFittingHistoriesSeen>0 and .reservedFinalStillRequired and (.automaticPromotion|not)' "$out/comparison.json" > /dev/null
sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
echo 'Scaled teacher model compared with the 316-history baseline on eight distinct starts.'
