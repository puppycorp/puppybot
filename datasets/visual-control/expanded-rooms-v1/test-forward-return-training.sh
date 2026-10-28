#!/usr/bin/env bash
# Verify equal-update comparison, new-history exposure and inference boundaries.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]]
PUPPYBOT_PROJECT="$project" bash "$project/datasets/visual-control/expanded-rooms-v1/test-neutral-drive-training.sh" "$out" > /dev/null
mock="$out/mock";root="$mock/build/flex/sim/expanded-rooms-v1/large-model-v1";old="$root/incomplete-return-admission-v1";admission="$root/forward-return-admission-v1";runtime="$root/neutral-drive-runtime-v1/runtime"
mkdir -p "$admission/known/expanded" "$admission/known/targets";printf '0\n' > "$admission/run.exit";printf 'new data\n' > "$admission/known/expanded/data.bin";printf 'new targets\n' > "$admission/known/targets/targets.bin";printf '{}\n' > "$admission/known/targets/receipt.json"
old_sha="$(sha256sum "$old/expanded/data.bin" | cut -d' ' -f1)";new_sha="$(sha256sum "$admission/known/expanded/data.bin" | cut -d' ' -f1)"
jq -n --arg old "$old_sha" --arg sha "$new_sha" '{passed:true,episodes:358,fittingHistories:242,validationHistories:116,addedTeacherHistories:4,incompleteAddedEpisodes:1,studentActionsReplayed:4,oldDataSHA256:$old,dataSHA256:$sha,reusedScenesSameSplit:true,existingDataBytePreserved:true,existingTargetsBytePreserved:true,newHistoriesIndependentlyAudited:true,teacherSearchGoalsReconstructed:true,teacherLabelsTrainingOnly:true,actorInputsUnchanged:true,incompleteEpisodesClaimedSuccessful:false,automaticPromotion:false}' > "$admission/coverage.json"
for i in 240 241 356 357;do mkdir "$admission/audit-$i";printf '{}\n' > "$admission/audit-$i/result.json";done
cat > "$runtime/build/flex/control/control" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ "$1" == train ]];shift;drop='';seed=''
while (( $# ));do case "$1" in --output) output="$2";shift 2;; --data) data="$2";shift 2;; --initial-policy) initial="$2";shift 2;; --target-heatmap) targets="$2";shift 2;; --drop-drive-feedback-milli) drop="$2";shift 2;; --seed) seed="$2";shift 2;; *) shift;; esac;done
[[ "$drop" == 1000 && "$seed" == 203 ]];mkdir "$output";cp "$initial/weights.bin" "$output/initial.bin";cp "$initial/weights.bin" "$output/first-after.bin";cp "$initial/weights.bin" "$output/weights.bin"
if [[ "$data" == */forward-return-admission-v1/* && "${PUPPYBOT_TEST_OMIT_NEW:-0}" != 1 ]];then perl -e 'binmode STDOUT; print pack("Q<",$_) for (0..193,240,241)' > "$output/first-order.bin";else perl -e 'binmode STDOUT; print pack("Q<",$_) for (0..195)' > "$output/first-order.bin";fi
data_sha="$(sha256sum "$data" | cut -d' ' -f1)";initial_sha="$(sha256sum "$initial/weights.bin" | cut -d' ' -f1)";target_sha="$(sha256sum "$targets/targets.bin" | cut -d' ' -f1)";if [[ "${PUPPYBOT_TEST_BAD_TARGET:-0}" == 1 ]];then target_sha=wrong;fi
jq -n --arg data "$data_sha" --arg initial "$initial_sha" --arg target "$target_sha" '{dataSHA256:$data,targetPositionTargetsSHA256:$target,initialWeightsSHA256:$initial,memoryWidth:256,epochs:1,batch:2,learningRateMicros:100,seed:203,maxOptimizerSteps:98,phaseGatedNavigation:true,sequenceMirrorAugmentation:true,heatmapActorGradientDetached:true,driveFeedbackDropMilli:1000,memoryPoseAuxiliary:false,taskFeedback:false}' > "$output/receipt.json"
jq -n '{epoch:1,optimizerSteps:98,driveFeedbackDroppedSequences:196,selected:true}' > "$output/curves.jsonl"
EOF
chmod +x "$runtime/build/flex/control/control"
sha256sum "$runtime/build/flex/control/control" "$runtime/build/flex/control/trainer" "$runtime/build/flex/control/simulator" "$root/feedback-drop-tests-v1/validation.json" > "$root/neutral-drive-runtime-v1/inputs.sha256"
driver="$project/datasets/visual-control/expanded-rooms-v1/train-forward-return-pilot.sh"
export PUPPYBOT_PROJECT="$mock" PUPPYBOT_FORWARD_RETURN_VERIFY_ZERO="$out/fake-zero" PUPPYBOT_FORWARD_RETURN_WAIT_RUN="$root/capacity/run"
PUPPYBOT_FORWARD_RETURN_TRAIN_OUT="$out/forward-trained" bash "$driver" > "$out/forward-trained.log" 2>&1
jq -e '.sameInitialActorParameters and .sameSeed and .seed==203 and .trainingDataDiffer and .validationDataDiffer and .bothNewFittingHistoriesSampled and .optimizerStepsPerModel==98 and .driveFeedbackDropMilli==1000 and .driveFeedbackRowsStayedZero and (.automaticPromotion|not)' "$out/forward-trained/comparison.json" > /dev/null
for fault in PUPPYBOT_TEST_NONZERO PUPPYBOT_TEST_OMIT_NEW PUPPYBOT_TEST_BAD_TARGET;do
    if env "$fault=1" PUPPYBOT_FORWARD_RETURN_TRAIN_OUT="$out/$fault-forward" bash "$driver" > "$out/$fault-forward.log" 2>&1;then echo "$fault was accepted." >&2;exit 1;fi
    [[ "$(< "$out/$fault-forward/run.exit")" != 0 && ! -e "$out/$fault-forward/comparison.json" ]]
done
echo 'Forward-return training checks sample exposure, target provenance and zero feedback.'
