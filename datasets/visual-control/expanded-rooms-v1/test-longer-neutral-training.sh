#!/usr/bin/env bash
# Longer training must match the baseline's first optimizer update.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]]
PUPPYBOT_PROJECT="$project" bash "$project/datasets/visual-control/expanded-rooms-v1/test-forward-return-training.sh" "$out" > /dev/null
mock="$out/mock";root="$mock/build/flex/sim/expanded-rooms-v1/large-model-v1";baseline="$root/forward-return-training-v1/baseline";runtime="$root/neutral-drive-runtime-v1/runtime"
ln -s "$out/forward-trained" "$root/forward-return-training-v1"
for file in first-mirror-mask.bin first-feedback-drop-mask.bin first-gradients.bin;do printf '%s\n' "$file" > "$baseline/policy/$file";done
cat > "$runtime/build/flex/control/control" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ "$1" == train ]];shift;drop='';seed='';epochs='';steps=''
while (( $# ));do case "$1" in --output) output="$2";shift 2;; --data) data="$2";shift 2;; --initial-policy) initial="$2";shift 2;; --target-heatmap) targets="$2";shift 2;; --drop-drive-feedback-milli) drop="$2";shift 2;; --seed) seed="$2";shift 2;; --epochs) epochs="$2";shift 2;; --max-optimizer-steps) steps="$2";shift 2;; *) shift;; esac;done
[[ "$drop" == 1000 && "$seed" == 203 && "$epochs" == 3 && "$steps" == 360 ]];mkdir "$output"
for file in initial.bin first-order.bin first-mirror-mask.bin first-feedback-drop-mask.bin first-gradients.bin first-after.bin;do cp "$PUPPYBOT_TEST_LONGER_BASELINE/policy/$file" "$output/$file";done
cp "$initial/weights.bin" "$output/weights.bin"
if [[ "${PUPPYBOT_TEST_BAD_FIRST:-0}" == 1 ]];then printf 'different\n' > "$output/first-after.bin";fi
data_sha="$(sha256sum "$data" | cut -d' ' -f1)";initial_sha="$(sha256sum "$initial/weights.bin" | cut -d' ' -f1)";target_sha="$(sha256sum "$targets/targets.bin" | cut -d' ' -f1)";if [[ "${PUPPYBOT_TEST_BAD_TARGET:-0}" == 1 ]];then target_sha=wrong;fi
jq -n --arg data "$data_sha" --arg initial "$initial_sha" --arg target "$target_sha" '{dataSHA256:$data,targetPositionTargetsSHA256:$target,initialWeightsSHA256:$initial,memoryWidth:256,epochs:3,batch:2,learningRateMicros:100,seed:203,maxOptimizerSteps:360,phaseGatedNavigation:true,sequenceMirrorAugmentation:true,heatmapActorGradientDetached:true,driveFeedbackDropMilli:1000,memoryPoseAuxiliary:false,taskFeedback:false}' > "$output/receipt.json"
printf '{"epoch":0,"optimizerSteps":0,"selected":true}\n{"epoch":1,"optimizerSteps":120,"selected":true}\n{"epoch":2,"optimizerSteps":240,"selected":true}\n' > "$output/curves.jsonl"
dropped=720;if [[ "${PUPPYBOT_TEST_BAD_DROP:-0}" == 1 ]];then dropped=719;fi
jq -n --argjson dropped "$dropped" '{epoch:3,optimizerSteps:360,driveFeedbackDroppedSequences:$dropped,selected:true}' >> "$output/curves.jsonl"
EOF
chmod +x "$runtime/build/flex/control/control"
sha256sum "$runtime/build/flex/control/control" "$runtime/build/flex/control/trainer" "$runtime/build/flex/control/simulator" "$root/feedback-drop-tests-v1/validation.json" > "$root/neutral-drive-runtime-v1/inputs.sha256"
driver="$project/datasets/visual-control/expanded-rooms-v1/train-longer-neutral.sh"
export PUPPYBOT_PROJECT="$mock" PUPPYBOT_TEST_LONGER_BASELINE="$baseline" PUPPYBOT_LONGER_NEUTRAL_VERIFY_ZERO="$out/fake-zero" PUPPYBOT_LONGER_NEUTRAL_WAIT_RUN="$root/capacity/run"
PUPPYBOT_LONGER_NEUTRAL_OUT="$out/longer-trained" bash "$driver" > "$out/longer-trained.log" 2>&1
jq -e '.sameTrainingData and .sameValidationData and .initialActorParametersIdentical and .firstTrainingOrderIdentical and .firstOptimizerUpdateIdentical and .baselineOptimizerSteps==98 and .candidateOptimizerSteps==360 and .completeFittingPasses==3 and .driveFeedbackRowsStayedZero and (.automaticPromotion|not)' "$out/longer-trained/comparison.json" > /dev/null
for fault in PUPPYBOT_TEST_NONZERO PUPPYBOT_TEST_BAD_FIRST PUPPYBOT_TEST_BAD_TARGET PUPPYBOT_TEST_BAD_DROP;do
    if env "$fault=1" PUPPYBOT_LONGER_NEUTRAL_OUT="$out/$fault-longer" bash "$driver" > "$out/$fault-longer.log" 2>&1;then echo "$fault was accepted." >&2;exit 1;fi
    [[ "$(< "$out/$fault-longer/run.exit")" != 0 && ! -e "$out/$fault-longer/comparison.json" ]]
done
echo 'Longer neutral-drive training checks identical first update and complete fitting passes.'
