#!/usr/bin/env bash
# Pose supervision must retain the neutral actor and use verified targets.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]]
PUPPYBOT_PROJECT="$project" bash "$project/datasets/visual-control/expanded-rooms-v1/test-neutral-drive-training.sh" "$out" > /dev/null
mock="$out/mock";root="$mock/build/flex/sim/expanded-rooms-v1/large-model-v1";baseline="$root/neutral-drive-training-v2";pose="$root/memory-pose-354-v2";runtime="$root/neutral-drive-runtime-v1/runtime";data="$root/incomplete-return-admission-v1/expanded/data.bin"
ln -s "$out/neutral-trained" "$baseline";mkdir -p "$pose/targets" "$root/feedback-drop-pose-gradient-v1";printf '0\n' > "$pose/run.exit";printf 'pose targets\n' > "$pose/targets/targets.bin"
data_sha="$(sha256sum "$data" | cut -d' ' -f1)";pose_sha="$(sha256sum "$pose/targets/targets.bin" | cut -d' ' -f1)"
jq -n --arg data "$data_sha" --arg pose "$pose_sha" '{passed:true,verifiedAgainstPhysicalTrace:true,sourceFilesStableDuringVerification:true,actorInputsUnchanged:true,preActionRGBAndFeedbackMatched:true,inverseTransformChecked:true,episodes:354,fittingHistories:240,validationHistories:114,sourceDataSHA256:$data,targetsSHA256:$pose}' > "$pose/targets/receipt.json"
printf '{"passed":true,"feedbackDropChecked":true,"fullCNNAndGRU":true,"tensorsChecked":26,"maxGradientAbsError":0.0001,"maxAdamAbsError":0.0000001}\n' > "$root/feedback-drop-pose-gradient-v1/result.json"
cat > "$out/fake-compare-initial" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${PUPPYBOT_TEST_BAD_INITIAL:-0}" == 1 ]];then exit 1;fi
printf '{"passed":true,"allOriginalParametersByteIdentical":true,"addedPoseHeadOnly":true,"memoryWidth":256,"addedPoseParameters":1028}\n' > "$3"
EOF
cat > "$runtime/build/flex/control/control" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ "$1" == train ]];shift;drop="";pose=""
while (( $# ));do case "$1" in --output) output="$2";shift 2;; --data) data="$2";shift 2;; --initial-policy) initial="$2";shift 2;; --target-heatmap) targets="$2";shift 2;; --drop-drive-feedback-milli) drop="$2";shift 2;; --memory-pose) pose="$2";shift 2;; *) shift;; esac;done
[[ "$drop" == 1000 && -n "$pose" ]];mkdir "$output";cp "$initial/weights.bin" "$output/initial.bin";cp "$initial/weights.bin" "$output/first-after.bin";cp "$initial/weights.bin" "$output/weights.bin"
cp "$PUPPYBOT_TEST_BASELINE/policy/first-order.bin" "$output/first-order.bin";cp "$PUPPYBOT_TEST_BASELINE/policy/first-mirror-mask.bin" "$output/first-mirror-mask.bin"
data_sha="$(sha256sum "$data" | cut -d' ' -f1)";initial_sha="$(sha256sum "$initial/weights.bin" | cut -d' ' -f1)";target_sha="$(sha256sum "$targets/targets.bin" | cut -d' ' -f1)";pose_sha="$(sha256sum "$pose/targets.bin" | cut -d' ' -f1)";if [[ "${PUPPYBOT_TEST_BAD_POSE_TARGET:-0}" == 1 ]];then pose_sha=wrong;fi
jq -n --arg data "$data_sha" --arg initial "$initial_sha" --arg target "$target_sha" --arg pose "$pose_sha" '{dataSHA256:$data,targetPositionTargetsSHA256:$target,memoryPoseTargetsSHA256:$pose,memoryPoseAuxiliary:true,initialWeightsSHA256:$initial,memoryWidth:256,epochs:1,batch:2,learningRateMicros:100,seed:202,maxOptimizerSteps:98,phaseGatedNavigation:true,sequenceMirrorAugmentation:true,heatmapActorGradientDetached:true,driveFeedbackDropMilli:1000,taskFeedback:false}' > "$output/receipt.json"
printf '{"epoch":1,"optimizerSteps":98,"driveFeedbackDroppedSequences":196,"selected":true}\n' > "$output/curves.jsonl"
EOF
chmod +x "$out/fake-compare-initial" "$runtime/build/flex/control/control"
sha256sum "$runtime/build/flex/control/control" "$runtime/build/flex/control/trainer" "$runtime/build/flex/control/simulator" "$root/feedback-drop-tests-v1/validation.json" > "$root/neutral-drive-runtime-v1/inputs.sha256"
driver="$project/datasets/visual-control/expanded-rooms-v1/train-neutral-pose.sh"
export PUPPYBOT_PROJECT="$mock" PUPPYBOT_TEST_BASELINE="$baseline" PUPPYBOT_NEUTRAL_POSE_COMPARE_INITIAL="$out/fake-compare-initial" PUPPYBOT_NEUTRAL_POSE_VERIFY_ZERO="$out/fake-zero" PUPPYBOT_NEUTRAL_POSE_WAIT_RUN="$root/capacity/run"
PUPPYBOT_NEUTRAL_POSE_OUT="$out/pose-trained" bash "$driver" > "$out/pose-trained.log" 2>&1
jq -e '.sameTrainingData and .sameValidationData and .trainingOrdersIdentical and .firstMirrorMasksIdentical and .optimizerStepsPerModel==98 and .initialActorTensorsIdentical and .poseTargetsTrainingOnly and .poseLossChangesValidationSelection and .driveFeedbackDropMilli==1000 and .driveFeedbackRowsStayedZero and .contactFeedbackPreserved and (.automaticPromotion|not)' "$out/pose-trained/comparison.json" > /dev/null
for fault in PUPPYBOT_TEST_BAD_INITIAL PUPPYBOT_TEST_BAD_POSE_TARGET PUPPYBOT_TEST_NONZERO;do
    if env "$fault=1" PUPPYBOT_NEUTRAL_POSE_OUT="$out/$fault-pose" bash "$driver" > "$out/$fault-pose.log" 2>&1;then echo "$fault was accepted." >&2;exit 1;fi
    [[ "$(< "$out/$fault-pose/run.exit")" != 0 && ! -e "$out/$fault-pose/comparison.json" ]]
done
echo 'Neutral-pose training checks target provenance, actor initialization and zero feedback rows.'
