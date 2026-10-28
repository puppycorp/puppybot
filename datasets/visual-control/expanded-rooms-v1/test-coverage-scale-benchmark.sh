#!/usr/bin/env bash
# Synthetic 32-case comparison rejects bad audits, scenes and simulator builds.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]];mkdir "$out"
PUPPYBOT_PROJECT="$project" bash "$project/datasets/visual-control/expanded-rooms-v1/test-contact-weight-benchmark.sh" "$out/fixture" > "$out/fixture.log" 2>&1
mock="$out/fixture/paired/mock";root="$mock/build/flex/sim/expanded-rooms-v1/large-model-v1";screen="$root/coverage-scale-training-v1";runtime="$root/phase-large-tests-v1/runtime"
cp "$root/workspace/build/flex/control/simulator" "$runtime/build/flex/control/simulator"
mkdir -p "$screen/policy" "$root/capacity";printf '0\n' > "$root/capacity/run.exit";printf '0\n' > "$screen/run.exit"
printf 'scaled weights\n' > "$screen/policy/weights.bin";printf '{}\n' > "$screen/policy/receipt.json"
printf '{"initialWeightsIdentical":true,"differentTrainingData":true,"optimizerStepsPerModel":98,"addedFittingHistoriesSeen":4,"trainingOrdersIdentical":false,"validationSetsDiffer":true,"shuffleAndCheckpointSelectionLimitCausalInterpretation":true,"reservedFinalStillRequired":true,"automaticPromotion":false}\n' > "$screen/comparison.json"
benchmark="$out/fixture/paired/benchmark";driver="$project/datasets/visual-control/expanded-rooms-v1/benchmark-coverage-scale.sh"
export PUPPYBOT_PROJECT="$mock" PUPPYBOT_SCALE_BENCHMARK_SCRIPT="$benchmark" PUPPYBOT_SCALE_BENCHMARK_WAIT_RUN="$root/capacity/run"
PUPPYBOT_SCALE_BENCHMARK_OUT="$out/good" bash "$driver" > "$out/good.log" 2>&1
jq -e '.complete and .identicalCases and .differentTrainingData and .initialWeightsIdentical and .addedFittingHistoriesSeen==4 and .validationSetsDiffer and .shuffleAndCheckpointSelectionLimitCausalInterpretation and (.automaticPromotion|not)' "$out/good/comparison.json" > /dev/null
if PUPPYBOT_TEST_FAULT=1 PUPPYBOT_SCALE_BENCHMARK_OUT="$out/bad-audit" bash "$driver" > "$out/bad-audit.log" 2>&1;then echo 'Failed replay audit was accepted.' >&2;exit 1;fi
[[ "$(< "$out/bad-audit/run.exit")" != 0 && ! -e "$out/bad-audit/comparison.json" ]]
sed 's|"$root" == \*/augmented|"$root" == */candidate|' "$benchmark" > "$out/tamper-benchmark"
if PUPPYBOT_TEST_SCENE_MISMATCH=1 PUPPYBOT_SCALE_BENCHMARK_SCRIPT="$out/tamper-benchmark" PUPPYBOT_SCALE_BENCHMARK_OUT="$out/bad-scene" bash "$driver" > "$out/bad-scene.log" 2>&1;then echo 'Changed scene was accepted.' >&2;exit 1;fi
[[ "$(< "$out/bad-scene/run.exit")" != 0 && ! -e "$out/bad-scene/comparison.json" ]]
printf 'changed simulator\n' > "$runtime/build/flex/control/simulator"
if PUPPYBOT_SCALE_BENCHMARK_OUT="$out/bad-simulator" bash "$driver" > "$out/bad-simulator.log" 2>&1;then echo 'Changed simulator was accepted.' >&2;exit 1;fi
[[ "$(< "$out/bad-simulator/run.exit")" != 0 && ! -e "$out/bad-simulator/comparison.json" ]]
echo 'Scaled benchmark rejects failed audits and changed scenes or simulator.'
