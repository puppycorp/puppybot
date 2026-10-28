#!/usr/bin/env bash
# Synthetic varied-room comparison rejects failed corpus and episode audits.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]]
PUPPYBOT_PROJECT="$project" bash "$project/datasets/visual-control/expanded-rooms-v1/test-diverse-development-benchmark.sh" "$out" > /dev/null
mock="$out/mock";root="$mock/build/flex/sim/expanded-rooms-v1/large-model-v1";screen="$root/coverage-scale-training-v1"
mkdir -p "$screen/policy" "$root/coverage-scale-admission-v1" "$root/coverage-v2-student-training-v1/policy"
printf '0\n' > "$screen/run.exit";printf '0\n' > "$root/coverage-scale-admission-v1/run.exit"
ln -s "$out/benchmark" "$root/diverse-development-316-baseline-v1"
cp "$out/policy/weights.bin" "$root/coverage-v2-student-training-v1/policy/weights.bin"
printf 'scaled weights\n' > "$screen/policy/weights.bin";printf '{"dataSHA256":"corpus"}\n' > "$screen/policy/receipt.json"
printf '{"initialWeightsIdentical":true,"differentTrainingData":true,"optimizerStepsPerModel":98,"addedFittingHistoriesSeen":4,"trainingOrdersIdentical":false,"validationSetsDiffer":true,"shuffleAndCheckpointSelectionLimitCausalInterpretation":true,"reservedFinalStillRequired":true,"automaticPromotion":false}\n' > "$screen/comparison.json"
cat > "$out/fake-audit" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
mkdir "$3";sha=corpus;if [[ "${PUPPYBOT_TEST_BAD_CORPUS:-0}" == 1 ]];then sha=wrong;fi
jq -n --arg sha "$sha" '{passed:true,dataSHA256:$sha,corpusHistories:348,episodes:8,exactCaseAndEnvironmentFilesDisjoint:true,reservedFinalUntouched:true}' > "$3/summary.json"
EOF
cat > "$out/fake-benchmark" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
cp -aL "$PUPPYBOT_TEST_BASELINE" "$PUPPYBOT_DIVERSE_BENCHMARK_OUT"
sha="$(sha256sum "$PUPPYBOT_DIVERSE_POLICY/weights.bin" | cut -d' ' -f1)"
jq --arg sha "$sha" '.policyWeightsSHA256=$sha | .rows|=map(.policyWeightsSHA256=$sha)' "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.json" > "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.tmp";mv "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.tmp" "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.json"
if [[ "${PUPPYBOT_TEST_BAD_AUDIT:-0}" == 1 ]];then jq '.rows[0].auditPassed=false' "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.json" > "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.tmp";mv "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.tmp" "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.json";fi
if [[ "${PUPPYBOT_TEST_BAD_SCENE:-0}" == 1 ]];then printf 'changed\n' > "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/0/9980000/scene/case.json";fi
EOF
driver="$project/datasets/visual-control/expanded-rooms-v1/compare-scale-diverse-development.sh"
export PUPPYBOT_PROJECT="$mock" PUPPYBOT_TEST_BASELINE="$out/benchmark" PUPPYBOT_SCALE_DIVERSE_AUDIT="$out/fake-audit" PUPPYBOT_SCALE_DIVERSE_BENCHMARK="$out/fake-benchmark" PUPPYBOT_SCALE_DIVERSE_WAIT_RUN="$root/capacity/run"
PUPPYBOT_SCALE_DIVERSE_OUT="$out/pair" bash "$driver" > "$out/pair.log" 2>&1
jq -e '.complete and .developmentOnly and .identicalCases and .uniqueStartingPoses==8 and .differentTrainingData and .initialWeightsIdentical and .addedFittingHistoriesSeen==4 and .validationSetsDiffer and (.automaticPromotion|not)' "$out/pair/comparison.json" > /dev/null
for fault in PUPPYBOT_TEST_BAD_CORPUS PUPPYBOT_TEST_BAD_AUDIT PUPPYBOT_TEST_BAD_SCENE;do
    if env "$fault=1" PUPPYBOT_SCALE_DIVERSE_OUT="$out/$fault-pair" bash "$driver" > "$out/$fault-pair.log" 2>&1;then echo "$fault was accepted." >&2;exit 1;fi
    [[ "$(< "$out/$fault-pair/run.exit")" != 0 && ! -e "$out/$fault-pair/comparison.json" ]]
done
echo 'Scaled diverse comparison rejects failed corpus, replay and scene checks.'
