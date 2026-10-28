#!/usr/bin/env bash
# Synthetic control-flow test: no simulator or reserved layout is used.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(/usr/bin/realpath -m "${1:?New output directory required}")"
[[ ! -e "$out" ]]
mock="$out/mock"
pair="$mock/build/flex/sim/expanded-rooms-v1/large-model-v1/gated-search-pair-v1"
mkdir -p "$pair/baseline-policy" "$pair/augmented-policy"
printf '0\n' > "$pair/run.exit"
printf '{"exploratory":true,"optimizerStepsPerModel":98,"initialWeightsIdentical":true,"additionalFittingHistorySeen":true,"trainingOrdersIdentical":false,"reservedFinalStillRequired":true,"automaticPromotion":false}\n' > "$pair/comparison.json"
for arm in baseline augmented;do
    printf '%s weights\n' "$arm" > "$pair/$arm-policy/weights.bin"
    printf '%s binary\n' "$arm" > "$pair/$arm-policy/policy"
    printf '{}\n' > "$pair/$arm-policy/receipt.json"
done
cat > "$out/benchmark" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
root="$PUPPYBOT_RETURN_BENCHMARK";mkdir "$root"
sha="$(/usr/bin/sha256sum "$PUPPYBOT_RETURN_TRAINING/policy/weights.bin" | /usr/bin/cut -d' ' -f1)"
count=0; if [[ "$root" == */augmented || "$root" == */candidate ]];then count=1;fi
for ((index=0;index<32;index++));do seed=$((9960000+index));mkdir -p "$root/$index/$seed/scene";for file in case.json environment.bin;do printf 'scene %s %s\n' "$index" "$file" > "$root/$index/$seed/scene/$file";done;done
/usr/bin/jq -n --arg sha "$sha" --argjson count "$count" --argjson fault "${PUPPYBOT_TEST_FAULT:-0}" '{episodes:32,completedRecordings:32,auditedEpisodes:32,approaches:$count,returns:$count,openReturns:$count,hiddenReturns:0,meanClosestM:1,meanSuccessfulSimulationSeconds:null,rows:[range(0;32)|{caseIndex:.,layoutId:(18+(./16|floor)),seed:(9960000+.),recordingCompleted:true,auditPassed:(if .==0 and $fault==1 then false else true end),policyWeightsSHA256:$sha,maximumBrickDistanceM:0.35,suppliedMap:false,taskEventHint:false,found:(.==0 and $count==1),physicalReturned:(.==0 and $count==1)}]}' > "$root/score.json"
printf '0\n' > "$root/run.exit"
EOF
driver="$project/datasets/visual-control/expanded-rooms-v1/benchmark-gated-search-pair.sh"
PUPPYBOT_PROJECT="$mock" PUPPYBOT_GATED_PAIR_BENCHMARK_SCRIPT="$out/benchmark" PUPPYBOT_GATED_PAIR_BENCHMARK_OUT="$out/good" /usr/bin/bash "$driver" > "$out/good.log" 2>&1
/usr/bin/jq -e '.complete and .identicalCases and .gainedApproaches==1 and .gainedReturns==1 and (.automaticPromotion|not)' "$out/good/comparison.json" > /dev/null
cp -a "$pair" "$out/alternate-pair"
mkdir "$out/parent-job"
printf '0\n' > "$out/parent-job/run.exit"
PUPPYBOT_PROJECT="$mock" PUPPYBOT_GATED_PAIR_DIRECTORY="$out/alternate-pair" PUPPYBOT_GATED_PAIR_WAIT_RUN="$out/parent-job/run" PUPPYBOT_GATED_PAIR_BENCHMARK_SCRIPT="$out/benchmark" PUPPYBOT_GATED_PAIR_BENCHMARK_OUT="$out/alternate" /usr/bin/bash "$driver" > "$out/alternate.log" 2>&1
/usr/bin/jq -e '.complete and .identicalCases' "$out/alternate/comparison.json" > /dev/null
if PUPPYBOT_PROJECT="$mock" PUPPYBOT_TEST_FAULT=1 PUPPYBOT_GATED_PAIR_BENCHMARK_SCRIPT="$out/benchmark" PUPPYBOT_GATED_PAIR_BENCHMARK_OUT="$out/bad" /usr/bin/bash "$driver" > "$out/bad.log" 2>&1;then echo 'Unaudited episode was accepted.' >&2;exit 1;fi
[[ "$(< "$out/bad/run.exit")" == 1 && ! -e "$out/bad/comparison.json" ]]
root="$mock/build/flex/sim/expanded-rooms-v1/large-model-v1"
mkdir -p "$root/phase-consistency-screen-v1/policy" "$root/gated-search-pair-benchmark-v1"
printf 'consistent weights\n' > "$root/phase-consistency-screen-v1/policy/weights.bin"
printf '{}\n' > "$root/phase-consistency-screen-v1/policy/receipt.json"
printf '{"sameTrainingData":true,"initialWeightsIdentical":true,"trainingOrdersIdentical":true,"mirrorMasksIdentical":true,"optimizerStepsPerModel":98,"phaseConsistencyMilli":1000,"reservedFinalStillRequired":true,"automaticPromotion":false}\n' > "$root/phase-consistency-screen-v1/comparison.json"
printf '0\n' > "$root/phase-consistency-screen-v1/run.exit"
ln -s "$out/good/augmented" "$root/gated-search-pair-benchmark-v1/augmented"
printf '0\n' > "$root/gated-search-pair-benchmark-v1/run.exit"
consistency="$project/datasets/visual-control/expanded-rooms-v1/benchmark-phase-consistency.sh"
PUPPYBOT_PROJECT="$mock" PUPPYBOT_CONSISTENCY_BENCHMARK_SCRIPT="$out/benchmark" PUPPYBOT_CONSISTENCY_BENCHMARK_OUT="$out/consistency" /usr/bin/bash "$consistency" > "$out/consistency.log" 2>&1
/usr/bin/jq -e '.complete and .identicalCases and .baseline.returns==1 and .candidate.returns==1 and (.automaticPromotion|not)' "$out/consistency/comparison.json" > /dev/null
if PUPPYBOT_PROJECT="$mock" PUPPYBOT_TEST_FAULT=1 PUPPYBOT_CONSISTENCY_BENCHMARK_SCRIPT="$out/benchmark" PUPPYBOT_CONSISTENCY_BENCHMARK_OUT="$out/consistency-bad" /usr/bin/bash "$consistency" > "$out/consistency-bad.log" 2>&1;then echo 'Unaudited consistency episode was accepted.' >&2;exit 1;fi
[[ "$(< "$out/consistency-bad/run.exit")" == 1 && ! -e "$out/consistency-bad/comparison.json" ]]
mkdir -p "$root/coverage-student-training-v1/policy" "$root/student-only-training-v1/policy" "$root/student-only-benchmark-v1"
cp "$pair/augmented-policy/weights.bin" "$root/student-only-training-v1/policy/weights.bin"
printf '{}\n' > "$root/student-only-training-v1/policy/receipt.json"
printf 'coverage weights\n' > "$root/coverage-student-training-v1/policy/weights.bin"
printf '{}\n' > "$root/coverage-student-training-v1/policy/receipt.json"
printf '{"exploratory":true,"initialWeightsIdentical":true,"additionalFittingHistorySeen":true,"trainingOrdersIdentical":false,"optimizerStepsPerModel":98,"reservedFinalStillRequired":true,"automaticPromotion":false}\n' > "$root/coverage-student-training-v1/comparison.json"
printf '0\n' > "$root/coverage-student-training-v1/run.exit"
ln -s "$out/good/augmented" "$root/student-only-benchmark-v1/augmented"
printf '0\n' > "$root/student-only-benchmark-v1/run.exit"
coverage="$project/datasets/visual-control/expanded-rooms-v1/benchmark-coverage-student.sh"
PUPPYBOT_PROJECT="$mock" PUPPYBOT_COVERAGE_BENCHMARK_SCRIPT="$out/benchmark" PUPPYBOT_COVERAGE_BENCHMARK_OUT="$out/coverage" /usr/bin/bash "$coverage" > "$out/coverage.log" 2>&1
/usr/bin/jq -e '.complete and .identicalCases and (.sameTrainingData|not) and (.trainingOrdersIdentical|not) and .baseline.returns==1 and .candidate.returns==1 and (.automaticPromotion|not)' "$out/coverage/comparison.json" > /dev/null
if PUPPYBOT_PROJECT="$mock" PUPPYBOT_TEST_FAULT=1 PUPPYBOT_COVERAGE_BENCHMARK_SCRIPT="$out/benchmark" PUPPYBOT_COVERAGE_BENCHMARK_OUT="$out/coverage-bad" /usr/bin/bash "$coverage" > "$out/coverage-bad.log" 2>&1;then echo 'Unaudited coverage episode was accepted.' >&2;exit 1;fi
[[ "$(< "$out/coverage-bad/run.exit")" == 1 && ! -e "$out/coverage-bad/comparison.json" ]]
mkdir -p "$root/coverage-teacher-training-v1/policy" "$root/coverage-student-benchmark-v1"
printf 'teacher weights\n' > "$root/coverage-teacher-training-v1/policy/weights.bin"
printf '{}\n' > "$root/coverage-teacher-training-v1/policy/receipt.json"
printf '{"exploratory":true,"initialWeightsIdentical":true,"additionalFittingHistorySeen":true,"trainingOrdersIdentical":false,"optimizerStepsPerModel":98,"reservedFinalStillRequired":true,"automaticPromotion":false}\n' > "$root/coverage-teacher-training-v1/comparison.json"
printf '0\n' > "$root/coverage-teacher-training-v1/run.exit"
ln -s "$out/coverage/candidate" "$root/coverage-student-benchmark-v1/candidate"
printf '0\n' > "$root/coverage-student-benchmark-v1/run.exit"
teacher="$project/datasets/visual-control/expanded-rooms-v1/benchmark-coverage-teacher.sh"
PUPPYBOT_PROJECT="$mock" PUPPYBOT_COVERAGE_BENCHMARK_SCRIPT="$out/benchmark" PUPPYBOT_COVERAGE_BENCHMARK_OUT="$out/teacher" /usr/bin/bash "$teacher" > "$out/teacher.log" 2>&1
/usr/bin/jq -e '.complete and .identicalCases and (.sameTrainingData|not) and .baseline.returns==1 and .candidate.returns==1 and (.automaticPromotion|not)' "$out/teacher/comparison.json" > /dev/null
if PUPPYBOT_PROJECT="$mock" PUPPYBOT_TEST_FAULT=1 PUPPYBOT_COVERAGE_BENCHMARK_SCRIPT="$out/benchmark" PUPPYBOT_COVERAGE_BENCHMARK_OUT="$out/teacher-bad" /usr/bin/bash "$teacher" > "$out/teacher-bad.log" 2>&1;then echo 'Unaudited teacher-training episode was accepted.' >&2;exit 1;fi
[[ "$(< "$out/teacher-bad/run.exit")" == 1 && ! -e "$out/teacher-bad/comparison.json" ]]
mkdir -p "$root/focused-coverage-training-v1/policy" "$root/coverage-teacher-benchmark-v1"
printf 'focused weights\n' > "$root/focused-coverage-training-v1/policy/weights.bin"
printf '{}\n' > "$root/focused-coverage-training-v1/policy/receipt.json"
printf '{"exploratory":true,"initialWeightsIdentical":true,"sameTrainingData":true,"focusedHistory":211,"focusCopiesPerEpoch":8,"focusedExposure":7,"otherNewHistorySeen":true,"trainingOrdersIdentical":false,"optimizerStepsPerModel":98,"reservedFinalStillRequired":true,"automaticPromotion":false}\n' > "$root/focused-coverage-training-v1/comparison.json"
printf '0\n' > "$root/focused-coverage-training-v1/run.exit"
ln -s "$out/teacher/candidate" "$root/coverage-teacher-benchmark-v1/candidate"
printf '0\n' > "$root/coverage-teacher-benchmark-v1/run.exit"
focused="$project/datasets/visual-control/expanded-rooms-v1/benchmark-focused-coverage.sh"
PUPPYBOT_PROJECT="$mock" PUPPYBOT_COVERAGE_BENCHMARK_SCRIPT="$out/benchmark" PUPPYBOT_COVERAGE_BENCHMARK_OUT="$out/focused" /usr/bin/bash "$focused" > "$out/focused.log" 2>&1
/usr/bin/jq -e '.complete and .identicalCases and .sameTrainingData and .focusedExposure==7 and .baseline.returns==1 and .candidate.returns==1 and (.automaticPromotion|not)' "$out/focused/comparison.json" > /dev/null
if PUPPYBOT_PROJECT="$mock" PUPPYBOT_TEST_FAULT=1 PUPPYBOT_COVERAGE_BENCHMARK_SCRIPT="$out/benchmark" PUPPYBOT_COVERAGE_BENCHMARK_OUT="$out/focused-bad" /usr/bin/bash "$focused" > "$out/focused-bad.log" 2>&1;then echo 'Unaudited focused-training episode was accepted.' >&2;exit 1;fi
[[ "$(< "$out/focused-bad/run.exit")" == 1 && ! -e "$out/focused-bad/comparison.json" ]]
mkdir -p "$root/coverage-v2-student-training-v1/policy" "$root/coverage-v2-training-pair-v1/augmented-policy" "$root/coverage-v2-training-benchmark-v1"
printf 'student-v2 weights\n' > "$root/coverage-v2-student-training-v1/policy/weights.bin"
printf '{}\n' > "$root/coverage-v2-student-training-v1/policy/receipt.json"
cp "$pair/augmented-policy/weights.bin" "$root/coverage-v2-training-pair-v1/augmented-policy/weights.bin"
printf '{}\n' > "$root/coverage-v2-training-pair-v1/augmented-policy/receipt.json"
printf '{"exploratory":true,"initialWeightsIdentical":true,"additionalFittingHistorySeen":true,"trainingOrdersIdentical":false,"optimizerStepsPerModel":98,"reservedFinalStillRequired":true,"automaticPromotion":false}\n' > "$root/coverage-v2-student-training-v1/comparison.json"
printf '0\n' > "$root/coverage-v2-student-training-v1/run.exit"
ln -s "$out/good/augmented" "$root/coverage-v2-training-benchmark-v1/augmented"
printf '0\n' > "$root/coverage-v2-training-benchmark-v1/run.exit"
student_v2="$project/datasets/visual-control/expanded-rooms-v1/benchmark-coverage-v2-student.sh"
PUPPYBOT_PROJECT="$mock" PUPPYBOT_COVERAGE_BENCHMARK_SCRIPT="$out/benchmark" PUPPYBOT_COVERAGE_BENCHMARK_OUT="$out/student-v2" /usr/bin/bash "$student_v2" > "$out/student-v2.log" 2>&1
/usr/bin/jq -e '.complete and .identicalCases and (.sameTrainingData|not) and .baseline.returns==1 and .candidate.returns==1 and (.automaticPromotion|not)' "$out/student-v2/comparison.json" > /dev/null
if PUPPYBOT_PROJECT="$mock" PUPPYBOT_TEST_FAULT=1 PUPPYBOT_COVERAGE_BENCHMARK_SCRIPT="$out/benchmark" PUPPYBOT_COVERAGE_BENCHMARK_OUT="$out/student-v2-bad" /usr/bin/bash "$student_v2" > "$out/student-v2-bad.log" 2>&1;then echo 'Unaudited revised student episode was accepted.' >&2;exit 1;fi
[[ "$(< "$out/student-v2-bad/run.exit")" == 1 && ! -e "$out/student-v2-bad/comparison.json" ]]
mkdir -p "$root/balanced-phase-screen-v1/policy"
printf 'balanced weights\n' > "$root/balanced-phase-screen-v1/policy/weights.bin"
printf '{}\n' > "$root/balanced-phase-screen-v1/policy/receipt.json"
printf '{"sameTrainingData":true,"initialWeightsIdentical":true,"trainingOrdersIdentical":true,"mirrorMasksIdentical":true,"optimizerStepsPerModel":98,"balancedPhaseLoss":true,"reservedFinalStillRequired":true,"automaticPromotion":false}\n' > "$root/balanced-phase-screen-v1/comparison.json"
printf '0\n' > "$root/balanced-phase-screen-v1/run.exit"
balanced="$project/datasets/visual-control/expanded-rooms-v1/benchmark-balanced-phase.sh"
PUPPYBOT_PROJECT="$mock" PUPPYBOT_BALANCED_PHASE_BENCHMARK_SCRIPT="$out/benchmark" PUPPYBOT_BALANCED_PHASE_BENCHMARK_OUT="$out/balanced" /usr/bin/bash "$balanced" > "$out/balanced.log" 2>&1
/usr/bin/jq -e '.complete and .identicalCases and .sameTrainingData and .balancedPhaseLoss and .baseline.returns==1 and .candidate.returns==1 and (.automaticPromotion|not)' "$out/balanced/comparison.json" > /dev/null
if PUPPYBOT_PROJECT="$mock" PUPPYBOT_TEST_FAULT=1 PUPPYBOT_BALANCED_PHASE_BENCHMARK_SCRIPT="$out/benchmark" PUPPYBOT_BALANCED_PHASE_BENCHMARK_OUT="$out/balanced-bad" /usr/bin/bash "$balanced" > "$out/balanced-bad.log" 2>&1;then echo 'Unaudited balanced-phase episode was accepted.' >&2;exit 1;fi
[[ "$(< "$out/balanced-bad/run.exit")" == 1 && ! -e "$out/balanced-bad/comparison.json" ]]
mkdir -p "$root/return-weight-screen-v1/policy"
printf 'return-weighted weights\n' > "$root/return-weight-screen-v1/policy/weights.bin"
printf '{}\n' > "$root/return-weight-screen-v1/policy/receipt.json"
printf '{"sameTrainingData":true,"initialWeightsIdentical":true,"trainingOrdersIdentical":true,"mirrorMasksIdentical":true,"optimizerStepsPerModel":98,"returnControlWeightMilli":2000,"reservedFinalStillRequired":true,"automaticPromotion":false}\n' > "$root/return-weight-screen-v1/comparison.json"
printf '0\n' > "$root/return-weight-screen-v1/run.exit"
weighted="$project/datasets/visual-control/expanded-rooms-v1/benchmark-return-weight.sh"
PUPPYBOT_PROJECT="$mock" PUPPYBOT_RETURN_WEIGHT_BENCHMARK_SCRIPT="$out/benchmark" PUPPYBOT_RETURN_WEIGHT_BENCHMARK_OUT="$out/weighted" /usr/bin/bash "$weighted" > "$out/weighted.log" 2>&1
/usr/bin/jq -e '.complete and .identicalCases and .sameTrainingData and .returnControlWeightMilli==2000 and .baseline.returns==1 and .candidate.returns==1 and (.automaticPromotion|not)' "$out/weighted/comparison.json" > /dev/null
if PUPPYBOT_PROJECT="$mock" PUPPYBOT_TEST_FAULT=1 PUPPYBOT_RETURN_WEIGHT_BENCHMARK_SCRIPT="$out/benchmark" PUPPYBOT_RETURN_WEIGHT_BENCHMARK_OUT="$out/weighted-bad" /usr/bin/bash "$weighted" > "$out/weighted-bad.log" 2>&1;then echo 'Unaudited return-weighted episode was accepted.' >&2;exit 1;fi
[[ "$(< "$out/weighted-bad/run.exit")" == 1 && ! -e "$out/weighted-bad/comparison.json" ]]
echo 'Synthetic paired benchmark accepts audited rows and rejects a failed audit.'
