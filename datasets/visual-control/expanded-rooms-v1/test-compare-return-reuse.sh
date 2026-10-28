#!/usr/bin/env bash
# Return-reuse comparisons must reject corrupt corpus, replay and scenes.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]];mkdir "$out"
PUPPYBOT_PROJECT="$project" bash "$project/datasets/visual-control/expanded-rooms-v1/test-compare-wide-student.sh" "$out/fixture" > /dev/null
mock="$out/fixture/mock";root="$mock/build/flex/sim/expanded-rooms-v1/large-model-v1"
cp -a "$root/wide-student-training-v1" "$root/return-reuse-training-v1"
mkdir "$root/return-reuse-admission-v1";printf '0\n' > "$root/return-reuse-admission-v1/run.exit"
sed 's/corpusHistories:356/corpusHistories:350/' "$out/fixture/student-fake-audit" > "$out/return-fake-audit"
driver="$project/datasets/visual-control/expanded-rooms-v1/compare-return-reuse.sh"
export PUPPYBOT_PROJECT="$mock" PUPPYBOT_RETURN_REUSE_CORPUS_AUDIT="$out/return-fake-audit" PUPPYBOT_RETURN_REUSE_BENCHMARK="$out/fixture/student-fake-benchmark" PUPPYBOT_RETURN_REUSE_BENCHMARK_WAIT_RUN="$root/capacity/run"
for scene_set in standard wide-heading;do
    baseline="$out/fixture/benchmark";if [[ "$scene_set" == wide-heading ]];then baseline="$root/wide-heading-348-candidate-v1";fi
    export PUPPYBOT_TEST_BASELINE="$baseline" PUPPYBOT_RETURN_REUSE_SCENE_SET="$scene_set"
    PUPPYBOT_RETURN_REUSE_BENCHMARK_OUT="$out/pair-$scene_set" bash "$driver" > "$out/pair-$scene_set.log" 2>&1
    jq -e --arg scene "$scene_set" '.complete and .sceneSet==$scene and .identicalCases and .uniqueStartingPoses==8 and .addedFittingHistoriesSeen>0 and .validationSetsDiffer and (.automaticPromotion|not)' "$out/pair-$scene_set/comparison.json" > /dev/null
    for fault in PUPPYBOT_TEST_BAD_CORPUS PUPPYBOT_TEST_BAD_AUDIT PUPPYBOT_TEST_BAD_SCENE;do
        if env "$fault=1" PUPPYBOT_RETURN_REUSE_BENCHMARK_OUT="$out/$fault-$scene_set" bash "$driver" > "$out/$fault-$scene_set.log" 2>&1;then echo "$fault was accepted for $scene_set." >&2;exit 1;fi
        [[ "$(< "$out/$fault-$scene_set/run.exit")" != 0 && ! -e "$out/$fault-$scene_set/comparison.json" ]]
    done
done
echo 'Return-reuse comparisons reject bad corpus, replay and scene checks.'
