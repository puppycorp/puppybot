#!/usr/bin/env bash
# Verify the cached-baseline comparison rejects bad audits and scene changes.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(/usr/bin/realpath -m "${1:?New output directory required}")"
[[ ! -e "$out" ]];mkdir "$out"
PUPPYBOT_PROJECT="$project" bash "$project/datasets/visual-control/expanded-rooms-v1/test-coverage-return-benchmark.sh" "$out/paired" > "$out/paired.log" 2>&1
mock="$out/paired/mock";root="$mock/build/flex/sim/expanded-rooms-v1/large-model-v1"
screen="$root/feedback-drop-screen-v1";previous="$root/student-only-benchmark-v1"
mkdir -p "$screen/policy" "$previous" "$root/student-only-training-v1/policy" "$root/long-return-cohort-v1"
mkdir -p "$root/phase-large-tests-v1/runtime/build/flex/control" "$root/workspace/build/flex/control"
printf 'simulator\n' > "$root/workspace/build/flex/control/simulator";cp "$root/workspace/build/flex/control/simulator" "$root/phase-large-tests-v1/runtime/build/flex/control/simulator";printf 'control\n' > "$root/phase-large-tests-v1/runtime/build/flex/control/control"
printf '0\n' > "$root/long-return-cohort-v1/run.exit"
cp "$root/coverage-return-pair-v1/augmented-policy/weights.bin" "$root/student-only-training-v1/policy/weights.bin"
printf '{}\n' > "$root/student-only-training-v1/policy/receipt.json"
printf 'candidate weights\n' > "$screen/policy/weights.bin";printf '{}\n' > "$screen/policy/receipt.json"
printf '{"sameTrainingData":true,"initialWeightsIdentical":true,"trainingOrdersIdentical":true,"firstMirrorMasksIdentical":true,"optimizerStepsPerModel":98,"driveFeedbackDropMilli":250,"reservedFinalStillRequired":true,"automaticPromotion":false}\n' > "$screen/comparison.json"
printf '0\n' > "$screen/run.exit";printf '0\n' > "$previous/run.exit"
ln -s "$out/paired/good/augmented" "$previous/augmented"
driver="$project/datasets/visual-control/expanded-rooms-v1/benchmark-feedback-drop-screen.sh"
PUPPYBOT_PROJECT="$mock" PUPPYBOT_FEEDBACK_DROP_BENCHMARK_SCRIPT="$out/paired/benchmark" PUPPYBOT_FEEDBACK_DROP_BENCHMARK_OUT="$out/good" bash "$driver" > "$out/good.log" 2>&1
jq -e '.complete and .identicalCases and .sameTrainingData and .driveFeedbackDropMilli==250 and .baseline.returns==1 and .candidate.returns==1 and (.automaticPromotion|not)' "$out/good/comparison.json" > /dev/null
if PUPPYBOT_PROJECT="$mock" PUPPYBOT_TEST_FAULT=1 PUPPYBOT_FEEDBACK_DROP_BENCHMARK_SCRIPT="$out/paired/benchmark" PUPPYBOT_FEEDBACK_DROP_BENCHMARK_OUT="$out/bad-audit" bash "$driver" > "$out/bad-audit.log" 2>&1;then echo 'Unaudited episode was accepted.' >&2;exit 1;fi
[[ "$(< "$out/bad-audit/run.exit")" != 0 && ! -e "$out/bad-audit/comparison.json" ]]
# The mock tampers only augmented scenes; make it apply to candidate scenes too.
sed 's|"$root" == \*/augmented|"$root" == */candidate|' "$out/paired/benchmark" > "$out/tamper-benchmark"
if PUPPYBOT_PROJECT="$mock" PUPPYBOT_TEST_SCENE_MISMATCH=1 PUPPYBOT_FEEDBACK_DROP_BENCHMARK_SCRIPT="$out/tamper-benchmark" PUPPYBOT_FEEDBACK_DROP_BENCHMARK_OUT="$out/bad-scene" bash "$driver" > "$out/bad-scene.log" 2>&1;then echo 'Mismatched scene was accepted.' >&2;exit 1;fi
[[ "$(< "$out/bad-scene/run.exit")" != 0 && ! -e "$out/bad-scene/comparison.json" ]]
printf 'different simulator\n' > "$root/phase-large-tests-v1/runtime/build/flex/control/simulator"
if PUPPYBOT_PROJECT="$mock" PUPPYBOT_FEEDBACK_DROP_BENCHMARK_SCRIPT="$out/paired/benchmark" PUPPYBOT_FEEDBACK_DROP_BENCHMARK_OUT="$out/bad-simulator" bash "$driver" > "$out/bad-simulator.log" 2>&1;then echo 'Mismatched simulator was accepted.' >&2;exit 1;fi
[[ "$(< "$out/bad-simulator/run.exit")" != 0 && ! -e "$out/bad-simulator/comparison.json" ]]
echo 'Feedback-drop benchmark rejects failed audits and mismatched scenes.'
