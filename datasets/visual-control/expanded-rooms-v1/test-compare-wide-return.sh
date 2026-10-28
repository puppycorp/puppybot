#!/usr/bin/env bash
# Wide-return comparisons require the matching corpus and recorded scenes.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]];mkdir "$out"
PUPPYBOT_PROJECT="$project" bash "$project/datasets/visual-control/expanded-rooms-v1/test-compare-return-reuse.sh" "$out/fixture" > /dev/null
mock="$out/fixture/fixture/mock";root="$mock/build/flex/sim/expanded-rooms-v1/large-model-v1"
cp -a "$root/return-reuse-training-v1" "$root/wide-return-training-v1"
printf 'wider return weights\n' > "$root/wide-return-training-v1/policy/weights.bin"
mkdir "$root/wide-return-admission-v1";printf '0\n' > "$root/wide-return-admission-v1/run.exit";printf '{"episodes":354}\n' > "$root/wide-return-admission-v1/coverage.json"
mkdir "$root/return-reuse-standard-comparison-v1" "$root/return-reuse-wide-comparison-v1"
printf '0\n' > "$root/return-reuse-standard-comparison-v1/run.exit";printf '0\n' > "$root/return-reuse-wide-comparison-v1/run.exit"
ln -s "$out/fixture/pair-standard/candidate" "$root/return-reuse-standard-comparison-v1/candidate"
ln -s "$out/fixture/pair-wide-heading/candidate" "$root/return-reuse-wide-comparison-v1/candidate"
sed 's/corpusHistories:350/corpusHistories:354/' "$out/fixture/return-fake-audit" > "$out/wide-return-fake-audit"
driver="$project/datasets/visual-control/expanded-rooms-v1/compare-wide-return.sh"
export PUPPYBOT_PROJECT="$mock" PUPPYBOT_WIDE_RETURN_CORPUS_AUDIT="$out/wide-return-fake-audit" PUPPYBOT_WIDE_RETURN_BENCHMARK="$out/fixture/fixture/student-fake-benchmark" PUPPYBOT_WIDE_RETURN_BENCHMARK_WAIT_RUN="$root/capacity/run"
for scene_set in standard wide-heading;do
    baseline="$root/return-reuse-standard-comparison-v1/candidate";if [[ "$scene_set" == wide-heading ]];then baseline="$root/return-reuse-wide-comparison-v1/candidate";fi
    export PUPPYBOT_TEST_BASELINE="$baseline" PUPPYBOT_WIDE_RETURN_SCENE_SET="$scene_set"
    PUPPYBOT_WIDE_RETURN_BENCHMARK_OUT="$out/pair-$scene_set" bash "$driver" > "$out/pair-$scene_set.log" 2>&1
    jq -e --arg scene "$scene_set" '.complete and .sceneSet==$scene and .identicalCases and .uniqueStartingPoses==8 and .addedFittingHistoriesSeen>0 and .validationSetsDiffer and (.automaticPromotion|not)' "$out/pair-$scene_set/comparison.json" > /dev/null
    for fault in PUPPYBOT_TEST_BAD_CORPUS PUPPYBOT_TEST_BAD_AUDIT PUPPYBOT_TEST_BAD_SCENE;do
        if env "$fault=1" PUPPYBOT_WIDE_RETURN_BENCHMARK_OUT="$out/$fault-$scene_set" bash "$driver" > "$out/$fault-$scene_set.log" 2>&1;then echo "$fault was accepted for $scene_set." >&2;exit 1;fi
        [[ "$(< "$out/$fault-$scene_set/run.exit")" != 0 && ! -e "$out/$fault-$scene_set/comparison.json" ]]
    done
done
printf '{"episodes":352}\n' > "$root/wide-return-admission-v1/coverage.json"
sed -i 's/corpusHistories:354/corpusHistories:352/' "$out/wide-return-fake-audit"
PUPPYBOT_TEST_BASELINE="$root/return-reuse-standard-comparison-v1/candidate" PUPPYBOT_WIDE_RETURN_SCENE_SET=standard PUPPYBOT_WIDE_RETURN_BENCHMARK_OUT="$out/one-pair" bash "$driver" > "$out/one-pair.log" 2>&1
jq -e '.complete and .identicalCases and .uniqueStartingPoses==8' "$out/one-pair/comparison.json" > /dev/null
printf '{"episodes":353}\n' > "$root/wide-return-admission-v1/coverage.json"
if PUPPYBOT_TEST_BASELINE="$root/return-reuse-standard-comparison-v1/candidate" PUPPYBOT_WIDE_RETURN_SCENE_SET=standard PUPPYBOT_WIDE_RETURN_BENCHMARK_OUT="$out/invalid-count" bash "$driver" > "$out/invalid-count.log" 2>&1;then echo 'Invalid corpus size was accepted.' >&2;exit 1;fi
[[ "$(< "$out/invalid-count/run.exit")" != 0 && ! -e "$out/invalid-count/comparison.json" ]]
echo 'Wide-return comparisons reject bad corpus, replay and scene checks.'
