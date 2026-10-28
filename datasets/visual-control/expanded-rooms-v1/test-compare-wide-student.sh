#!/usr/bin/env bash
# Both scene sets must reject invalid corpus, replay and scene results.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]]
PUPPYBOT_PROJECT="$project" bash "$project/datasets/visual-control/expanded-rooms-v1/test-diverse-development-benchmark.sh" "$out" > /dev/null
mock="$out/mock";root="$mock/build/flex/sim/expanded-rooms-v1/large-model-v1";screen="$root/wide-student-training-v1"
mkdir -p "$screen/policy" "$root/wide-student-admission-v1" "$root/coverage-scale-training-v1/policy" "$root/coverage-scale-diverse-comparison-v1" "$root/wide-heading-development-v1"
printf '0\n' > "$screen/run.exit";printf '0\n' > "$root/wide-student-admission-v1/run.exit"
ln -s "$out/benchmark" "$root/coverage-scale-diverse-comparison-v1/candidate"
cp -aL "$out/benchmark" "$root/wide-heading-348-candidate-v1"
for ((index=0;index<8;index++));do mv "$root/wide-heading-348-candidate-v1/$index/$((9980000+index))" "$root/wide-heading-348-candidate-v1/$index/$((9990000+index))";done
jq '.sceneSet="wide-heading" | .rows|=map(.layoutId+=38 | .seed+=10000)' "$root/wide-heading-348-candidate-v1/score.json" > "$out/wide-score.json";cp "$out/wide-score.json" "$root/wide-heading-348-candidate-v1/score.json"
cp "$out/policy/weights.bin" "$root/coverage-scale-training-v1/policy/weights.bin"
printf 'student weights\n' > "$screen/policy/weights.bin";printf '{"dataSHA256":"corpus"}\n' > "$screen/policy/receipt.json"
printf '{"initialWeightsIdentical":true,"differentTrainingData":true,"optimizerStepsPerModel":98,"addedFittingHistoriesSeen":2,"trainingOrdersIdentical":false,"validationSetsDiffer":true,"shuffleAndCheckpointSelectionLimitCausalInterpretation":true,"reservedFinalStillRequired":true,"automaticPromotion":false}\n' > "$screen/comparison.json"
cat > "$out/student-fake-audit" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
mkdir "$3";sha=corpus;if [[ "${PUPPYBOT_TEST_BAD_CORPUS:-0}" == 1 ]];then sha=wrong;fi
jq -n --arg sha "$sha" '{passed:true,dataSHA256:$sha,corpusHistories:356,episodes:8,exactCaseAndEnvironmentFilesDisjoint:true,reservedFinalUntouched:true}' > "$3/summary.json"
EOF
cat > "$out/student-fake-benchmark" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
cp -aL "$PUPPYBOT_TEST_BASELINE" "$PUPPYBOT_DIVERSE_BENCHMARK_OUT"
sha="$(sha256sum "$PUPPYBOT_DIVERSE_POLICY/weights.bin" | cut -d' ' -f1)"
jq --arg sha "$sha" '.policyWeightsSHA256=$sha | .rows|=map(.policyWeightsSHA256=$sha)' "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.json" > "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.tmp";mv "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.tmp" "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.json"
if [[ "${PUPPYBOT_TEST_BAD_AUDIT:-0}" == 1 ]];then jq '.rows[0].auditPassed=false' "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.json" > "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.tmp";mv "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.tmp" "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.json";fi
if [[ "${PUPPYBOT_TEST_BAD_SCENE:-0}" == 1 ]];then seed=9980000;if [[ "$PUPPYBOT_DIVERSE_SCENE_SET" == wide-heading ]];then seed=9990000;fi;printf 'changed\n' > "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/0/$seed/scene/case.json";fi
EOF
driver="$project/datasets/visual-control/expanded-rooms-v1/compare-wide-student.sh"
export PUPPYBOT_PROJECT="$mock" PUPPYBOT_WIDE_STUDENT_CORPUS_AUDIT="$out/student-fake-audit" PUPPYBOT_WIDE_STUDENT_BENCHMARK="$out/student-fake-benchmark" PUPPYBOT_WIDE_STUDENT_BENCHMARK_WAIT_RUN="$root/capacity/run"
for scene_set in standard wide-heading;do
    baseline="$out/benchmark";if [[ "$scene_set" == wide-heading ]];then baseline="$root/wide-heading-348-candidate-v1";fi
    export PUPPYBOT_TEST_BASELINE="$baseline" PUPPYBOT_WIDE_STUDENT_SCENE_SET="$scene_set"
    PUPPYBOT_WIDE_STUDENT_BENCHMARK_OUT="$out/pair-$scene_set" bash "$driver" > "$out/pair-$scene_set.log" 2>&1
    jq -e --arg scene "$scene_set" '.complete and .sceneSet==$scene and .developmentOnly and .identicalCases and .uniqueStartingPoses==8 and .differentTrainingData and .initialWeightsIdentical and .addedFittingHistoriesSeen==2 and .validationSetsDiffer and (.automaticPromotion|not)' "$out/pair-$scene_set/comparison.json" > /dev/null
    for fault in PUPPYBOT_TEST_BAD_CORPUS PUPPYBOT_TEST_BAD_AUDIT PUPPYBOT_TEST_BAD_SCENE;do
        if env "$fault=1" PUPPYBOT_WIDE_STUDENT_BENCHMARK_OUT="$out/$fault-$scene_set" bash "$driver" > "$out/$fault-$scene_set.log" 2>&1;then echo "$fault was accepted for $scene_set." >&2;exit 1;fi
        [[ "$(< "$out/$fault-$scene_set/run.exit")" != 0 && ! -e "$out/$fault-$scene_set/comparison.json" ]]
    done
done
echo 'Student comparisons reject failed corpus, replay and scene checks for both scene sets.'
