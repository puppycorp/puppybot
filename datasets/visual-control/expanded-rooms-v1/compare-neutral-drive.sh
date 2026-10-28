#!/usr/bin/env bash
# Compare neutral-drive retraining with the same-data baseline policy.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
root="$project/build/flex/sim/expanded-rooms-v1/large-model-v1"
screen="$root/neutral-drive-training-v2";admission="$root/incomplete-return-admission-v1"
scene_set="${PUPPYBOT_NEUTRAL_SCENE_SET:-standard}"
if [[ "$scene_set" == standard ]];then baseline_job="$root/incomplete-return-standard-comparison-v1";scenes="$root/diverse-development-v1";first_seed=9980000
elif [[ "$scene_set" == wide-heading ]];then baseline_job="$root/incomplete-return-wide-comparison-v1";scenes="$root/wide-heading-development-v1";first_seed=9990000
else echo 'Expected standard or wide-heading scene set.' >&2;exit 2;fi
baseline="$baseline_job/candidate"
audit_driver="${PUPPYBOT_NEUTRAL_CORPUS_AUDIT:?Frozen corpus audit required}"
benchmark="${PUPPYBOT_NEUTRAL_BENCHMARK:?Frozen diverse benchmark required}"
verify_zero="${PUPPYBOT_NEUTRAL_VERIFY_ZERO:?Frozen zero verifier required}"
capacity="${PUPPYBOT_NEUTRAL_BENCHMARK_WAIT_RUN:?Previous benchmark required}"
out="${PUPPYBOT_NEUTRAL_BENCHMARK_OUT:?New output directory required}"
[[ ! -e "$out" ]];mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
for job in "$screen/run" "$admission/run" "$baseline_job/run";do
    while [[ ! -f "$job.exit" ]];do [[ -f "$job.pid" ]] && kill -0 "$(< "$job.pid")" || { echo "$job ended without a status." >&2;exit 1; };sleep 20;done
    [[ "$(< "$job.exit")" == 0 ]] || { echo "$job failed; comparison not started." >&2;exit 1; }
done
while [[ ! -f "$capacity.exit" ]];do [[ -f "$capacity.pid" ]] && kill -0 "$(< "$capacity.pid")" || { echo 'Previous benchmark ended without a status.' >&2;exit 1; };sleep 20;done
printf '%s\n' "$(< "$capacity.exit")" > "$out/prior-benchmark-status.txt"
baseline_sha="$(sha256sum "$root/incomplete-return-training-v1/policy/weights.bin" | cut -d' ' -f1)";candidate_sha="$(sha256sum "$screen/policy/weights.bin" | cut -d' ' -f1)";data_sha="$(jq -er '.dataSHA256' "$screen/policy/receipt.json")";corpus_histories="$(jq -er '.episodes | select(.==354)' "$admission/coverage.json")"
jq -e '.sameTrainingData and .sameValidationData and .trainingOrdersIdentical and .firstMirrorMasksIdentical and .optimizerStepsPerModel==98 and .onlyInitialDriveFeedbackRowsAblated and .driveFeedbackDropMilli==1000 and .driveFeedbackRowsStayedZero and .contactFeedbackPreserved and (.automaticPromotion|not)' "$screen/comparison.json" > /dev/null
jq -e --arg sha "$data_sha" '.dataSHA256==$sha and .memoryWidth==256 and (.taskFeedback|not)' "$root/incomplete-return-training-v1/policy/receipt.json" > /dev/null
jq -e --arg sha "$candidate_sha" --arg data "$data_sha" '.weightsSHA256==$sha and .dataSHA256==$data and .memoryWidth==256 and .driveFeedbackDropMilli==1000 and (.taskFeedback|not)' "$screen/policy/receipt.json" > /dev/null
"$verify_zero" "$screen/policy/weights.bin" "$out/zero.json"
jq -e --arg sha "$candidate_sha" '.passed and .weightsSHA256==$sha and .bytesChecked==15360 and .driveFeedbackValuesZero==5' "$out/zero.json" > /dev/null
jq -e --arg sha "$baseline_sha" '.passed and .developmentOnly and .episodes==8 and .auditedEpisodes==8 and .uniqueStartingPoses==8 and ([.rows[].caseIndex]|sort)==[range(0;8)] and .policyWeightsSHA256==$sha and all(.rows[]; .auditPassed and .policyWeightsSHA256==$sha and (.suppliedMap|not) and (.taskEventHint|not))' "$baseline/score.json" > /dev/null
sha256sum "$audit_driver" "$benchmark" "$verify_zero" "$screen/comparison.json" "$screen/policy/weights.bin" "$screen/policy/receipt.json" "$baseline/score.json" "$root/incomplete-return-training-v1/policy/weights.bin" "$admission/coverage.json" > "$out/inputs.sha256"
bash "$audit_driver" "$scenes" "$admission" "$out/corpus-audit" > "$out/corpus-audit.log" 2>&1
jq -e --arg sha "$data_sha" --argjson histories "$corpus_histories" '.passed and .dataSHA256==$sha and .corpusHistories==$histories and .episodes==8 and .exactCaseAndEnvironmentFilesDisjoint and .reservedFinalUntouched' "$out/corpus-audit/summary.json" > /dev/null
PUPPYBOT_PROJECT="$project" PUPPYBOT_DIVERSE_POLICY="$screen/policy" PUPPYBOT_DIVERSE_CORPUS_AUDIT="$out/corpus-audit" PUPPYBOT_DIVERSE_SCENE_SET="$scene_set" PUPPYBOT_DIVERSE_WAIT_RUN="$capacity" PUPPYBOT_DIVERSE_BENCHMARK_OUT="$out/candidate" bash "$benchmark" > "$out/candidate.log" 2>&1
[[ "$(< "$out/candidate/run.exit")" == 0 ]]
jq -e --arg sha "$candidate_sha" '.passed and .developmentOnly and .episodes==8 and .auditedEpisodes==8 and .uniqueStartingPoses==8 and ([.rows[].caseIndex]|sort)==[range(0;8)] and .policyWeightsSHA256==$sha and all(.rows[]; .auditPassed and .policyWeightsSHA256==$sha and (.suppliedMap|not) and (.taskEventHint|not))' "$out/candidate/score.json" > /dev/null
for ((index=0;index<8;index++));do seed=$((first_seed+index));for file in case.json environment.bin;do cmp "$baseline/$index/$seed/scene/$file" "$out/candidate/$index/$seed/scene/$file";done;done
jq -n --arg scene_set "$scene_set" --slurpfile a "$baseline/score.json" --slurpfile b "$out/candidate/score.json" --slurpfile training "$screen/comparison.json" '
  [$b[0].rows[] as $new | $a[0].rows[] | select(.caseIndex==$new.caseIndex) |
   {caseIndex,layoutId,seed,startPose,matchingCase:(.layoutId==$new.layoutId and .seed==$new.seed and .startPose==$new.startPose),baselineApproach:.found,candidateApproach:$new.found,baselineReturn:.physicalReturned,candidateReturn:$new.physicalReturned}] as $pairs |
  {complete:true,developmentOnly:true,sceneSet:$scene_set,identicalCases:(($pairs|length)==8 and all($pairs[];.matchingCase)),uniqueStartingPoses:($pairs|map(.startPose)|unique|length),sameTrainingData:true,sameValidationData:true,trainingOrdersIdentical:true,onlyInitialDriveFeedbackRowsAblated:true,driveFeedbackDropMilli:1000,driveFeedbackRowsStayedZero:true,contactFeedbackPreserved:true,candidateEpochOneSelected:$training[0].candidateEpochOneSelected,
   baseline:{approaches:$a[0].approaches,returns:$a[0].returns,twoRoomExits:$a[0].twoRoomExits,meanSuccessfulSimulationSeconds:$a[0].meanSuccessfulSimulationSeconds},candidate:{approaches:$b[0].approaches,returns:$b[0].returns,twoRoomExits:$b[0].twoRoomExits,meanSuccessfulSimulationSeconds:$b[0].meanSuccessfulSimulationSeconds},reservedFinalStillRequired:true,automaticPromotion:false,rows:$pairs}' > "$out/comparison.json"
jq -e '.complete and .identicalCases and .uniqueStartingPoses==8 and .sameTrainingData and .sameValidationData and .trainingOrdersIdentical and .onlyInitialDriveFeedbackRowsAblated and .driveFeedbackDropMilli==1000 and .driveFeedbackRowsStayedZero and .contactFeedbackPreserved and .reservedFinalStillRequired and (.automaticPromotion|not)' "$out/comparison.json" > /dev/null
sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
echo 'Neutral-drive retraining compared with its same-data baseline on eight distinct starts.'
