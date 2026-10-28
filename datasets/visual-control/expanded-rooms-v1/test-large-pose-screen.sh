#!/usr/bin/env bash
# Synthetic control-flow test; no GPU or simulator is used.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]]
mock="$out/mock";base="$mock/build/flex/sim/expanded-rooms-v1";root="$base/large-model-v1"
admission="$root/coverage-v2-student-admission-v1";baseline="$root/coverage-v2-student-training-v1";pose="$root/memory-pose-316-v2";seed="$root/phase-screen-v1/gated-initial";runtime="$root/large-pose-tests-v1/runtime";tests="$root/large-pose-tests-v1";screen="$root/source/phase-screen-v1";core="$root/large-pose-screen-source-v1"
mkdir -p "$admission/expanded" "$admission/targets" "$baseline/policy" "$baseline/screen" "$pose/targets" "$seed" "$runtime/build/flex/control" "$screen/fixture/data" "$core" "$base/unseen-benchmark-v2/native-path" "$root/contact-weight-screen-v1"
printf 'data\n' > "$admission/expanded/data.bin";printf 'target\n' > "$admission/targets/targets.bin";printf '{}\n' > "$admission/targets/receipt.json"
printf 'pose\n' > "$pose/targets/targets.bin";printf '{}\n' > "$pose/targets/sources.json";printf 'seed\n' > "$seed/weights.bin";printf '{}\n' > "$seed/receipt.json"
data_sha="$(sha256sum "$admission/expanded/data.bin" | cut -d' ' -f1)";target_sha="$(sha256sum "$admission/targets/targets.bin" | cut -d' ' -f1)";pose_sha="$(sha256sum "$pose/targets/targets.bin" | cut -d' ' -f1)"
jq -n --arg sha "$data_sha" '{passed:true,episodes:316,fittingHistories:221,validationHistories:95,dataSHA256:$sha,newHistoriesIndependentlyAudited:true,actorInputsUnchanged:true}' > "$admission/coverage.json"
jq -n --arg data "$data_sha" --arg pose "$pose_sha" '{passed:true,verifiedAgainstPhysicalTrace:true,preActionRGBAndFeedbackMatched:true,inverseTransformChecked:true,sourceFilesStableDuringVerification:true,actorInputsUnchanged:true,episodes:316,sourceDataSHA256:$data,targetsSHA256:$pose}' > "$pose/targets/receipt.json"
jq -n --arg data "$data_sha" --arg target "$target_sha" '{dataSHA256:$data,targetPositionTargetsSHA256:$target,memoryWidth:256,seed:202,batch:2,epochs:1,maxOptimizerSteps:98,phaseGatedNavigation:true,sequenceMirrorAugmentation:true,heatmapActorGradientDetached:true,memoryPoseAuxiliary:false,taskFeedback:false}' > "$baseline/policy/receipt.json"
cp "$seed/weights.bin" "$baseline/policy/initial.bin";printf 'baseline last\n' > "$baseline/policy/last.bin"
printf 'order\n' > "$baseline/policy/first-order.bin";printf 'mirror\n' > "$baseline/policy/first-mirror-mask.bin"
printf '{"exploratory":true,"episodes":4,"approaches":0,"returns":0,"rows":[]}\n' > "$baseline/screen/summary.json"
for index in 2 15 16 17;do case_seed=$((9960000+index));mkdir -p "$baseline/screen/$index/$case_seed/scene";for file in case.json environment.bin;do printf 'scene %s %s\n' "$index" "$file" > "$baseline/screen/$index/$case_seed/scene/$file";done;done
for d in "$admission" "$baseline" "$pose" "$root/contact-weight-screen-v1";do printf '0\n' > "$d/run.exit";done
printf '{"passed":true,"fullNetworkPoseGradientsChecked":true,"largeActorInitialTensorsPreserved":true,"onlyPoseHeadAdded":true,"exportedInferenceParity":true,"defaultTrainingBitIdentical":true,"incorrectCoreAndTraceRejected":true,"physicalPoseTargetsPilotChecked":true,"actorInputsUnchanged":true}\n' > "$tests/validation.json"
printf 'stable fixture\n' > "$tests/stable";sha256sum "$tests/stable" > "$tests/inputs.sha256"
printf 'fixture\n' > "$screen/fixture/data/data.bin";printf 'trainer\n' > "$runtime/build/flex/control/trainer"
cat > "$core/compare-pose-initial" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" == */last.bin ]];then echo 'original checkpoint tensor changed' >&2;exit 1;fi
if [[ "${PUPPYBOT_TEST_CHANGED_CORE:-0}" == 1 ]];then echo 'original checkpoint tensor changed' >&2;exit 1;fi
printf '{"passed":true,"allOriginalParametersByteIdentical":true,"addedPoseHeadOnly":true,"memoryWidth":256,"addedPoseParameters":1028}\n' > "$3"
EOF
cp "$core/compare-pose-initial" "$runtime/build/flex/control/compare-pose-initial";chmod +x "$core/compare-pose-initial" "$runtime/build/flex/control/compare-pose-initial"
cat > "$runtime/build/flex/control/control" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ "$1" == train ]];shift
while (( $# ));do case "$1" in --output) output="$2";shift 2;; --data) data="$2";shift 2;; --initial-policy) initial="$2";shift 2;; --target-heatmap) targets="$2";shift 2;; --memory-pose) pose="$2";shift 2;; *) shift;; esac;done
mkdir "$output";printf 'new pose initial\n' > "$output/initial.bin";printf 'new last\n' > "$output/last.bin";printf 'order\n' > "$output/first-order.bin";printf 'mirror\n' > "$output/first-mirror-mask.bin"
if [[ "${PUPPYBOT_TEST_DIFFERENT_ORDER:-0}" == 1 ]];then printf 'wrong order\n' > "$output/first-order.bin";fi
data_sha="$(sha256sum "$data" | cut -d' ' -f1)";target_sha="$(sha256sum "$targets/targets.bin" | cut -d' ' -f1)";pose_sha="$(sha256sum "$pose/targets.bin" | cut -d' ' -f1)";initial_sha="$(sha256sum "$initial/weights.bin" | cut -d' ' -f1)"
jq -n --arg data "$data_sha" --arg target "$target_sha" --arg pose "$pose_sha" --arg initial "$initial_sha" '{dataSHA256:$data,targetPositionTargetsSHA256:$target,memoryPoseTargetsSHA256:$pose,initialWeightsSHA256:$initial,memoryPoseAuxiliary:true,memoryWidth:256,phaseGatedNavigation:true,maxOptimizerSteps:98,taskFeedback:false}' > "$output/receipt.json"
printf '{"epoch":1,"optimizerSteps":98}\n' > "$output/curves.jsonl"
EOF
cat > "$runtime/build/flex/control/large-forward-tests" <<'EOF'
#!/usr/bin/env bash
mkdir "$3";printf '{"passed":true,"logitMaxAbsError":0,"memoryMaxAbsError":0,"resetBitIdentical":true}\n' > "$3/result.json"
EOF
chmod +x "$runtime/build/flex/control/control" "$runtime/build/flex/control/large-forward-tests"
cat > "$screen/screen-large-model.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
out="$PUPPYBOT_SCREEN_OUTPUT";mkdir "$out"
for index in 2 15 16 17;do case_seed=$((9960000+index));mkdir -p "$out/$index/$case_seed/scene";for file in case.json environment.bin;do printf 'scene %s %s\n' "$index" "$file" > "$out/$index/$case_seed/scene/$file";done;done
printf '{"exploratory":true,"episodes":4,"approaches":0,"returns":0,"rows":[]}\n' > "$out/summary.json"
EOF
driver="$project/datasets/visual-control/expanded-rooms-v1/train-large-pose-screen.sh"
PUPPYBOT_PROJECT="$mock" PUPPYBOT_LARGE_POSE_SCREEN_OUT="$out/good" bash "$driver" > "$out/good.log" 2>&1
jq -e '.sameTrainingData and .initialActorTensorsIdentical and .trainingOrdersIdentical and .firstMirrorMasksIdentical and .validationLossIncludesPoseAuxiliary and .checkpointSelectionMayDiffer and .baseline.episodes==4 and .candidate.episodes==4' "$out/good/comparison.json" > /dev/null
for fault in PUPPYBOT_TEST_DIFFERENT_ORDER PUPPYBOT_TEST_CHANGED_CORE;do
    if env "$fault=1" PUPPYBOT_PROJECT="$mock" PUPPYBOT_LARGE_POSE_SCREEN_OUT="$out/$fault" bash "$driver" > "$out/$fault.log" 2>&1;then echo "$fault was accepted." >&2;exit 1;fi
    [[ "$(< "$out/$fault/run.exit")" != 0 && ! -e "$out/$fault/comparison.json" ]]
done
echo 'Synthetic pose comparison rejects different initial core and sampling order.'
