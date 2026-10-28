#!/usr/bin/env bash
# Synthetic orchestration check; no simulator or neural training is run.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]]
mock="$out/mock";base="$mock/build/flex/sim/expanded-rooms-v1";root="$base/large-model-v1"
admission="$root/coverage-v2-student-admission-v1";baseline="$root/coverage-v2-student-training-v1";initial="$root/expanded-236-mirrored";runtime="$root/phase-large-tests-v1/runtime";screen="$root/source/phase-screen-v1"
mkdir -p "$admission/expanded" "$admission/targets" "$baseline/policy" "$baseline/screen" "$initial" "$runtime/build/flex/control" "$screen/fixture/data" "$base/unseen-benchmark-v2/native-path" "$root/capacity"
printf 'data\n' > "$admission/expanded/data.bin";printf 'targets\n' > "$admission/targets/targets.bin";printf '{}\n' > "$admission/targets/receipt.json";printf 'initial\n' > "$initial/weights.bin";printf '{}\n' > "$initial/receipt.json"
data_sha="$(sha256sum "$admission/expanded/data.bin" | cut -d' ' -f1)";target_sha="$(sha256sum "$admission/targets/targets.bin" | cut -d' ' -f1)";initial_sha="$(sha256sum "$initial/weights.bin" | cut -d' ' -f1)"
jq -n --arg sha "$data_sha" '{passed:true,episodes:316,fittingHistories:221,validationHistories:95,dataSHA256:$sha,newHistoriesIndependentlyAudited:true,teacherLabelsTrainingOnly:true,actorInputsUnchanged:true}' > "$admission/coverage.json"
jq -n --arg data "$data_sha" --arg target "$target_sha" --arg initial "$initial_sha" '{dataSHA256:$data,targetPositionTargetsSHA256:$target,initialWeightsSHA256:$initial,memoryWidth:256,seed:202,batch:2,epochs:1,learningRateMicros:100,maxOptimizerSteps:98,phaseGatedNavigation:true,sequenceMirrorAugmentation:true,heatmapActorGradientDetached:true,taskFeedback:false}' > "$baseline/policy/receipt.json"
for file in initial.bin first-order.bin first-mirror-mask.bin first-gradients.bin first-after.bin;do printf '%s\n' "$file" > "$baseline/policy/$file";done
printf '{"epoch":1,"optimizerSteps":98}\n' > "$baseline/policy/curves.jsonl"
printf '{"exploratory":true,"episodes":4,"approaches":0,"returns":0}\n' > "$baseline/screen/summary.json"
for index in 2 15 16 17;do seed=$((9960000+index));mkdir -p "$baseline/screen/$index/$seed/scene";for file in case.json environment.bin;do printf '%s %s\n' "$index" "$file" > "$baseline/screen/$index/$seed/scene/$file";done;done
for run in "$admission/run" "$baseline/run" "$root/capacity/run";do printf '0\n' > "$run.exit";done
printf 'fixture\n' > "$screen/fixture/data/data.bin";printf 'trainer\n' > "$runtime/build/flex/control/trainer"
cat > "$runtime/build/flex/control/control" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ "$1" == train ]];shift
while (( $# ));do case "$1" in --output) output="$2";shift 2;; --data) data="$2";shift 2;; --initial-policy) initial="$2";shift 2;; --target-heatmap) targets="$2";shift 2;; *) shift;; esac;done
mkdir "$output"
for file in initial.bin first-order.bin first-mirror-mask.bin first-gradients.bin first-after.bin;do printf '%s\n' "$file" > "$output/$file";done
if [[ "${PUPPYBOT_TEST_DIFFERENT_UPDATE:-0}" == 1 ]];then printf 'changed\n' > "$output/first-after.bin";fi
data_sha="$(sha256sum "$data" | cut -d' ' -f1)";target_sha="$(sha256sum "$targets/targets.bin" | cut -d' ' -f1)";initial_sha="$(sha256sum "$initial/weights.bin" | cut -d' ' -f1)"
jq -n --arg data "$data_sha" --arg target "$target_sha" --arg initial "$initial_sha" '{dataSHA256:$data,targetPositionTargetsSHA256:$target,initialWeightsSHA256:$initial,memoryWidth:256,seed:202,batch:2,epochs:10,learningRateMicros:100,maxOptimizerSteps:1110,phaseGatedNavigation:true,sequenceMirrorAugmentation:true,heatmapActorGradientDetached:true,taskFeedback:false}' > "$output/receipt.json"
for ((epoch=0;epoch<=10;epoch++));do jq -nc --argjson epoch "$epoch" '{epoch:$epoch,optimizerSteps:($epoch*111),selected:($epoch==0 or $epoch==2)}';done > "$output/curves.jsonl"
EOF
cat > "$runtime/build/flex/control/large-forward-tests" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
mkdir "$3";printf '{"passed":true,"logitMaxAbsError":0,"memoryMaxAbsError":0,"resetBitIdentical":true}\n' > "$3/result.json"
EOF
chmod +x "$runtime/build/flex/control/control" "$runtime/build/flex/control/large-forward-tests"
cat > "$screen/screen-large-model.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
out="$PUPPYBOT_SCREEN_OUTPUT";mkdir "$out"
for index in 2 15 16 17;do seed=$((9960000+index));mkdir -p "$out/$index/$seed/scene";for file in case.json environment.bin;do printf '%s %s\n' "$index" "$file" > "$out/$index/$seed/scene/$file";done;done
printf '{"exploratory":true,"episodes":4,"approaches":1,"returns":0}\n' > "$out/summary.json"
EOF
driver="$project/datasets/visual-control/expanded-rooms-v1/train-longer-316.sh"
PUPPYBOT_PROJECT="$mock" PUPPYBOT_LONGER_316_WAIT_RUN="$root/capacity/run" PUPPYBOT_LONGER_316_OUT="$out/good" bash "$driver" > "$out/good.log" 2>&1
jq -e '.sameTrainingData and .firstOptimizerUpdateIdentical and .baselineOptimizerSteps==98 and .candidateOptimizerSteps==1110 and .validationSelectedEpoch==2 and .baseline.approaches==0 and .candidate.approaches==1 and (.automaticPromotion|not)' "$out/good/comparison.json" > /dev/null
if PUPPYBOT_PROJECT="$mock" PUPPYBOT_TEST_DIFFERENT_UPDATE=1 PUPPYBOT_LONGER_316_WAIT_RUN="$root/capacity/run" PUPPYBOT_LONGER_316_OUT="$out/bad" bash "$driver" > "$out/bad.log" 2>&1;then echo 'Different first optimizer update was accepted.' >&2;exit 1;fi
[[ "$(< "$out/bad/run.exit")" != 0 && ! -e "$out/bad/comparison.json" ]]
echo 'Longer training comparison rejects an unmatched first optimizer update.'
