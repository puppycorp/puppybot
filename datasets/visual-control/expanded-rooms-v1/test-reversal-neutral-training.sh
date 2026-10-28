#!/usr/bin/env bash
# The reversal comparison must keep the dataset, masks and actor inputs fixed.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]]
PUPPYBOT_PROJECT="$project" bash "$project/datasets/visual-control/expanded-rooms-v1/test-forward-return-training.sh" "$out" > /dev/null
mock="$out/mock";root="$mock/build/flex/sim/expanded-rooms-v1/large-model-v1";baseline="$root/forward-return-training-v1/candidate";runtime="$root/neutral-drive-runtime-v1/runtime"
ln -s "$out/forward-trained" "$root/forward-return-training-v1"
for file in first-mirror-mask.bin first-feedback-drop-mask.bin first-gradients.bin;do printf '%s\n' "$file" > "$baseline/policy/$file";done
mkdir "$out/combined"
cat > "$runtime/build/flex/control/control" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ "$1" == train ]];shift;drop='';seed='';penalty=''
while (( $# ));do case "$1" in --output) output="$2";shift 2;; --data) data="$2";shift 2;; --initial-policy) initial="$2";shift 2;; --target-heatmap) targets="$2";shift 2;; --drop-drive-feedback-milli) drop="$2";shift 2;; --reversal-penalty-milli) penalty="$2";shift 2;; --seed) seed="$2";shift 2;; *) shift;; esac;done
[[ "$drop" == 1000 && "$seed" == 203 && "$penalty" == 1000 ]];mkdir "$output"
for file in initial.bin first-order.bin first-mirror-mask.bin first-feedback-drop-mask.bin;do cp "$PUPPYBOT_TEST_REVERSAL_BASELINE/policy/$file" "$output/$file";done
cp "$initial/weights.bin" "$output/first-after.bin";cp "$initial/weights.bin" "$output/weights.bin";printf 'changed gradient\n' > "$output/first-gradients.bin"
if [[ "${PUPPYBOT_TEST_BAD_ORDER:-0}" == 1 ]];then printf 'different\n' > "$output/first-order.bin";fi
data_sha="$(sha256sum "$data" | cut -d' ' -f1)";initial_sha="$(sha256sum "$initial/weights.bin" | cut -d' ' -f1)";target_sha="$(sha256sum "$targets/targets.bin" | cut -d' ' -f1)";if [[ "${PUPPYBOT_TEST_BAD_TARGET:-0}" == 1 ]];then target_sha=wrong;fi
if [[ "${PUPPYBOT_TEST_BAD_PENALTY:-0}" == 1 ]];then penalty=0;fi
jq -n --arg data "$data_sha" --arg initial "$initial_sha" --arg target "$target_sha" --argjson penalty "$penalty" '{dataSHA256:$data,targetPositionTargetsSHA256:$target,initialWeightsSHA256:$initial,memoryWidth:256,epochs:1,batch:2,learningRateMicros:100,seed:203,maxOptimizerSteps:98,phaseGatedNavigation:true,sequenceMirrorAugmentation:true,heatmapActorGradientDetached:true,driveFeedbackDropMilli:1000,reversalPenaltyMilli:$penalty,memoryPoseAuxiliary:false,taskFeedback:false}' > "$output/receipt.json"
jq -n '{epoch:1,optimizerSteps:98,driveFeedbackDroppedSequences:196,selected:true}' > "$output/curves.jsonl"
EOF
chmod +x "$runtime/build/flex/control/control"
sha256sum "$runtime/build/flex/control/control" "$runtime/build/flex/control/trainer" "$runtime/build/flex/control/simulator" "$root/feedback-drop-tests-v1/validation.json" > "$root/neutral-drive-runtime-v1/inputs.sha256"
control_sha="$(sha256sum "$runtime/build/flex/control/control" | cut -d' ' -f1)";trainer_sha="$(sha256sum "$runtime/build/flex/control/trainer" | cut -d' ' -f1)"
jq -n --arg control "$control_sha" --arg trainer "$trainer_sha" '{passed:true,controlSHA256:$control,trainerSHA256:$trainer,sameInitialWeightsAndOrder:true,feedbackMaskedInTraining:true,validationUnmasked:true,reversalChangesGradients:true,deterministicRepeat:true,inferenceParity:true,trainingOnlyLoss:true}' > "$out/combined/summary.json"
driver="$project/datasets/visual-control/expanded-rooms-v1/train-reversal-neutral.sh"
export PUPPYBOT_PROJECT="$mock" PUPPYBOT_TEST_REVERSAL_BASELINE="$baseline" PUPPYBOT_REVERSAL_NEUTRAL_VERIFY_ZERO="$out/fake-zero" PUPPYBOT_REVERSAL_NEUTRAL_COMBINED_TEST="$out/combined" PUPPYBOT_REVERSAL_NEUTRAL_WAIT_RUN="$root/capacity/run"
PUPPYBOT_REVERSAL_NEUTRAL_OUT="$out/reversal-trained" bash "$driver" > "$out/reversal-trained.log" 2>&1
jq -e '.sameTrainingData and .sameValidationData and .initialActorParametersIdentical and .firstTrainingOrderIdentical and .firstMirrorAndFeedbackMasksIdentical and .optimizerStepsPerModel==98 and .reversalPenaltyMilli==1000 and .firstGradientChanged and .reversalLossTrainingOnly and .validationObjectiveUnchanged and .driveFeedbackRowsStayedZero and (.automaticPromotion|not)' "$out/reversal-trained/comparison.json" > /dev/null
for fault in PUPPYBOT_TEST_NONZERO PUPPYBOT_TEST_BAD_ORDER PUPPYBOT_TEST_BAD_TARGET PUPPYBOT_TEST_BAD_PENALTY;do
    if env "$fault=1" PUPPYBOT_REVERSAL_NEUTRAL_OUT="$out/$fault-reversal" bash "$driver" > "$out/$fault-reversal.log" 2>&1;then echo "$fault was accepted." >&2;exit 1;fi
    [[ "$(< "$out/$fault-reversal/run.exit")" != 0 && ! -e "$out/$fault-reversal/comparison.json" ]]
done
jq '.reversalChangesGradients=false' "$out/combined/summary.json" > "$out/bad-combined.json";cp "$out/bad-combined.json" "$out/combined/summary.json"
if PUPPYBOT_REVERSAL_NEUTRAL_OUT="$out/bad-combined" bash "$driver" > "$out/bad-combined.log" 2>&1;then echo 'Unverified combined loss was accepted.' >&2;exit 1;fi
[[ "$(< "$out/bad-combined/run.exit")" != 0 && ! -e "$out/bad-combined/comparison.json" ]]
jq '.reversalChangesGradients=true | .trainerSHA256="wrong"' "$out/combined/summary.json" > "$out/bad-runtime.json";cp "$out/bad-runtime.json" "$out/combined/summary.json"
if PUPPYBOT_REVERSAL_NEUTRAL_OUT="$out/bad-runtime" bash "$driver" > "$out/bad-runtime.log" 2>&1;then echo 'Combined test from a different trainer was accepted.' >&2;exit 1;fi
[[ "$(< "$out/bad-runtime/run.exit")" != 0 && ! -e "$out/bad-runtime/comparison.json" ]]
echo 'Reversal training checks unchanged data, masks and training-only penalty.'
