#!/usr/bin/env bash
# Compare policies trained with and without the forward-return pilot.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
root="$project/build/flex/sim/expanded-rooms-v1/large-model-v1";training="$root/forward-return-training-v1";old="$root/incomplete-return-admission-v1";admission="$root/forward-return-admission-v1"
scene_set="${PUPPYBOT_FORWARD_RETURN_SCENE_SET:-standard}"
if [[ "$scene_set" == standard ]];then scenes="$root/diverse-development-v1";first_seed=9980000
elif [[ "$scene_set" == wide-heading ]];then scenes="$root/wide-heading-development-v1";first_seed=9990000
else echo 'Expected standard or wide-heading scene set.' >&2;exit 2;fi
audit="${PUPPYBOT_FORWARD_RETURN_CORPUS_AUDIT:?Frozen corpus audit required}"
benchmark="${PUPPYBOT_FORWARD_RETURN_BENCHMARK:?Frozen benchmark required}"
input_audit="${PUPPYBOT_FORWARD_RETURN_INPUT_AUDIT:?Frozen initial input audit required}"
capacity="${PUPPYBOT_FORWARD_RETURN_BENCHMARK_WAIT_RUN:?Previous GPU job required}"
out="${PUPPYBOT_FORWARD_RETURN_BENCHMARK_OUT:?New output directory required}"
[[ ! -e "$out" ]];mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
for job in "$training/run" "$old/run" "$admission/run";do [[ "$(< "$job.exit")" == 0 ]];done
while [[ ! -f "$capacity.exit" ]];do [[ -f "$capacity.pid" ]] && kill -0 "$(< "$capacity.pid")" || { echo 'Previous GPU job ended without a status.' >&2;exit 1; };sleep 20;done
jq -e '.sameInitialActorParameters and .sameSeed and .seed==203 and .optimizerStepsPerModel==98 and .trainingDataDiffer and .validationDataDiffer and .bothNewFittingHistoriesSampled and .driveFeedbackDropMilli==1000 and .driveFeedbackRowsStayedZero and .contactFeedbackPreserved and (.automaticPromotion|not)' "$training/comparison.json" > /dev/null
jq -e '.passed and .episodes==358 and .reusedScenesSameSplit and .existingDataBytePreserved and .newHistoriesIndependentlyAudited and .actorInputsUnchanged and (.automaticPromotion|not)' "$admission/coverage.json" > /dev/null
mkdir "$out/expanded-corpus"
ln -s "$admission/known/expanded" "$out/expanded-corpus/expanded";ln -s "$admission/coverage.json" "$out/expanded-corpus/coverage.json";ln -s "$admission/run.exit" "$out/expanded-corpus/run.exit"
sha256sum "$audit" "$benchmark" "$input_audit" "$training/comparison.json" "$training"/{baseline,candidate}/policy/{weights.bin,receipt.json} "$old/coverage.json" "$admission/coverage.json" > "$out/inputs.sha256"
for kind in baseline candidate;do
    corpus="$old";expected=354;wait_run="$capacity";if [[ "$kind" == candidate ]];then corpus="$out/expanded-corpus";expected=358;wait_run="$out/baseline/run";fi
    policy="$training/$kind/policy";data_sha="$(jq -er '.dataSHA256' "$policy/receipt.json")";weights_sha="$(sha256sum "$policy/weights.bin" | cut -d' ' -f1)"
    jq -e --arg sha "$weights_sha" --arg data "$data_sha" '.weightsSHA256==$sha and .dataSHA256==$data and .seed==203 and .memoryWidth==256 and .driveFeedbackDropMilli==1000 and (.taskFeedback|not)' "$policy/receipt.json" > /dev/null
    bash "$audit" "$scenes" "$corpus" "$out/$kind-corpus-audit" > "$out/$kind-corpus-audit.log" 2>&1
    jq -e --arg sha "$data_sha" --argjson count "$expected" '.passed and .dataSHA256==$sha and .corpusHistories==$count and .episodes==8 and .exactCaseAndEnvironmentFilesDisjoint and .reservedFinalUntouched' "$out/$kind-corpus-audit/summary.json" > /dev/null
    PUPPYBOT_PROJECT="$project" PUPPYBOT_DIVERSE_POLICY="$policy" PUPPYBOT_DIVERSE_CORPUS_AUDIT="$out/$kind-corpus-audit" PUPPYBOT_DIVERSE_SCENE_SET="$scene_set" PUPPYBOT_DIVERSE_WAIT_RUN="$wait_run" PUPPYBOT_DIVERSE_BENCHMARK_OUT="$out/$kind" bash "$benchmark" > "$out/$kind.log" 2>&1
    [[ "$(< "$out/$kind/run.exit")" == 0 ]]
    jq -e --arg sha "$weights_sha" '.passed and .developmentOnly and .episodes==8 and .auditedEpisodes==8 and .uniqueStartingPoses==8 and ([.rows[].caseIndex]|sort)==[range(0;8)] and .policyWeightsSHA256==$sha and all(.rows[]; .auditPassed and .policyWeightsSHA256==$sha and (.suppliedMap|not) and (.taskEventHint|not))' "$out/$kind/score.json" > /dev/null
done
for ((index=0;index<8;index++));do seed=$((first_seed+index));for file in case.json environment.bin;do cmp "$out/baseline/$index/$seed/scene/$file" "$out/candidate/$index/$seed/scene/$file";done;done
bash "$input_audit" "$out/baseline" "$out/candidate" "$out/initial-input-audit" > "$out/initial-input-audit.log" 2>&1
jq -e '.passed and .episodes==8 and .sceneFilesIdentical and .initialActorImagesAndFeedbackIdentical and .policyReplaysPassed' "$out/initial-input-audit/summary.json" > /dev/null
jq -n --arg scene_set "$scene_set" --slurpfile a "$out/baseline/score.json" --slurpfile b "$out/candidate/score.json" '
 [$b[0].rows[] as $new | $a[0].rows[] | select(.caseIndex==$new.caseIndex) |
  {caseIndex,layoutId,seed,startPose,matchingCase:(.layoutId==$new.layoutId and .seed==$new.seed and .startPose==$new.startPose),baselineApproach:.found,candidateApproach:$new.found,baselineReturn:.physicalReturned,candidateReturn:$new.physicalReturned}] as $pairs |
 {complete:true,developmentOnly:true,sceneSet:$scene_set,identicalCases:(($pairs|length)==8 and all($pairs[];.matchingCase)),identicalInitialCameraAndOwnFeedback:true,uniqueStartingPoses:($pairs|map(.startPose)|unique|length),sameInitialActorParameters:true,sameSeed:true,optimizerStepsPerModel:98,trainingDataDiffer:true,validationDataDiffer:true,trainingOrderAndCheckpointSelectionMayDiffer:true,bothNewFittingHistoriesSampled:true,
 baseline:{approaches:$a[0].approaches,returns:$a[0].returns,twoRoomExits:$a[0].twoRoomExits,meanSuccessfulSimulationSeconds:$a[0].meanSuccessfulSimulationSeconds},candidate:{approaches:$b[0].approaches,returns:$b[0].returns,twoRoomExits:$b[0].twoRoomExits,meanSuccessfulSimulationSeconds:$b[0].meanSuccessfulSimulationSeconds},reservedFinalStillRequired:true,automaticPromotion:false,rows:$pairs}' > "$out/comparison.json"
jq -e '.complete and .identicalCases and .identicalInitialCameraAndOwnFeedback and .uniqueStartingPoses==8 and .trainingDataDiffer and .validationDataDiffer and .trainingOrderAndCheckpointSelectionMayDiffer and .bothNewFittingHistoriesSampled and .reservedFinalStillRequired and (.automaticPromotion|not)' "$out/comparison.json" > /dev/null
sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
echo 'Compared forward-return pilot policies on eight matched development scenes.'
