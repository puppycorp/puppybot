#!/usr/bin/env bash
# Synthetic orchestration test; no neural training or simulator is run.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(/usr/bin/realpath -m "${1:?New output directory required}")"
[[ ! -e "$out" ]]
mock="$out/mock";base="$mock/build/flex/sim/expanded-rooms-v1";root="$base/large-model-v1"
admission="$root/student-only-admission-v1";baseline="$root/student-only-training-v1";runtime="$root/feedback-drop-tests-v1/runtime";source="$root/source/phase-screen-v1";tests="$root/feedback-drop-tests-v1"
mkdir -p "$admission/expanded" "$admission/targets" "$baseline/policy" "$baseline/screen" "$root/expanded-236-mirrored" "$runtime/build/flex/control" "$source/fixture/data" "$tests" "$base/unseen-benchmark-v2/native-path"
mkdir "$root/feedback-drop-gradient-result-v2"
printf '{"passed":true,"feedbackDropChecked":true,"fullCNNAndGRU":true,"tensorsChecked":24,"maxGradientAbsError":0,"maxAdamAbsError":0}\n' > "$root/feedback-drop-gradient-result-v2/result.json"
printf 'data\n' > "$admission/expanded/data.bin";printf 'target\n' > "$admission/targets/targets.bin";printf '{}\n' > "$admission/targets/receipt.json";printf 'initial\n' > "$root/expanded-236-mirrored/weights.bin"
data_sha="$(/usr/bin/sha256sum "$admission/expanded/data.bin" | /usr/bin/cut -d' ' -f1)";target_sha="$(/usr/bin/sha256sum "$admission/targets/targets.bin" | /usr/bin/cut -d' ' -f1)";initial_sha="$(/usr/bin/sha256sum "$root/expanded-236-mirrored/weights.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -n --arg sha "$data_sha" '{passed:true,episodes:292,dataSHA256:$sha,newHistoriesIndependentlyAudited:true,teacherLabelsTrainingOnly:true,actorInputsUnchanged:true}' > "$admission/coverage.json"
/usr/bin/jq -n --arg data "$data_sha" --arg target "$target_sha" --arg initial "$initial_sha" '{dataSHA256:$data,targetPositionTargetsSHA256:$target,initialWeightsSHA256:$initial,memoryWidth:256,epochs:1,batch:2,learningRateMicros:100,seed:197,maxOptimizerSteps:98,phaseGatedNavigation:true,sequenceMirrorAugmentation:true,heatmapActorGradientDetached:true,taskFeedback:false}' > "$baseline/policy/receipt.json"
cp "$root/expanded-236-mirrored/weights.bin" "$baseline/policy/initial.bin"
printf 'order\n' > "$baseline/policy/first-order.bin";printf 'mirror\n' > "$baseline/policy/first-mirror-mask.bin";printf 'baseline gradient\n' > "$baseline/policy/first-gradients.bin"
printf '{"exploratory":true,"episodes":4,"approaches":0,"returns":0,"rows":[]}\n' > "$baseline/screen/summary.json"
for index in 2 15 16 17;do seed=$((9960000+index));mkdir -p "$baseline/screen/$index/$seed/scene";for file in case.json environment.bin;do printf 'scene %s %s\n' "$index" "$file" > "$baseline/screen/$index/$seed/scene/$file";done;done
printf '0\n' > "$admission/run.exit";printf '0\n' > "$baseline/run.exit"
for job in contact-weight-screen-v1;do mkdir "$root/$job";printf '0\n' > "$root/$job/run.exit";done
printf '{"passed":true,"numericGradientAndMaskTests":true,"gpuDeterministic":true,"feedbackDropChangesGradient":true,"defaultBitIdenticalToPreviousRuntime":true,"validationUnmasked":true,"firstOrderAndMirrorMaskIdentical":true,"inferenceParity":true,"invalidRateRejected":true,"actorInterfaceUnchanged":true}\n' > "$tests/validation.json"
printf 'fixture\n' > "$source/fixture/data/data.bin";printf 'synthetic trainer\n' > "$runtime/build/flex/control/trainer"
printf 'stable\n' > "$tests/stable";sha256sum "$tests/stable" > "$tests/inputs.sha256"
printf 'baseline last\n' > "$baseline/policy/last.bin"
cat > "$runtime/build/flex/control/control" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ "$1" == train ]];shift
while (( $# ));do case "$1" in --output) output="$2";shift 2;; --data) data="$2";shift 2;; --initial-policy) initial="$2";shift 2;; --target-heatmap) targets="$2";shift 2;; *) shift;; esac;done
mkdir "$output";cp "$initial/weights.bin" "$output/initial.bin";printf 'order\n' > "$output/first-order.bin";printf 'mirror\n' > "$output/first-mirror-mask.bin";printf 'changed gradient\n' > "$output/first-gradients.bin"
if [[ "${PUPPYBOT_TEST_DIFFERENT_ORDER:-0}" == 1 ]];then printf 'different\n' > "$output/first-order.bin";fi
data_sha="$(/usr/bin/sha256sum "$data" | /usr/bin/cut -d' ' -f1)";target_sha="$(/usr/bin/sha256sum "$targets/targets.bin" | /usr/bin/cut -d' ' -f1)";initial_sha="$(/usr/bin/sha256sum "$initial/weights.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -n --arg data "$data_sha" --arg target "$target_sha" --arg initial "$initial_sha" '{dataSHA256:$data,targetPositionTargetsSHA256:$target,initialWeightsSHA256:$initial,driveFeedbackDropMilli:250,driveFeedbackDropTrainingOnly:true,phaseGatedNavigation:true,memoryWidth:256,maxOptimizerSteps:98,taskFeedback:false}' > "$output/receipt.json"
dropped=3;if [[ "${PUPPYBOT_TEST_NO_DROPS:-0}" == 1 ]];then dropped=0;fi
jq -n --argjson dropped "$dropped" '{epoch:1,optimizerSteps:98,driveFeedbackDroppedSequences:$dropped}' > "$output/curves.jsonl"
mask=0;if [[ "${PUPPYBOT_TEST_VALIDATION_MASKED:-0}" == 1 ]];then mask=1;fi
printf 'candidate last\n' > "$output/last.bin";perl -e 'print pack("Q<", $ARGV[0])' "$mask" > "$output/last-validation-feedback-drop-mask.bin"
EOF
cat > "$runtime/build/flex/control/large-forward-tests" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
mkdir "$3";printf '{"passed":true,"logitMaxAbsError":0,"memoryMaxAbsError":0,"resetBitIdentical":true}\n' > "$3/result.json"
EOF
chmod +x "$runtime/build/flex/control/control" "$runtime/build/flex/control/large-forward-tests"
cat > "$source/screen-large-model.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
out="$PUPPYBOT_SCREEN_OUTPUT";mkdir "$out"
for index in 2 15 16 17;do seed=$((9960000+index));mkdir -p "$out/$index/$seed/scene";for file in case.json environment.bin;do printf 'scene %s %s\n' "$index" "$file" > "$out/$index/$seed/scene/$file";done;done
printf '{"exploratory":true,"episodes":4,"approaches":0,"returns":0,"rows":[]}\n' > "$out/summary.json"
EOF
driver="$project/datasets/visual-control/expanded-rooms-v1/train-feedback-drop-screen.sh"
PUPPYBOT_PROJECT="$mock" PUPPYBOT_FEEDBACK_DROP_SCREEN_OUT="$out/good" /usr/bin/bash "$driver" > "$out/good.log" 2>&1
/usr/bin/jq -e '.sameTrainingData and .initialWeightsIdentical and .trainingOrdersIdentical and .firstMirrorMasksIdentical and .baseline.episodes==4 and .candidate.episodes==4' "$out/good/comparison.json" > /dev/null
if PUPPYBOT_PROJECT="$mock" PUPPYBOT_TEST_DIFFERENT_ORDER=1 PUPPYBOT_FEEDBACK_DROP_SCREEN_OUT="$out/bad" /usr/bin/bash "$driver" > "$out/bad.log" 2>&1;then echo 'Different training order was accepted.' >&2;exit 1;fi
[[ "$(< "$out/bad/run.exit")" == 1 && ! -e "$out/bad/comparison.json" ]]
for fault in PUPPYBOT_TEST_NO_DROPS PUPPYBOT_TEST_VALIDATION_MASKED;do
    if env "$fault=1" PUPPYBOT_PROJECT="$mock" PUPPYBOT_FEEDBACK_DROP_SCREEN_OUT="$out/$fault" /usr/bin/bash "$driver" > "$out/$fault.log" 2>&1;then echo "$fault was accepted." >&2;exit 1;fi
    [[ "$(< "$out/$fault/run.exit")" != 0 && ! -e "$out/$fault/comparison.json" ]]
done
echo 'Synthetic feedback-drop screen rejects mismatched training order.'
