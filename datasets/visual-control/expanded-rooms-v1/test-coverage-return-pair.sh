#!/usr/bin/env bash
# Synthetic orchestration test for return-data training; no neural training is performed.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")"
[[ ! -e "$out" ]];mock="$out/mock";base="$mock/build/flex/sim/expanded-rooms-v1";root="$base/large-model-v1"
old="$root/coverage-v2-teacher-admission-v1";new="$root/coverage-return-admission-v1";initial="$root/expanded-236-mirrored";runtime="$root/phase-large-tests-v1/runtime";source="$root/source/phase-screen-v1"
mkdir -p "$old/expanded" "$old/targets" "$new/expanded" "$new/targets" "$initial" "$root/phase-screen-v1/gated-initial" "$root/return-weight-screen-v1" "$runtime/build/flex/control" "$source/fixture/data" "$base/unseen-benchmark-v2/native-path"
printf 'old data\n' > "$old/expanded/data.bin";printf 'new data\n' > "$new/expanded/data.bin"
for d in "$old" "$new";do printf 'targets\n' > "$d/targets/targets.bin";printf '{}\n' > "$d/targets/receipt.json";printf '0\n' > "$d/run.exit";done
printf 'seed\n' > "$initial/weights.bin";printf '{}\n' > "$initial/receipt.json";cp "$initial/weights.bin" "$root/phase-screen-v1/gated-initial/weights.bin"
printf '0\n' > "$root/return-weight-screen-v1/run.exit";printf 'fixture\n' > "$source/fixture/data/data.bin"
old_sha="$(sha256sum "$old/expanded/data.bin" | cut -d' ' -f1)";new_sha="$(sha256sum "$new/expanded/data.bin" | cut -d' ' -f1)"
jq -n --arg sha "$old_sha" '{passed:true,episodes:308,fittingHistories:217,dataSHA256:$sha,newHistoriesIndependentlyAudited:true,actorInputsUnchanged:true}' > "$old/coverage.json"
count="${PUPPYBOT_TEST_RETURN_PAIRS:-1}";[[ "$count" == 1 || "$count" == 2 ]]
jq -n --arg old "$old_sha" --arg sha "$new_sha" --argjson count "$count" '{passed:true,episodes:(308+2*$count),fittingHistories:(217+$count),validationHistories:(91+$count),oldDataSHA256:$old,dataSHA256:$sha,addedReturnHistories:(2*$count),studentReturnActionsReplayed:120,newHistoriesIndependentlyAudited:true,teacherSearchGoalsReconstructed:true,teacherLabelsTrainingOnly:true,teacherAssisted:true,actorInputsUnchanged:true,autonomousWholeEpisodeSuccessClaimed:false}' > "$new/coverage.json"
cat > "$runtime/build/flex/control/control" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ "$1" == train ]];shift
while (( $# ));do case "$1" in --output) output="$2";shift 2;; --data) data="$2";shift 2;; --initial-policy) initial="$2";shift 2;; *) shift;; esac;done
mkdir "$output";cp "$initial/weights.bin" "$output/seed.bin";cp "$initial/weights.bin" "$output/initial.bin"
data_sha="$(sha256sum "$data" | cut -d' ' -f1)";initial_sha="$(sha256sum "$initial/weights.bin" | cut -d' ' -f1)"
jq -n --arg data "$data_sha" --arg initial "$initial_sha" '{dataSHA256:$data,initialWeightsSHA256:$initial,memoryWidth:256,epochs:1,batch:2,learningRateMicros:100,seed:202,maxOptimizerSteps:109,phaseGatedNavigation:true,sequenceMirrorAugmentation:true,heatmapActorFeatures:true,heatmapActorGradientDetached:true,taskFeedback:false}' > "$output/receipt.json"
printf '{"epoch":1,"optimizerSteps":109}\n' > "$output/curves.jsonl"
if [[ "$output" == */baseline-policy ]];then perl -e 'print pack("Q<", $_) for 0..216' > "$output/first-order.bin"
elif [[ "${PUPPYBOT_TEST_OMIT_NEW:-0}" == 1 ]];then perl -e 'print pack("Q<", $_) for 0..216,219' > "$output/first-order.bin"
elif [[ "${PUPPYBOT_TEST_RETURN_PAIRS:-1}" == 2 ]];then perl -e 'print pack("Q<", $_) for 0..215,217,218' > "$output/first-order.bin"
else perl -e 'print pack("Q<", $_) for 0..217' > "$output/first-order.bin";fi
printf 'weights\n' > "$output/weights.bin";printf 'policy\n' > "$output/policy"
EOF
cat > "$runtime/build/flex/control/large-forward-tests" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
mkdir "$3";printf '{"passed":true,"logitMaxAbsError":0,"memoryMaxAbsError":0,"resetBitIdentical":true}\n' > "$3/result.json"
EOF
printf 'trainer\n' > "$runtime/build/flex/control/trainer";chmod +x "$runtime/build/flex/control/control" "$runtime/build/flex/control/large-forward-tests"
cat > "$source/screen-large-model.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
out="$PUPPYBOT_SCREEN_OUTPUT";mkdir "$out"
for index in 2 15 16 17;do seed=$((9960000+index));mkdir -p "$out/$index/$seed/scene";for file in case.json environment.bin;do printf 'scene %s %s\n' "$index" "$file" > "$out/$index/$seed/scene/$file";done;done
printf '{"exploratory":true,"episodes":4,"approaches":0,"returns":0,"rows":[]}\n' > "$out/summary.json"
EOF
driver="$project/datasets/visual-control/expanded-rooms-v1/train-coverage-return-pair.sh"
PUPPYBOT_PROJECT="$mock" PUPPYBOT_COVERAGE_RETURN_PAIR_OUT="$out/good" bash "$driver" > "$out/good.log" 2>&1
jq -e '.initialWeightsIdentical and .seed==202 and .additionalFittingHistorySeen and .baseline.episodes==4 and .augmented.episodes==4' "$out/good/comparison.json" > /dev/null
if PUPPYBOT_PROJECT="$mock" PUPPYBOT_TEST_OMIT_NEW=1 PUPPYBOT_COVERAGE_RETURN_PAIR_OUT="$out/bad" bash "$driver" > "$out/bad.log" 2>&1;then echo 'Training that omitted new histories was accepted.' >&2;exit 1;fi
[[ "$(< "$out/bad/run.exit")" == 1 && ! -e "$out/bad/comparison.json" ]]
echo 'Matched return training checks seeds and exposure to every added fitting history.'
