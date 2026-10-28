#!/usr/bin/env bash
# Synthetic comparison checks matching cases and replay audits.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]]
PUPPYBOT_PROJECT="$project" bash "$project/datasets/visual-control/expanded-rooms-v1/test-diverse-development-benchmark.sh" "$out" > /dev/null
mock="$out/mock";root="$mock/build/flex/sim/expanded-rooms-v1/large-model-v1";pair="$root/return-reversal-screen-v1";baseline="$root/coverage-return-pair-v1/augmented-policy";candidate="$pair/policy"
mkdir -p "$baseline" "$candidate" "$root/return-reversal-benchmark-v1" "$root/diverse-development-310-corpus-audit-v1" "$root/capacity"
printf '0\n' > "$pair/run.exit";printf '0\n' > "$root/return-reversal-benchmark-v1/run.exit";printf '0\n' > "$root/capacity/run.exit"
cp "$out/policy/weights.bin" "$baseline/weights.bin";printf 'candidate\n' > "$candidate/weights.bin"
for arm in baseline candidate;do policy="$baseline";if [[ "$arm" == candidate ]];then policy="$candidate";fi;sha="$(sha256sum "$policy/weights.bin" | cut -d' ' -f1)";jq -n --arg sha "$sha" '{dataSHA256:"corpus",weightsSHA256:$sha,memoryWidth:256,reversalPenaltyMilli:1000,taskFeedback:false}' > "$policy/receipt.json";done
printf '{"sameTrainingData":true,"initialWeightsIdentical":true,"trainingOrdersIdentical":true,"mirrorMasksIdentical":true,"optimizerStepsPerModel":109,"reversalPenaltyMilli":1000,"reservedFinalStillRequired":true,"automaticPromotion":false}\n' > "$pair/comparison.json"
printf '{"passed":true,"dataSHA256":"corpus","corpusHistories":310,"episodes":8,"exactCaseAndEnvironmentFilesDisjoint":true,"reservedFinalUntouched":true}\n' > "$root/diverse-development-310-corpus-audit-v1/summary.json"
cat > "$out/fake-benchmark" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
cp -aL "$PUPPYBOT_TEST_BASELINE" "$PUPPYBOT_DIVERSE_BENCHMARK_OUT"
sha="$(sha256sum "$PUPPYBOT_DIVERSE_POLICY/weights.bin" | cut -d' ' -f1)"
jq --arg sha "$sha" '.policyWeightsSHA256=$sha | .rows|=map(.policyWeightsSHA256=$sha)' "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.json" > "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.tmp";mv "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.tmp" "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.json"
if [[ "${PUPPYBOT_TEST_BAD_AUDIT:-0}" == 1 && "$PUPPYBOT_DIVERSE_BENCHMARK_OUT" == */candidate ]];then jq '.rows[0].auditPassed=false' "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.json" > "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.tmp";mv "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.tmp" "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.json";fi
if [[ "${PUPPYBOT_TEST_BAD_SCENE:-0}" == 1 && "$PUPPYBOT_DIVERSE_BENCHMARK_OUT" == */candidate ]];then printf 'changed\n' > "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/0/9980000/scene/case.json";fi
EOF
driver="$project/datasets/visual-control/expanded-rooms-v1/compare-reversal-diverse-development.sh"
export PUPPYBOT_PROJECT="$mock" PUPPYBOT_TEST_BASELINE="$out/benchmark" PUPPYBOT_REVERSAL_DIVERSE_WAIT_RUN="$root/capacity/run" PUPPYBOT_REVERSAL_DIVERSE_BENCHMARK="$out/fake-benchmark"
PUPPYBOT_REVERSAL_DIVERSE_OUT="$out/pair" bash "$driver" > "$out/pair.log" 2>&1
jq -e '.complete and .developmentOnly and .identicalCases and .uniqueStartingPoses==8 and .sameTrainingData and .trainingOrdersIdentical and .reversalPenaltyMilli==1000 and (.automaticPromotion|not)' "$out/pair/comparison.json" > /dev/null
for fault in PUPPYBOT_TEST_BAD_AUDIT PUPPYBOT_TEST_BAD_SCENE;do
    if env "$fault=1" PUPPYBOT_REVERSAL_DIVERSE_OUT="$out/$fault-pair" bash "$driver" > "$out/$fault-pair.log" 2>&1;then echo "$fault was accepted." >&2;exit 1;fi
    [[ "$(< "$out/$fault-pair/run.exit")" != 0 && ! -e "$out/$fault-pair/comparison.json" ]]
done
echo 'Reversal diverse comparison rejects failed audits and changed scenes.'
