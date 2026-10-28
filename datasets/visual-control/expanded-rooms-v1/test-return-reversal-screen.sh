#!/usr/bin/env bash
# Synthetic orchestration test; no neural training or simulator is run.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(/usr/bin/realpath -m "${1:?New output directory required}")"
[[ ! -e "$out" ]]
mock="$out/mock";base="$mock/build/flex/sim/expanded-rooms-v1";root="$base/large-model-v1"
admission="$root/coverage-return-admission-v1";baseline="$root/coverage-return-pair-v1";runtime="$root/phase-large-tests-v1/runtime";source="$root/source/phase-screen-v1"
mkdir -p "$admission/expanded" "$admission/targets" "$baseline/augmented-policy" "$baseline/augmented-screen" "$root/expanded-236-mirrored" "$runtime/build/flex/control" "$source/fixture/data" "$base/unseen-benchmark-v2/native-path"
printf 'data\n' > "$admission/expanded/data.bin";printf 'target\n' > "$admission/targets/targets.bin";printf '{}\n' > "$admission/targets/receipt.json";printf 'initial\n' > "$root/expanded-236-mirrored/weights.bin"
data_sha="$(/usr/bin/sha256sum "$admission/expanded/data.bin" | /usr/bin/cut -d' ' -f1)";target_sha="$(/usr/bin/sha256sum "$admission/targets/targets.bin" | /usr/bin/cut -d' ' -f1)";initial_sha="$(/usr/bin/sha256sum "$root/expanded-236-mirrored/weights.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -n --arg sha "$data_sha" '{passed:true,episodes:310,dataSHA256:$sha,newHistoriesIndependentlyAudited:true,teacherLabelsTrainingOnly:true,actorInputsUnchanged:true}' > "$admission/coverage.json"
/usr/bin/jq -n --arg data "$data_sha" --arg target "$target_sha" --arg initial "$initial_sha" '{dataSHA256:$data,targetPositionTargetsSHA256:$target,initialWeightsSHA256:$initial,memoryWidth:256,epochs:1,batch:2,learningRateMicros:100,seed:202,maxOptimizerSteps:109,phaseGatedNavigation:true,sequenceMirrorAugmentation:true,heatmapActorGradientDetached:true,taskFeedback:false}' > "$baseline/augmented-policy/receipt.json"
cp "$root/expanded-236-mirrored/weights.bin" "$baseline/augmented-policy/initial.bin"
printf 'order\n' > "$baseline/augmented-policy/first-order.bin";printf 'mirror\n' > "$baseline/augmented-policy/first-mirror-mask.bin";printf 'baseline gradient\n' > "$baseline/augmented-policy/first-gradients.bin"
printf '{"exploratory":true,"episodes":4,"approaches":0,"returns":0,"rows":[]}\n' > "$baseline/augmented-screen/summary.json"
for index in 2 15 16 17;do seed=$((9960000+index));mkdir -p "$baseline/augmented-screen/$index/$seed/scene";for file in case.json environment.bin;do printf 'scene %s %s\n' "$index" "$file" > "$baseline/augmented-screen/$index/$seed/scene/$file";done;done
printf '0\n' > "$admission/run.exit";printf '0\n' > "$baseline/run.exit"
printf 'fixture\n' > "$source/fixture/data/data.bin";printf 'synthetic trainer\n' > "$runtime/build/flex/control/trainer"
cat > "$runtime/build/flex/control/control" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ "$1" == train ]];shift
while (( $# ));do case "$1" in --output) output="$2";shift 2;; --data) data="$2";shift 2;; --initial-policy) initial="$2";shift 2;; --target-heatmap) targets="$2";shift 2;; *) shift;; esac;done
mkdir "$output";cp "$initial/weights.bin" "$output/initial.bin";printf 'order\n' > "$output/first-order.bin";printf 'mirror\n' > "$output/first-mirror-mask.bin";printf 'changed gradient\n' > "$output/first-gradients.bin"
if [[ "${PUPPYBOT_TEST_DIFFERENT_ORDER:-0}" == 1 ]];then printf 'different\n' > "$output/first-order.bin";fi
data_sha="$(/usr/bin/sha256sum "$data" | /usr/bin/cut -d' ' -f1)";target_sha="$(/usr/bin/sha256sum "$targets/targets.bin" | /usr/bin/cut -d' ' -f1)";initial_sha="$(/usr/bin/sha256sum "$initial/weights.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -n --arg data "$data_sha" --arg target "$target_sha" --arg initial "$initial_sha" '{dataSHA256:$data,targetPositionTargetsSHA256:$target,initialWeightsSHA256:$initial,reversalPenaltyMilli:1000,phaseGatedNavigation:true,memoryWidth:256,maxOptimizerSteps:109,taskFeedback:false}' > "$output/receipt.json"
printf '{"epoch":1,"optimizerSteps":109}\n' > "$output/curves.jsonl"
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
driver="$project/datasets/visual-control/expanded-rooms-v1/train-return-reversal-screen.sh"
PUPPYBOT_PROJECT="$mock" PUPPYBOT_RETURN_REVERSAL_SCREEN_OUT="$out/good" /usr/bin/bash "$driver" > "$out/good.log" 2>&1
/usr/bin/jq -e '.sameTrainingData and .initialWeightsIdentical and .trainingOrdersIdentical and .mirrorMasksIdentical and .baseline.episodes==4 and .candidate.episodes==4' "$out/good/comparison.json" > /dev/null
if PUPPYBOT_PROJECT="$mock" PUPPYBOT_TEST_DIFFERENT_ORDER=1 PUPPYBOT_RETURN_REVERSAL_SCREEN_OUT="$out/bad" /usr/bin/bash "$driver" > "$out/bad.log" 2>&1;then echo 'Different training order was accepted.' >&2;exit 1;fi
[[ "$(< "$out/bad/run.exit")" == 1 && ! -e "$out/bad/comparison.json" ]]
echo 'Synthetic reversal screen rejects mismatched training order.'
