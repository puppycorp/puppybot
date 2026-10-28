#!/usr/bin/env bash
# Compare longer training with its 316-history baseline on varied starts.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
root="$project/build/flex/sim/expanded-rooms-v1/large-model-v1"
training="$root/longer-316-queue-v1/run";screen="$root/longer-316-screen-v1";baseline="$root/diverse-development-316-baseline-v1"
driver="${PUPPYBOT_DIVERSE_FROZEN_BENCHMARK:?Frozen benchmark driver required}"
out="${PUPPYBOT_LONGER_DIVERSE_OUT:?New output directory required}"
[[ ! -e "$out" ]];mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
for job in "$training" "$baseline/run";do
    while [[ ! -f "$job.exit" ]];do [[ -f "$job.pid" ]] && kill -0 "$(< "$job.pid")" || { echo "$job ended without a status." >&2;exit 1; };sleep 20;done
    [[ "$(< "$job.exit")" == 0 ]] || { echo "$job failed; comparison not started." >&2;exit 1; }
done
jq -e '.sameTrainingData and .initialWeightsIdentical and .firstTrainingOrderIdentical and .firstOptimizerUpdateIdentical and .baselineOptimizerSteps==98 and .candidateOptimizerSteps==1110 and (.automaticPromotion|not)' "$screen/comparison.json" > /dev/null
baseline_sha="$(sha256sum "$root/coverage-v2-student-training-v1/policy/weights.bin" | cut -d' ' -f1)";candidate_sha="$(sha256sum "$screen/policy/weights.bin" | cut -d' ' -f1)"
jq -e --arg sha "$baseline_sha" '.passed and .developmentOnly and .episodes==8 and .auditedEpisodes==8 and .uniqueStartingPoses==8 and ([.rows[].caseIndex]|sort)==[range(0;8)] and .policyWeightsSHA256==$sha and all(.rows[]; .auditPassed and .policyWeightsSHA256==$sha and (.suppliedMap|not) and (.taskEventHint|not))' "$baseline/score.json" > /dev/null
sha256sum "$driver" "$screen/comparison.json" "$screen/policy/weights.bin" "$screen/policy/receipt.json" "$baseline/score.json" "$root/coverage-v2-student-training-v1/policy/weights.bin" > "$out/inputs.sha256"
PUPPYBOT_PROJECT="$project" PUPPYBOT_DIVERSE_POLICY="$screen/policy" PUPPYBOT_DIVERSE_WAIT_RUN="$baseline/run" PUPPYBOT_DIVERSE_BENCHMARK_OUT="$out/candidate" bash "$driver" > "$out/candidate.log" 2>&1
[[ "$(< "$out/candidate/run.exit")" == 0 ]]
jq -e --arg sha "$candidate_sha" '.passed and .developmentOnly and .episodes==8 and .auditedEpisodes==8 and .uniqueStartingPoses==8 and ([.rows[].caseIndex]|sort)==[range(0;8)] and .policyWeightsSHA256==$sha and all(.rows[]; .auditPassed and .policyWeightsSHA256==$sha and (.suppliedMap|not) and (.taskEventHint|not))' "$out/candidate/score.json" > /dev/null
for ((index=0;index<8;index++));do seed=$((9980000+index));for file in case.json environment.bin;do cmp "$baseline/$index/$seed/scene/$file" "$out/candidate/$index/$seed/scene/$file";done;done
jq -n --slurpfile a "$baseline/score.json" --slurpfile b "$out/candidate/score.json" '
    [$b[0].rows[] as $new | $a[0].rows[] | select(.caseIndex==$new.caseIndex) |
      {caseIndex,layoutId,seed,startPose,matchingCase:(.layoutId==$new.layoutId and .seed==$new.seed and .startPose==$new.startPose),baselineApproach:.found,candidateApproach:$new.found,baselineReturn:.physicalReturned,candidateReturn:$new.physicalReturned}] as $pairs |
    {complete:true,developmentOnly:true,identicalCases:(($pairs|length)==8 and all($pairs[];.matchingCase)),uniqueStartingPoses:($pairs|map(.startPose)|unique|length),sameTrainingData:true,firstOptimizerUpdateIdentical:true,baselineOptimizerSteps:98,candidateOptimizerSteps:1110,validationCheckpointSelectionCanDiffer:true,
     baseline:{approaches:$a[0].approaches,returns:$a[0].returns,twoRoomExits:$a[0].twoRoomExits,meanSuccessfulSimulationSeconds:$a[0].meanSuccessfulSimulationSeconds},candidate:{approaches:$b[0].approaches,returns:$b[0].returns,twoRoomExits:$b[0].twoRoomExits,meanSuccessfulSimulationSeconds:$b[0].meanSuccessfulSimulationSeconds},reservedFinalStillRequired:true,automaticPromotion:false,rows:$pairs}' > "$out/comparison.json"
jq -e '.complete and .identicalCases and .uniqueStartingPoses==8 and .reservedFinalStillRequired and (.automaticPromotion|not)' "$out/comparison.json" > /dev/null
sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
echo 'Longer-trained policy and same-data baseline compared on eight distinct starts.'
