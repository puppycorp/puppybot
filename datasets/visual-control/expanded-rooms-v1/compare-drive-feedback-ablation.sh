#!/usr/bin/env bash
# Compare the drive-feedback weight ablation with its exact parent policy.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
root="$project/build/flex/sim/expanded-rooms-v1/large-model-v1"
screen="$root/drive-feedback-ablation-v1";admission="$root/incomplete-return-admission-v1"
scene_set="${PUPPYBOT_DRIVE_ABLATE_SCENE_SET:-standard}"
if [[ "$scene_set" == standard ]];then baseline_job="$root/incomplete-return-standard-comparison-v1";scenes="$root/diverse-development-v1";first_seed=9980000
elif [[ "$scene_set" == wide-heading ]];then baseline_job="$root/incomplete-return-wide-comparison-v1";scenes="$root/wide-heading-development-v1";first_seed=9990000
else echo 'Expected standard or wide-heading scene set.' >&2;exit 2;fi
baseline="$baseline_job/candidate"
audit_driver="${PUPPYBOT_DRIVE_ABLATE_CORPUS_AUDIT:?Frozen corpus audit required}"
benchmark="${PUPPYBOT_DRIVE_ABLATE_BENCHMARK:?Frozen diverse benchmark required}"
capacity="${PUPPYBOT_DRIVE_ABLATE_BENCHMARK_WAIT_RUN:?Previous benchmark required}"
out="${PUPPYBOT_DRIVE_ABLATE_BENCHMARK_OUT:?New output directory required}"
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
jq -e --arg parent "$baseline_sha" --arg sha "$candidate_sha" '.passed and .parentWeightsSHA256==$parent and .weightsSHA256==$sha and .driveFeedbackValuesZeroed==5 and .contactFeedbackPreserved and .otherWeightsPreserved and .singleFrameForwardChecked and (.trainingPerformed|not) and .closedLoopPerformanceNotMeasured and (.automaticPromotion|not)' "$screen/summary.json" > /dev/null
jq -e --arg sha "$data_sha" '.dataSHA256==$sha and .memoryWidth==256 and (.taskFeedback|not)' "$root/incomplete-return-training-v1/policy/receipt.json" > /dev/null
jq -e --arg parent "$baseline_sha" --arg sha "$candidate_sha" '.passed and .sourceSHA256==$parent and .weightsSHA256==$sha and .bytesZeroed==15360 and .driveFeedbackValuesZeroed==5' "$screen/ablation.json" > /dev/null
first="$(jq -er '.firstByte|select(type=="number" and .>=0 and floor==.)' "$screen/ablation.json")";removed="$(jq -er '.bytesZeroed' "$screen/ablation.json")"
cmp -n "$first" "$root/incomplete-return-training-v1/policy/weights.bin" "$screen/policy/weights.bin";cmp -i "$((first+removed))" "$root/incomplete-return-training-v1/policy/weights.bin" "$screen/policy/weights.bin"
dd if="$screen/policy/weights.bin" of="$out/zeroed.bin" bs=1 skip="$first" count="$removed" status=none;cmp -n "$removed" "$out/zeroed.bin" /dev/zero
cmp "$root/incomplete-return-training-v1/policy/policy" "$screen/policy/policy";cmp "$root/incomplete-return-training-v1/policy/model.pup" "$screen/policy/model.pup"
diff -qr "$root/incomplete-return-training-v1/policy/kernels" "$screen/policy/kernels" > "$out/kernel-comparison.log"
jq -e --arg sha "$baseline_sha" '.passed and .developmentOnly and .episodes==8 and .auditedEpisodes==8 and .uniqueStartingPoses==8 and ([.rows[].caseIndex]|sort)==[range(0;8)] and .policyWeightsSHA256==$sha and all(.rows[]; .auditPassed and .policyWeightsSHA256==$sha and (.suppliedMap|not) and (.taskEventHint|not))' "$baseline/score.json" > /dev/null
sha256sum "$audit_driver" "$benchmark" "$screen/summary.json" "$screen/ablation.json" "$screen/policy/weights.bin" "$screen/policy/receipt.json" "$baseline/score.json" "$root/incomplete-return-training-v1/policy/weights.bin" "$admission/coverage.json" > "$out/inputs.sha256"
bash "$audit_driver" "$scenes" "$admission" "$out/corpus-audit" > "$out/corpus-audit.log" 2>&1
jq -e --arg sha "$data_sha" --argjson histories "$corpus_histories" '.passed and .dataSHA256==$sha and .corpusHistories==$histories and .episodes==8 and .exactCaseAndEnvironmentFilesDisjoint and .reservedFinalUntouched' "$out/corpus-audit/summary.json" > /dev/null
PUPPYBOT_PROJECT="$project" PUPPYBOT_DIVERSE_POLICY="$screen/policy" PUPPYBOT_DIVERSE_CORPUS_AUDIT="$out/corpus-audit" PUPPYBOT_DIVERSE_SCENE_SET="$scene_set" PUPPYBOT_DIVERSE_WAIT_RUN="$capacity" PUPPYBOT_DIVERSE_BENCHMARK_OUT="$out/candidate" bash "$benchmark" > "$out/candidate.log" 2>&1
[[ "$(< "$out/candidate/run.exit")" == 0 ]]
jq -e --arg sha "$candidate_sha" '.passed and .developmentOnly and .episodes==8 and .auditedEpisodes==8 and .uniqueStartingPoses==8 and ([.rows[].caseIndex]|sort)==[range(0;8)] and .policyWeightsSHA256==$sha and all(.rows[]; .auditPassed and .policyWeightsSHA256==$sha and (.suppliedMap|not) and (.taskEventHint|not))' "$out/candidate/score.json" > /dev/null
for ((index=0;index<8;index++));do seed=$((first_seed+index));for file in case.json environment.bin;do cmp "$baseline/$index/$seed/scene/$file" "$out/candidate/$index/$seed/scene/$file";done;done
jq -n --arg scene_set "$scene_set" --slurpfile a "$baseline/score.json" --slurpfile b "$out/candidate/score.json" '
  [$b[0].rows[] as $new | $a[0].rows[] | select(.caseIndex==$new.caseIndex) |
   {caseIndex,layoutId,seed,startPose,matchingCase:(.layoutId==$new.layoutId and .seed==$new.seed and .startPose==$new.startPose),baselineApproach:.found,candidateApproach:$new.found,baselineReturn:.physicalReturned,candidateReturn:$new.physicalReturned}] as $pairs |
  {complete:true,developmentOnly:true,sceneSet:$scene_set,identicalCases:(($pairs|length)==8 and all($pairs[];.matchingCase)),uniqueStartingPoses:($pairs|map(.startPose)|unique|length),sameTrainingData:true,onlyDriveFeedbackWeightsAblated:true,contactFeedbackPreserved:true,trainingPerformed:false,
   baseline:{approaches:$a[0].approaches,returns:$a[0].returns,twoRoomExits:$a[0].twoRoomExits,meanSuccessfulSimulationSeconds:$a[0].meanSuccessfulSimulationSeconds},candidate:{approaches:$b[0].approaches,returns:$b[0].returns,twoRoomExits:$b[0].twoRoomExits,meanSuccessfulSimulationSeconds:$b[0].meanSuccessfulSimulationSeconds},reservedFinalStillRequired:true,automaticPromotion:false,rows:$pairs}' > "$out/comparison.json"
jq -e '.complete and .identicalCases and .uniqueStartingPoses==8 and .sameTrainingData and .onlyDriveFeedbackWeightsAblated and .contactFeedbackPreserved and (.trainingPerformed|not) and .reservedFinalStillRequired and (.automaticPromotion|not)' "$out/comparison.json" > /dev/null
sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
echo 'Drive-feedback ablation compared with its parent on eight distinct starts.'
