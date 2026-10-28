#!/usr/bin/env bash
# Synthetic paired evaluation rejects scene changes and unaudited episodes.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]]
PUPPYBOT_PROJECT="$project" bash "$project/datasets/visual-control/expanded-rooms-v1/test-diverse-development-benchmark.sh" "$out" > /dev/null
mock="$out/mock";root="$mock/build/flex/sim/expanded-rooms-v1/large-model-v1";screen="$root/longer-316-screen-v1"
mkdir -p "$root/longer-316-queue-v1" "$root/coverage-v2-student-training-v1/policy" "$screen/policy"
printf '0\n' > "$root/longer-316-queue-v1/run.exit";ln -s "$out/benchmark" "$root/diverse-development-316-baseline-v1"
cp "$out/policy/weights.bin" "$root/coverage-v2-student-training-v1/policy/weights.bin"
printf 'candidate\n' > "$screen/policy/weights.bin";printf '{}\n' > "$screen/policy/receipt.json"
printf '{"sameTrainingData":true,"initialWeightsIdentical":true,"firstTrainingOrderIdentical":true,"firstOptimizerUpdateIdentical":true,"baselineOptimizerSteps":98,"candidateOptimizerSteps":1110,"automaticPromotion":false}\n' > "$screen/comparison.json"
cat > "$out/fake-benchmark" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
root="$PUPPYBOT_PROJECT/build/flex/sim/expanded-rooms-v1/large-model-v1"
cp -aL "$root/diverse-development-316-baseline-v1" "$PUPPYBOT_DIVERSE_BENCHMARK_OUT"
sha="$(sha256sum "$PUPPYBOT_DIVERSE_POLICY/weights.bin" | cut -d' ' -f1)"
jq --arg sha "$sha" '.policyWeightsSHA256=$sha | .rows|=map(.policyWeightsSHA256=$sha)' "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.json" > "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.tmp"
mv "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.tmp" "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.json"
if [[ "${PUPPYBOT_TEST_BAD_AUDIT:-0}" == 1 ]];then jq '.rows[0].auditPassed=false' "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.json" > "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.tmp";mv "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.tmp" "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.json";fi
if [[ "${PUPPYBOT_TEST_DUPLICATE_CASE:-0}" == 1 ]];then jq '.rows[0].caseIndex=.rows[1].caseIndex' "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.json" > "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.tmp";mv "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.tmp" "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.json";fi
if [[ "${PUPPYBOT_TEST_BAD_SCENE:-0}" == 1 ]];then printf 'changed\n' > "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/0/9980000/scene/case.json";fi
EOF
driver="$project/datasets/visual-control/expanded-rooms-v1/compare-longer-diverse-development.sh"
export PUPPYBOT_PROJECT="$mock" PUPPYBOT_DIVERSE_FROZEN_BENCHMARK="$out/fake-benchmark"
PUPPYBOT_LONGER_DIVERSE_OUT="$out/pair" bash "$driver" > "$out/pair.log" 2>&1
jq -e '.complete and .developmentOnly and .identicalCases and .uniqueStartingPoses==8 and .sameTrainingData and .firstOptimizerUpdateIdentical and (.automaticPromotion|not)' "$out/pair/comparison.json" > /dev/null
for fault in PUPPYBOT_TEST_BAD_AUDIT PUPPYBOT_TEST_BAD_SCENE PUPPYBOT_TEST_DUPLICATE_CASE;do
    if env "$fault=1" PUPPYBOT_LONGER_DIVERSE_OUT="$out/$fault-pair" bash "$driver" > "$out/$fault-pair.log" 2>&1;then echo "$fault was accepted." >&2;exit 1;fi
    [[ "$(< "$out/$fault-pair/run.exit")" != 0 && ! -e "$out/$fault-pair/comparison.json" ]]
done
echo 'Distinct-start paired comparison rejects failed audits and changed scenes.'
