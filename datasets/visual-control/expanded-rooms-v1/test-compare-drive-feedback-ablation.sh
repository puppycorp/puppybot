#!/usr/bin/env bash
# Ablation comparisons reject unrelated weight changes and bad scene audits.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]];mkdir "$out"
PUPPYBOT_PROJECT="$project" bash "$project/datasets/visual-control/expanded-rooms-v1/test-compare-incomplete-return.sh" "$out/fixture" > /dev/null
mock="$out/fixture/fixture/fixture/fixture/mock";root="$mock/build/flex/sim/expanded-rooms-v1/large-model-v1";original="$root/incomplete-return-training-v1/policy";screen="$root/drive-feedback-ablation-v1"
mkdir -p "$screen/policy/kernels" "$original/kernels"
perl -e 'binmode STDOUT; print "\1" x 20000' > "$original/weights.bin"
perl -e 'binmode STDOUT; print "\1" x 128, "\0" x 15360, "\1" x (20000-128-15360)' > "$screen/policy/weights.bin"
printf 'policy\n' > "$original/policy";printf 'graph\n' > "$original/model.pup";printf 'kernel\n' > "$original/kernels/test"
cp "$original/policy" "$original/model.pup" "$screen/policy/";cp "$original/kernels/test" "$screen/policy/kernels/test"
baseline_sha="$(sha256sum "$original/weights.bin" | cut -d' ' -f1)";candidate_sha="$(sha256sum "$screen/policy/weights.bin" | cut -d' ' -f1)"
printf '{"dataSHA256":"corpus","memoryWidth":256,"taskFeedback":false}\n' > "$original/receipt.json";printf '{"dataSHA256":"corpus","memoryWidth":256,"taskFeedback":false}\n' > "$screen/policy/receipt.json"
jq -n --arg parent "$baseline_sha" --arg sha "$candidate_sha" '{passed:true,parentWeightsSHA256:$parent,weightsSHA256:$sha,driveFeedbackValuesZeroed:5,contactFeedbackPreserved:true,otherWeightsPreserved:true,singleFrameForwardChecked:true,trainingPerformed:false,closedLoopPerformanceNotMeasured:true,automaticPromotion:false}' > "$screen/summary.json"
jq -n --arg parent "$baseline_sha" --arg sha "$candidate_sha" '{passed:true,sourceSHA256:$parent,weightsSHA256:$sha,firstByte:128,bytesZeroed:15360,driveFeedbackValuesZeroed:5}' > "$screen/ablation.json";printf '0\n' > "$screen/run.exit"
mkdir "$root/incomplete-return-standard-comparison-v1" "$root/incomplete-return-wide-comparison-v1"
for scene_set in standard wide-heading;do
    job="$root/incomplete-return-standard-comparison-v1";if [[ "$scene_set" == wide-heading ]];then job="$root/incomplete-return-wide-comparison-v1";fi
    printf '0\n' > "$job/run.exit";cp -aL "$out/fixture/pair-$scene_set/candidate" "$job/candidate"
    jq --arg sha "$baseline_sha" '.policyWeightsSHA256=$sha | .rows|=map(.policyWeightsSHA256=$sha)' "$job/candidate/score.json" > "$out/score.tmp";cp "$out/score.tmp" "$job/candidate/score.json"
done
driver="$project/datasets/visual-control/expanded-rooms-v1/compare-drive-feedback-ablation.sh"
export PUPPYBOT_PROJECT="$mock" PUPPYBOT_DRIVE_ABLATE_CORPUS_AUDIT="$out/fixture/incomplete-return-fake-audit" PUPPYBOT_DRIVE_ABLATE_BENCHMARK="$out/fixture/fixture/fixture/fixture/student-fake-benchmark" PUPPYBOT_DRIVE_ABLATE_BENCHMARK_WAIT_RUN="$root/capacity/run"
for scene_set in standard wide-heading;do
    baseline="$root/incomplete-return-standard-comparison-v1/candidate";if [[ "$scene_set" == wide-heading ]];then baseline="$root/incomplete-return-wide-comparison-v1/candidate";fi
    export PUPPYBOT_TEST_BASELINE="$baseline" PUPPYBOT_DRIVE_ABLATE_SCENE_SET="$scene_set"
    PUPPYBOT_DRIVE_ABLATE_BENCHMARK_OUT="$out/pair-$scene_set" bash "$driver" > "$out/pair-$scene_set.log" 2>&1
    jq -e --arg scene "$scene_set" '.complete and .sceneSet==$scene and .identicalCases and .uniqueStartingPoses==8 and .sameTrainingData and .onlyDriveFeedbackWeightsAblated and .contactFeedbackPreserved and (.trainingPerformed|not) and (.automaticPromotion|not)' "$out/pair-$scene_set/comparison.json" > /dev/null
    for fault in PUPPYBOT_TEST_BAD_CORPUS PUPPYBOT_TEST_BAD_AUDIT PUPPYBOT_TEST_BAD_SCENE;do
        if env "$fault=1" PUPPYBOT_DRIVE_ABLATE_BENCHMARK_OUT="$out/$fault-$scene_set" bash "$driver" > "$out/$fault-$scene_set.log" 2>&1;then echo "$fault was accepted for $scene_set." >&2;exit 1;fi
        [[ "$(< "$out/$fault-$scene_set/run.exit")" != 0 && ! -e "$out/$fault-$scene_set/comparison.json" ]]
    done
done
printf '\2' | dd of="$screen/policy/weights.bin" bs=1 seek=0 conv=notrunc status=none
bad_sha="$(sha256sum "$screen/policy/weights.bin" | cut -d' ' -f1)"
for file in summary.json ablation.json;do jq --arg sha "$bad_sha" '.weightsSHA256=$sha' "$screen/$file" > "$out/bad-receipt.tmp";cp "$out/bad-receipt.tmp" "$screen/$file";done
if PUPPYBOT_TEST_BASELINE="$root/incomplete-return-standard-comparison-v1/candidate" PUPPYBOT_DRIVE_ABLATE_SCENE_SET=standard PUPPYBOT_DRIVE_ABLATE_BENCHMARK_OUT="$out/bad-weights" bash "$driver" > "$out/bad-weights.log" 2>&1;then echo 'Unrelated weight change was accepted.' >&2;exit 1;fi
[[ "$(< "$out/bad-weights/run.exit")" != 0 && ! -e "$out/bad-weights/comparison.json" ]]
echo 'Drive ablation comparisons reject unrelated weight, corpus, replay and scene changes.'
