#!/usr/bin/env bash
# Synthetic comparison must reject failed audits and changed scenes.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]];mkdir "$out"
PUPPYBOT_PROJECT="$project" bash "$project/datasets/visual-control/expanded-rooms-v1/test-coverage-return-benchmark.sh" "$out/paired" > "$out/paired.log" 2>&1
mock="$out/paired/mock";root="$mock/build/flex/sim/expanded-rooms-v1/large-model-v1";screen="$root/longer-316-screen-v1";previous="$root/coverage-v2-student-benchmark-v1"
mkdir -p "$screen/policy" "$previous" "$root/coverage-v2-student-training-v1/policy" "$root/capacity"
printf '0\n' > "$root/capacity/run.exit"
cp "$root/coverage-return-pair-v1/augmented-policy/weights.bin" "$root/coverage-v2-student-training-v1/policy/weights.bin";printf '{}\n' > "$root/coverage-v2-student-training-v1/policy/receipt.json"
printf 'candidate weights\n' > "$screen/policy/weights.bin";printf '{}\n' > "$screen/policy/receipt.json"
printf '{"sameTrainingData":true,"initialWeightsIdentical":true,"firstTrainingOrderIdentical":true,"firstOptimizerUpdateIdentical":true,"baselineOptimizerSteps":98,"candidateOptimizerSteps":1110,"validationCheckpointSelectionCanDiffer":true,"reservedFinalStillRequired":true,"automaticPromotion":false}\n' > "$screen/comparison.json"
printf '0\n' > "$screen/run.exit";printf '0\n' > "$previous/run.exit";ln -s "$out/paired/good/augmented" "$previous/candidate"
driver="$project/datasets/visual-control/expanded-rooms-v1/benchmark-longer-316.sh"
PUPPYBOT_PROJECT="$mock" PUPPYBOT_LONGER_316_BENCHMARK_WAIT_RUN="$root/capacity/run" PUPPYBOT_LONGER_316_BENCHMARK_SCRIPT="$out/paired/benchmark" PUPPYBOT_LONGER_316_BENCHMARK_OUT="$out/good" bash "$driver" > "$out/good.log" 2>&1
jq -e '.complete and .identicalCases and .sameTrainingData and .firstOptimizerUpdateIdentical and .baselineOptimizerSteps==98 and .candidateOptimizerSteps==1110 and .baseline.returns==1 and .candidate.returns==1 and (.automaticPromotion|not)' "$out/good/comparison.json" > /dev/null
if PUPPYBOT_PROJECT="$mock" PUPPYBOT_TEST_FAULT=1 PUPPYBOT_LONGER_316_BENCHMARK_WAIT_RUN="$root/capacity/run" PUPPYBOT_LONGER_316_BENCHMARK_SCRIPT="$out/paired/benchmark" PUPPYBOT_LONGER_316_BENCHMARK_OUT="$out/bad-audit" bash "$driver" > "$out/bad-audit.log" 2>&1;then echo 'Unaudited episode was accepted.' >&2;exit 1;fi
[[ "$(< "$out/bad-audit/run.exit")" != 0 && ! -e "$out/bad-audit/comparison.json" ]]
sed 's|"$root" == \*/augmented|"$root" == */candidate|' "$out/paired/benchmark" > "$out/tamper-benchmark"
if PUPPYBOT_PROJECT="$mock" PUPPYBOT_TEST_SCENE_MISMATCH=1 PUPPYBOT_LONGER_316_BENCHMARK_WAIT_RUN="$root/capacity/run" PUPPYBOT_LONGER_316_BENCHMARK_SCRIPT="$out/tamper-benchmark" PUPPYBOT_LONGER_316_BENCHMARK_OUT="$out/bad-scene" bash "$driver" > "$out/bad-scene.log" 2>&1;then echo 'Mismatched scene was accepted.' >&2;exit 1;fi
[[ "$(< "$out/bad-scene/run.exit")" != 0 && ! -e "$out/bad-scene/comparison.json" ]]
echo 'Longer-training benchmark rejects failed audits and mismatched scenes.'
