#!/usr/bin/env bash
# Incomplete-return comparisons require the expected corpus and recorded scenes.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]];mkdir "$out"
PUPPYBOT_PROJECT="$project" bash "$project/datasets/visual-control/expanded-rooms-v1/test-compare-wide-return.sh" "$out/fixture" > /dev/null
mock="$out/fixture/fixture/fixture/mock";root="$mock/build/flex/sim/expanded-rooms-v1/large-model-v1"
cp -a "$root/wide-return-training-v1" "$root/incomplete-return-training-v1"
printf 'incomplete return weights\n' > "$root/incomplete-return-training-v1/policy/weights.bin"
mkdir "$root/incomplete-return-admission-v1";printf '0\n' > "$root/incomplete-return-admission-v1/run.exit";printf '{"episodes":354}\n' > "$root/incomplete-return-admission-v1/coverage.json"
mkdir "$root/wide-return-standard-comparison-v1" "$root/wide-return-wide-comparison-v1"
printf '0\n' > "$root/wide-return-standard-comparison-v1/run.exit";printf '0\n' > "$root/wide-return-wide-comparison-v1/run.exit"
ln -s "$out/fixture/pair-standard/candidate" "$root/wide-return-standard-comparison-v1/candidate"
ln -s "$out/fixture/pair-wide-heading/candidate" "$root/wide-return-wide-comparison-v1/candidate"
sed 's/corpusHistories:352/corpusHistories:354/' "$out/fixture/wide-return-fake-audit" > "$out/incomplete-return-fake-audit"
driver="$project/datasets/visual-control/expanded-rooms-v1/compare-incomplete-return.sh"
export PUPPYBOT_PROJECT="$mock" PUPPYBOT_INCOMPLETE_RETURN_CORPUS_AUDIT="$out/incomplete-return-fake-audit" PUPPYBOT_INCOMPLETE_RETURN_BENCHMARK="$out/fixture/fixture/fixture/student-fake-benchmark" PUPPYBOT_INCOMPLETE_RETURN_BENCHMARK_WAIT_RUN="$root/capacity/run"
for scene_set in standard wide-heading;do
    baseline="$root/wide-return-standard-comparison-v1/candidate";if [[ "$scene_set" == wide-heading ]];then baseline="$root/wide-return-wide-comparison-v1/candidate";fi
    export PUPPYBOT_TEST_BASELINE="$baseline" PUPPYBOT_INCOMPLETE_RETURN_SCENE_SET="$scene_set"
    PUPPYBOT_INCOMPLETE_RETURN_BENCHMARK_OUT="$out/pair-$scene_set" bash "$driver" > "$out/pair-$scene_set.log" 2>&1
    jq -e --arg scene "$scene_set" '.complete and .sceneSet==$scene and .identicalCases and .uniqueStartingPoses==8 and .addedFittingHistoriesSeen>0 and .validationSetsDiffer and (.automaticPromotion|not)' "$out/pair-$scene_set/comparison.json" > /dev/null
    for fault in PUPPYBOT_TEST_BAD_CORPUS PUPPYBOT_TEST_BAD_AUDIT PUPPYBOT_TEST_BAD_SCENE;do
        if env "$fault=1" PUPPYBOT_INCOMPLETE_RETURN_BENCHMARK_OUT="$out/$fault-$scene_set" bash "$driver" > "$out/$fault-$scene_set.log" 2>&1;then echo "$fault was accepted for $scene_set." >&2;exit 1;fi
        [[ "$(< "$out/$fault-$scene_set/run.exit")" != 0 && ! -e "$out/$fault-$scene_set/comparison.json" ]]
    done
done
echo 'Incomplete-return comparisons reject bad corpus, replay and scene checks.'
