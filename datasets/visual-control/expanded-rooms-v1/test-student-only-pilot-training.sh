#!/usr/bin/env bash
# Synthetic orchestration test. No simulator or neural training is performed.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(/usr/bin/realpath -m "${1:?New output directory required}")"
[[ ! -e "$out" ]]
mock="$out/mock";base="$mock/build/flex/sim/expanded-rooms-v1";root="$base/large-model-v1"
old="$root/gated-search-cohort-admission-v2";admission="$root/student-only-admission-v1";pair="$root/gated-search-cohort-training-v2";runtime="$root/phase-large-tests-v1/runtime";source="$root/source/phase-screen-v1"
mkdir -p "$old/expanded" "$admission/expanded" "$admission/targets" "$admission/audit-fit" "$admission/audit-validation" "$pair/policy" "$pair/screen" "$root/expanded-236-mirrored" "$runtime/build/flex/control" "$source/fixture/data" "$base/unseen-benchmark-v2/native-path"
printf '{}\n' > "$admission/audit-fit/result.json";printf '{}\n' > "$admission/audit-validation/result.json"
printf 'baseline data\n' > "$old/expanded/data.bin";printf 'expanded data\n' > "$admission/expanded/data.bin"
printf 'targets\n' > "$admission/targets/targets.bin";printf '{}\n' > "$admission/targets/receipt.json"
printf 'initial weights\n' > "$root/expanded-236-mirrored/weights.bin";printf '{}\n' > "$root/expanded-236-mirrored/receipt.json"
cp "$root/expanded-236-mirrored/weights.bin" "$pair/policy/initial.bin"
printf 'baseline policy\n' > "$pair/policy/weights.bin"
old_sha="$(/usr/bin/sha256sum "$old/expanded/data.bin" | /usr/bin/cut -d' ' -f1)"
new_sha="$(/usr/bin/sha256sum "$admission/expanded/data.bin" | /usr/bin/cut -d' ' -f1)"
initial_sha="$(/usr/bin/sha256sum "$root/expanded-236-mirrored/weights.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -n --arg old "$old_sha" --arg sha "$new_sha" '{passed:true,episodes:292,fittingHistories:209,validationHistories:83,addedStudentOnlyHistories:2,studentRollinActionsReplayed:600,incompleteAddedEpisodes:2,oldDataSHA256:$old,dataSHA256:$sha,existingDataBytePreserved:true,existingTargetsBytePreserved:true,newHistoriesIndependentlyAudited:true,teacherLabelsTrainingOnly:true,actorInputsUnchanged:true,incompleteEpisodesClaimedSuccessful:false}' > "$admission/coverage.json"
/usr/bin/jq -n --arg data "$old_sha" --arg initial "$initial_sha" '{dataSHA256:$data,initialWeightsSHA256:$initial,memoryWidth:256,epochs:1,batch:2,learningRateMicros:100,seed:197,maxOptimizerSteps:98,phaseGatedNavigation:true,taskFeedback:false}' > "$pair/policy/receipt.json"
printf '{"epoch":1,"optimizerSteps":98}\n' > "$pair/policy/curves.jsonl"
printf '{"exploratory":true,"episodes":4,"approaches":0,"returns":0,"rows":[]}\n' > "$pair/screen/summary.json"
printf '{"synthetic":true}\n' > "$pair/comparison.json"
/usr/bin/jq -n '[range(0;196)]' > "$pair/training-indices.json"
for index in 2 15 16 17;do seed=$((9960000+index));mkdir -p "$pair/screen/$index/$seed/scene";for file in case.json environment.bin;do printf 'scene %s %s\n' "$index" "$file" > "$pair/screen/$index/$seed/scene/$file";done;done
printf '0\n' > "$admission/run.exit";printf '0\n' > "$pair/run.exit"
for job in return-cohort-equal-training-v1 return-cohort-second-training-v1 return-cohort-reversal-training-v1 phase-cohort-training-v1 phase-consistency-screen-v1;do mkdir "$root/$job";printf '0\n' > "$root/$job/run.exit";done
printf 'fixture\n' > "$source/fixture/data/data.bin"
cat > "$runtime/build/flex/control/control" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ "$1" == train ]];shift
while (( $# ));do case "$1" in --output) output="$2";shift 2;; --data) data="$2";shift 2;; --initial-policy) initial="$2";shift 2;; *) shift;; esac;done
mkdir "$output";cp "$initial/weights.bin" "$output/seed.bin";cp "$initial/weights.bin" "$output/initial.bin"
data_sha="$(/usr/bin/sha256sum "$data" | /usr/bin/cut -d' ' -f1)";initial_sha="$(/usr/bin/sha256sum "$initial/weights.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -n --arg data "$data_sha" --arg initial "$initial_sha" '{dataSHA256:$data,initialWeightsSHA256:$initial,memoryWidth:256,epochs:1,batch:2,learningRateMicros:100,seed:197,maxOptimizerSteps:98,phaseGatedNavigation:true,sequenceMirrorAugmentation:true,heatmapActorFeatures:true,heatmapActorGradientDetached:true,taskFeedback:false}' > "$output/receipt.json"
printf '{"epoch":1,"optimizerSteps":98}\n' > "$output/curves.jsonl"
if [[ "${PUPPYBOT_TEST_OMIT_NEW:-0}" == 1 ]];then /usr/bin/perl -e 'print pack("Q<", $_) for 0..195' > "$output/first-order.bin";else /usr/bin/perl -e 'print pack("Q<", $_) for 0..194,208' > "$output/first-order.bin";fi
printf 'candidate weights\n' > "$output/weights.bin";printf 'candidate binary\n' > "$output/policy"
EOF
cat > "$runtime/build/flex/control/large-forward-tests" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
mkdir "$3";printf '{"passed":true,"logitMaxAbsError":0,"memoryMaxAbsError":0,"resetBitIdentical":true}\n' > "$3/result.json"
EOF
printf 'synthetic trainer\n' > "$runtime/build/flex/control/trainer"
chmod +x "$runtime/build/flex/control/control" "$runtime/build/flex/control/large-forward-tests"
cat > "$source/screen-large-model.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
out="$PUPPYBOT_SCREEN_OUTPUT";mkdir "$out"
for index in 2 15 16 17;do seed=$((9960000+index));mkdir -p "$out/$index/$seed/scene";for file in case.json environment.bin;do printf 'scene %s %s\n' "$index" "$file" > "$out/$index/$seed/scene/$file";done;done
printf '{"exploratory":true,"episodes":4,"approaches":0,"returns":0,"rows":[]}\n' > "$out/summary.json"
EOF
driver="$project/datasets/visual-control/expanded-rooms-v1/train-student-only-pilot.sh"
mkdir "$out/extra-capacity-job";printf '0\n' > "$out/extra-capacity-job/run.exit"
PUPPYBOT_PROJECT="$mock" PUPPYBOT_EXTRA_TRAINING_WAIT_RUN="$out/extra-capacity-job/run" PUPPYBOT_STUDENT_ONLY_TRAINING_OUT="$out/good" /usr/bin/bash "$driver" > "$out/good.log" 2>&1
/usr/bin/jq -e '.additionalFittingHistorySeen and .initialWeightsIdentical and .baseline.episodes==4 and .augmented.episodes==4' "$out/good/comparison.json" > /dev/null
[[ "$(< "$out/good/comparison-pair/run.exit")" == 0 ]]
if PUPPYBOT_PROJECT="$mock" PUPPYBOT_TEST_OMIT_NEW=1 PUPPYBOT_STUDENT_ONLY_TRAINING_OUT="$out/bad" /usr/bin/bash "$driver" > "$out/bad.log" 2>&1;then echo 'Training that missed the added fitting history was accepted.' >&2;exit 1;fi
[[ "$(< "$out/bad/run.exit")" == 1 && ! -e "$out/bad/comparison-pair/run.exit" ]]
echo 'Synthetic cohort training checks added-sample exposure and matched comparison wiring.'
