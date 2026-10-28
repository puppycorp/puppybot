#!/usr/bin/env bash
# Pose comparisons preserve the controlled data and inference boundary.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]];mkdir "$out"
PUPPYBOT_PROJECT="$project" bash "$project/datasets/visual-control/expanded-rooms-v1/test-compare-neutral-drive.sh" "$out/fixture" > /dev/null
mock="$out/fixture/fixture/fixture/fixture/fixture/fixture/mock";root="$mock/build/flex/sim/expanded-rooms-v1/large-model-v1";baseline="$root/neutral-drive-training-v2";screen="$root/neutral-pose-training-v3"
mkdir -p "$screen/policy";printf 'pose model\n' > "$screen/policy/weights.bin";sha="$(sha256sum "$screen/policy/weights.bin" | cut -d' ' -f1)";baseline_sha="$(sha256sum "$baseline/policy/weights.bin" | cut -d' ' -f1)"
jq -n --arg sha "$sha" '{weightsSHA256:$sha,dataSHA256:"corpus",memoryWidth:256,memoryPoseAuxiliary:true,memoryPoseTargetsSHA256:("a"*64),driveFeedbackDropMilli:1000,taskFeedback:false}' > "$screen/policy/receipt.json"
printf '0\n' > "$screen/run.exit"
jq '.initialActorTensorsIdentical=true | .poseTargetsTrainingOnly=true | .poseLossChangesValidationSelection=true' "$baseline/comparison.json" > "$screen/comparison.json"
for scene_set in standard wide-heading;do
    job="$root/neutral-drive-standard-comparison-v1";if [[ "$scene_set" == wide-heading ]];then job="$root/neutral-drive-wide-comparison-v1";fi
    mkdir "$job";printf '0\n' > "$job/run.exit"
    cp -aL "$out/fixture/pair-$scene_set/candidate" "$job/candidate"
    jq --arg sha "$baseline_sha" '.policyWeightsSHA256=$sha | .rows|=map(.policyWeightsSHA256=$sha)' "$job/candidate/score.json" > "$out/score.tmp";cp "$out/score.tmp" "$job/candidate/score.json"
done
driver="$project/datasets/visual-control/expanded-rooms-v1/compare-neutral-pose.sh"
export PUPPYBOT_PROJECT="$mock" PUPPYBOT_NEUTRAL_POSE_CORPUS_AUDIT="$out/fixture/fixture/fixture/incomplete-return-fake-audit" PUPPYBOT_NEUTRAL_POSE_BENCHMARK="$out/fixture/fixture/fixture/fixture/fixture/fixture/student-fake-benchmark" PUPPYBOT_NEUTRAL_POSE_VERIFY_ZERO="$out/fixture/fake-zero" PUPPYBOT_NEUTRAL_POSE_BENCHMARK_WAIT_RUN="$root/capacity/run"
for scene_set in standard wide-heading;do
    job="$root/neutral-drive-standard-comparison-v1";if [[ "$scene_set" == wide-heading ]];then job="$root/neutral-drive-wide-comparison-v1";fi
    export PUPPYBOT_TEST_BASELINE="$job/candidate" PUPPYBOT_NEUTRAL_POSE_SCENE_SET="$scene_set"
    PUPPYBOT_NEUTRAL_POSE_BENCHMARK_OUT="$out/pair-$scene_set" bash "$driver" > "$out/pair-$scene_set.log" 2>&1
    jq -e --arg scene "$scene_set" '.complete and .sceneSet==$scene and .identicalCases and .poseTargetsTrainingOnly and .poseLossChangesValidationSelection and .initialActorTensorsIdentical and (.automaticPromotion|not)' "$out/pair-$scene_set/comparison.json" > /dev/null
    for fault in PUPPYBOT_TEST_BAD_ZERO PUPPYBOT_TEST_BAD_CORPUS PUPPYBOT_TEST_BAD_AUDIT PUPPYBOT_TEST_BAD_SCENE;do
        if env "$fault=1" PUPPYBOT_NEUTRAL_POSE_BENCHMARK_OUT="$out/$fault-$scene_set" bash "$driver" > "$out/$fault-$scene_set.log" 2>&1;then echo "$fault was accepted for $scene_set." >&2;exit 1;fi
        [[ "$(< "$out/$fault-$scene_set/run.exit")" != 0 && ! -e "$out/$fault-$scene_set/comparison.json" ]]
    done
done
echo 'Neutral-pose comparisons reject invalid weights, corpus, replay and scenes.'
