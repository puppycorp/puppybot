#!/usr/bin/env bash
# Synthetic scaled training checks added-sample exposure and target provenance.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]]
PUPPYBOT_PROJECT="$project" bash "$project/datasets/visual-control/expanded-rooms-v1/test-coverage-v2-student-training.sh" "$out" > /dev/null
mock="$out/mock";root="$mock/build/flex/sim/expanded-rooms-v1/large-model-v1";old="$root/coverage-v2-student-admission-v1";baseline="$root/coverage-v2-student-training-v1";admission="$root/coverage-scale-admission-v1";runtime="$root/phase-large-tests-v1/runtime"
mkdir -p "$baseline/policy" "$admission/expanded" "$admission/targets" "$admission/audit-fit" "$admission/audit-validation" "$root/capacity"
cp "$out/good/policy/initial.bin" "$baseline/policy/initial.bin";cp "$out/good/policy/first-order.bin" "$baseline/policy/first-order.bin";cp "$out/good/policy/curves.jsonl" "$baseline/policy/curves.jsonl"
old_target="$(sha256sum "$old/targets/targets.bin" | cut -d' ' -f1)";jq --arg target "$old_target" '.targetPositionTargetsSHA256=$target' "$out/good/policy/receipt.json" > "$baseline/policy/receipt.json"
cp -a "$out/good/screen" "$baseline/screen";printf '0\n' > "$baseline/run.exit";printf '0\n' > "$admission/run.exit";printf '0\n' > "$root/capacity/run.exit"
printf 'scaled data\n' > "$admission/expanded/data.bin";printf '{}\n' > "$admission/expanded/report.json";printf 'scaled targets\n' > "$admission/targets/targets.bin";printf '{}\n' > "$admission/targets/receipt.json";printf '{}\n' > "$admission/audit-fit/result.json";printf '{}\n' > "$admission/audit-validation/result.json"
old_sha="$(sha256sum "$old/expanded/data.bin" | cut -d' ' -f1)";data_sha="$(sha256sum "$admission/expanded/data.bin" | cut -d' ' -f1)"
jq -n --arg old "$old_sha" --arg data "$data_sha" '{passed:true,episodes:348,fittingHistories:237,validationHistories:111,addedTeacherHistories:32,dataSHA256:$data,oldDataSHA256:$old,teacherAssistedCompleted:8,existingDataBytePreserved:true,existingTargetsBytePreserved:true,newHistoriesIndependentlyAudited:true,teacherLabelsTrainingOnly:true,actorInputsUnchanged:true,automaticPromotion:false}' > "$admission/coverage.json"
cat > "$runtime/build/flex/control/control" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ "$1" == train ]];shift
while (( $# ));do case "$1" in --output) output="$2";shift 2;; --data) data="$2";shift 2;; --initial-policy) initial="$2";shift 2;; --target-heatmap) targets="$2";shift 2;; *) shift;; esac;done
mkdir "$output";cp "$initial/weights.bin" "$output/initial.bin"
data_sha="$(sha256sum "$data" | cut -d' ' -f1)";initial_sha="$(sha256sum "$initial/weights.bin" | cut -d' ' -f1)";target_sha="$(sha256sum "$targets/targets.bin" | cut -d' ' -f1)"
if [[ "${PUPPYBOT_TEST_WRONG_TARGET:-0}" == 1 ]];then target_sha=wrong;fi
jq -n --arg data "$data_sha" --arg initial "$initial_sha" --arg target "$target_sha" '{dataSHA256:$data,targetPositionTargetsSHA256:$target,initialWeightsSHA256:$initial,memoryWidth:256,epochs:1,batch:2,learningRateMicros:100,seed:202,maxOptimizerSteps:98,phaseGatedNavigation:true,sequenceMirrorAugmentation:true,heatmapActorGradientDetached:true,taskFeedback:false}' > "$output/receipt.json"
printf '{"epoch":1,"optimizerSteps":98}\n' > "$output/curves.jsonl"
if [[ "${PUPPYBOT_TEST_OMIT_NEW:-0}" == 1 ]];then perl -e 'print pack("Q<", $_) for 0..195' > "$output/first-order.bin";else perl -e 'print pack("Q<", $_) for 0..194,221' > "$output/first-order.bin";fi
EOF
chmod +x "$runtime/build/flex/control/control"
driver="$project/datasets/visual-control/expanded-rooms-v1/train-coverage-scale.sh"
export PUPPYBOT_PROJECT="$mock" PUPPYBOT_SCALE_TRAIN_WAIT_RUN="$root/capacity/run"
PUPPYBOT_SCALE_TRAIN_OUT="$out/scaled" bash "$driver" > "$out/scaled.log" 2>&1
jq -e '.initialWeightsIdentical and .differentTrainingData and .optimizerStepsPerModel==98 and .addedFittingHistoriesSeen==1 and .validationSetsDiffer and .shuffleAndCheckpointSelectionLimitCausalInterpretation and .baseline.episodes==4 and .candidate.episodes==4 and (.automaticPromotion|not)' "$out/scaled/comparison.json" > /dev/null
for fault in PUPPYBOT_TEST_OMIT_NEW PUPPYBOT_TEST_WRONG_TARGET;do
    if env "$fault=1" PUPPYBOT_SCALE_TRAIN_OUT="$out/$fault" bash "$driver" > "$out/$fault.log" 2>&1;then echo "$fault was accepted." >&2;exit 1;fi
    [[ "$(< "$out/$fault/run.exit")" != 0 && ! -e "$out/$fault/comparison.json" ]]
done
echo 'Scaled training checks new-history exposure and target provenance.'
