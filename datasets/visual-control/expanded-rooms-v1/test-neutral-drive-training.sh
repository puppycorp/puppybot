#!/usr/bin/env bash
# Neutral-drive training must preserve data/order and keep feedback rows zero.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]]
PUPPYBOT_PROJECT="$project" bash "$project/datasets/visual-control/expanded-rooms-v1/test-incomplete-return-training.sh" "$out" > /dev/null
mock="$out/mock";root="$mock/build/flex/sim/expanded-rooms-v1/large-model-v1";baseline="$root/incomplete-return-training-v1";initial="$root/neutral-drive-initial-v1";source="$root/expanded-236-mirrored";reference="$root/phase-large-tests-v1/runtime";runtime="$root/neutral-drive-runtime-v1/runtime"
mkdir -p "$root/neutral-drive-runtime-v1" "$root/feedback-drop-tests-v1"
cp -a "$reference" "$runtime";printf 'simulator\n' > "$reference/build/flex/control/simulator";cp "$reference/build/flex/control/simulator" "$runtime/build/flex/control/simulator"
printf '{"passed":true,"numericGradientAndMaskTests":true,"gpuDeterministic":true,"feedbackDropChangesGradient":true,"defaultBitIdenticalToPreviousRuntime":true,"validationUnmasked":true,"firstOrderAndMirrorMaskIdentical":true,"inferenceParity":true,"invalidRateRejected":true,"actorInterfaceUnchanged":true}\n' > "$root/feedback-drop-tests-v1/validation.json"
ln -s "$out/incomplete-trained" "$baseline";mkdir -p "$initial/policy";printf '0\n' > "$initial/run.exit";printf '0\n' > "$root/capacity/run.exit"
cp "$source/weights.bin" "$initial/policy/weights.bin";printf '{}\n' > "$initial/policy/receipt.json";printf 'mirror\n' > "$baseline/policy/first-mirror-mask.bin"
sha="$(sha256sum "$source/weights.bin" | cut -d' ' -f1)"
jq -n --arg sha "$sha" '{passed:true,parentWeightsSHA256:$sha,weightsSHA256:$sha,driveFeedbackValuesZeroed:5,contactFeedbackPreserved:true,otherWeightsPreserved:true,singleFrameForwardChecked:true,trainingPerformed:false,automaticPromotion:false}' > "$initial/summary.json"
cat > "$out/fake-ablate" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
cp "$1" "$2";printf '{}\n' > "$3"
EOF
cat > "$out/fake-zero" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${PUPPYBOT_TEST_NONZERO:-0}" == 1 ]];then exit 1;fi
sha="$(sha256sum "$1" | cut -d' ' -f1)";jq -n --arg sha "$sha" '{passed:true,weightsSHA256:$sha,bytesChecked:15360,driveFeedbackValuesZero:5}' > "$2"
EOF
cat > "$runtime/build/flex/control/control" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ "$1" == train ]];shift;drop=""
while (( $# ));do case "$1" in --output) output="$2";shift 2;; --data) data="$2";shift 2;; --initial-policy) initial="$2";shift 2;; --target-heatmap) targets="$2";shift 2;; --drop-drive-feedback-milli) drop="$2";shift 2;; *) shift;; esac;done
[[ "$drop" == 1000 ]];mkdir "$output";cp "$initial/weights.bin" "$output/initial.bin";cp "$initial/weights.bin" "$output/first-after.bin";cp "$initial/weights.bin" "$output/weights.bin"
cp "$PUPPYBOT_TEST_BASELINE/policy/first-order.bin" "$output/first-order.bin";cp "$PUPPYBOT_TEST_BASELINE/policy/first-mirror-mask.bin" "$output/first-mirror-mask.bin"
if [[ "${PUPPYBOT_TEST_BAD_ORDER:-0}" == 1 ]];then printf 'changed\n' > "$output/first-order.bin";fi
data_sha="$(sha256sum "$data" | cut -d' ' -f1)";initial_sha="$(sha256sum "$initial/weights.bin" | cut -d' ' -f1)";target_sha="$(sha256sum "$targets/targets.bin" | cut -d' ' -f1)";if [[ "${PUPPYBOT_TEST_BAD_TARGET:-0}" == 1 ]];then target_sha=wrong;fi
jq -n --arg data "$data_sha" --arg initial "$initial_sha" --arg target "$target_sha" '{dataSHA256:$data,targetPositionTargetsSHA256:$target,initialWeightsSHA256:$initial,memoryWidth:256,epochs:1,batch:2,learningRateMicros:100,seed:202,maxOptimizerSteps:98,phaseGatedNavigation:true,sequenceMirrorAugmentation:true,heatmapActorGradientDetached:true,driveFeedbackDropMilli:1000,taskFeedback:false}' > "$output/receipt.json"
dropped=196;if [[ "${PUPPYBOT_TEST_BAD_DROP:-0}" == 1 ]];then dropped=195;fi
jq -n --argjson dropped "$dropped" '{epoch:1,optimizerSteps:98,driveFeedbackDroppedSequences:$dropped,selected:true}' > "$output/curves.jsonl"
EOF
chmod +x "$out/fake-ablate" "$out/fake-zero" "$runtime/build/flex/control/control"
sha256sum "$runtime/build/flex/control/control" "$runtime/build/flex/control/trainer" "$runtime/build/flex/control/simulator" "$root/feedback-drop-tests-v1/validation.json" > "$root/neutral-drive-runtime-v1/inputs.sha256"
driver="$project/datasets/visual-control/expanded-rooms-v1/train-neutral-drive.sh"
export PUPPYBOT_PROJECT="$mock" PUPPYBOT_TEST_BASELINE="$baseline" PUPPYBOT_NEUTRAL_TRAIN_ABLATE="$out/fake-ablate" PUPPYBOT_NEUTRAL_TRAIN_VERIFY_ZERO="$out/fake-zero" PUPPYBOT_NEUTRAL_TRAIN_WAIT_RUN="$root/capacity/run"
PUPPYBOT_NEUTRAL_TRAIN_OUT="$out/neutral-trained" bash "$driver" > "$out/neutral-trained.log" 2>&1
jq -e '.sameTrainingData and .sameValidationData and .trainingOrdersIdentical and .firstMirrorMasksIdentical and .optimizerStepsPerModel==98 and .onlyInitialDriveFeedbackRowsAblated and .driveFeedbackDropMilli==1000 and .driveFeedbackRowsStayedZero and .contactFeedbackPreserved and .candidateEpochOneSelected and (.automaticPromotion|not)' "$out/neutral-trained/comparison.json" > /dev/null
for fault in PUPPYBOT_TEST_NONZERO PUPPYBOT_TEST_BAD_ORDER PUPPYBOT_TEST_BAD_TARGET PUPPYBOT_TEST_BAD_DROP;do
    if env "$fault=1" PUPPYBOT_NEUTRAL_TRAIN_OUT="$out/$fault-neutral" bash "$driver" > "$out/$fault-neutral.log" 2>&1;then echo "$fault was accepted." >&2;exit 1;fi
    [[ "$(< "$out/$fault-neutral/run.exit")" != 0 && ! -e "$out/$fault-neutral/comparison.json" ]]
done
echo 'Neutral-drive training rejects nonzero rows and changed order, targets or dropout.'
