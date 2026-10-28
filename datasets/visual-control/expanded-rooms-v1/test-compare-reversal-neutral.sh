#!/usr/bin/env bash
# Compare only matching data, scene, replay and initial inputs.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]];mkdir "$out"
PUPPYBOT_PROJECT="$project" bash "$project/datasets/visual-control/expanded-rooms-v1/test-compare-forward-return-pilot.sh" "$out/fixture" > /dev/null
mock="$out/fixture/fixture/fixture/fixture/fixture/fixture/fixture/mock";root="$mock/build/flex/sim/expanded-rooms-v1/large-model-v1";screen="$root/reversal-neutral-training-v1";baseline_policy="$root/forward-return-training-v1/candidate/policy"
mkdir -p "$screen/policy";printf 'reversal model\n' > "$screen/policy/weights.bin";sha="$(sha256sum "$screen/policy/weights.bin" | cut -d' ' -f1)";baseline_sha="$(sha256sum "$baseline_policy/weights.bin" | cut -d' ' -f1)"
jq -n --arg sha "$sha" '{weightsSHA256:$sha,dataSHA256:"new-corpus",seed:203,memoryWidth:256,epochs:1,maxOptimizerSteps:98,reversalPenaltyMilli:1000,driveFeedbackDropMilli:1000,taskFeedback:false}' > "$screen/policy/receipt.json"
printf '0\n' > "$screen/run.exit"
printf '{"sameTrainingData":true,"sameValidationData":true,"initialActorParametersIdentical":true,"firstTrainingOrderIdentical":true,"firstMirrorAndFeedbackMasksIdentical":true,"optimizerStepsPerModel":98,"reversalPenaltyMilli":1000,"reversalLossTrainingOnly":true,"firstGradientChanged":true,"validationObjectiveUnchanged":true,"driveFeedbackDropMilli":1000,"driveFeedbackRowsStayedZero":true,"contactFeedbackPreserved":true,"validationSelectedEpoch":1,"automaticPromotion":false}\n' > "$screen/comparison.json"
for scene_set in standard wide-heading;do
    job="$root/forward-return-standard-comparison-v1";if [[ "$scene_set" == wide-heading ]];then job="$root/forward-return-wide-comparison-v1";fi
    mkdir "$job";printf '0\n' > "$job/run.exit";cp -aL "$out/fixture/pair-$scene_set/candidate" "$job/candidate"
    jq --arg sha "$baseline_sha" '.policyWeightsSHA256=$sha | .rows|=map(.policyWeightsSHA256=$sha)' "$job/candidate/score.json" > "$out/score.tmp";cp "$out/score.tmp" "$job/candidate/score.json"
done
cat > "$out/benchmark" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
cp -aL "$PUPPYBOT_TEST_BASELINE" "$PUPPYBOT_DIVERSE_BENCHMARK_OUT"
sha="$(sha256sum "$PUPPYBOT_DIVERSE_POLICY/weights.bin" | cut -d' ' -f1)"
jq --arg sha "$sha" '.policyWeightsSHA256=$sha | .rows|=map(.policyWeightsSHA256=$sha)' "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.json" > "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.tmp";mv "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.tmp" "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.json"
if [[ "${PUPPYBOT_TEST_BAD_AUDIT:-0}" == 1 ]];then jq '.rows[0].auditPassed=false' "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.json" > "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.tmp";mv "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.tmp" "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.json";fi
if [[ "${PUPPYBOT_TEST_BAD_SCENE:-0}" == 1 ]];then seed=9980000;if [[ "$PUPPYBOT_DIVERSE_SCENE_SET" == wide-heading ]];then seed=9990000;fi;printf 'changed\n' > "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/0/$seed/scene/case.json";fi
EOF
chmod +x "$out/benchmark"
driver="$project/datasets/visual-control/expanded-rooms-v1/compare-reversal-neutral.sh"
export PUPPYBOT_PROJECT="$mock" PUPPYBOT_REVERSAL_NEUTRAL_CORPUS_AUDIT="$out/fixture/audit" PUPPYBOT_REVERSAL_NEUTRAL_BENCHMARK="$out/benchmark" PUPPYBOT_REVERSAL_NEUTRAL_VERIFY_ZERO="$out/fixture/fixture/fake-zero" PUPPYBOT_REVERSAL_NEUTRAL_INPUT_AUDIT="$out/fixture/input-audit" PUPPYBOT_REVERSAL_NEUTRAL_BENCHMARK_WAIT_RUN="$root/capacity/run"
for scene_set in standard wide-heading;do
    job="$root/forward-return-standard-comparison-v1";if [[ "$scene_set" == wide-heading ]];then job="$root/forward-return-wide-comparison-v1";fi
    export PUPPYBOT_TEST_BASELINE="$job/candidate" PUPPYBOT_REVERSAL_NEUTRAL_SCENE_SET="$scene_set"
    PUPPYBOT_REVERSAL_NEUTRAL_BENCHMARK_OUT="$out/pair-$scene_set" bash "$driver" > "$out/pair-$scene_set.log" 2>&1
    jq -e --arg scene "$scene_set" '.complete and .sceneSet==$scene and .identicalCases and .identicalInitialCameraAndOwnFeedback and .sameTrainingData and .sameValidationData and .firstTrainingOrderIdentical and .optimizerStepsPerModel==98 and .reversalPenaltyMilli==1000 and .reversalLossTrainingOnly and .validationObjectiveUnchanged and (.automaticPromotion|not)' "$out/pair-$scene_set/comparison.json" > /dev/null
    for fault in PUPPYBOT_TEST_BAD_CORPUS PUPPYBOT_TEST_BAD_AUDIT PUPPYBOT_TEST_BAD_SCENE PUPPYBOT_TEST_BAD_INPUT;do
        if env "$fault=1" PUPPYBOT_REVERSAL_NEUTRAL_BENCHMARK_OUT="$out/$fault-$scene_set" bash "$driver" > "$out/$fault-$scene_set.log" 2>&1;then echo "$fault was accepted for $scene_set." >&2;exit 1;fi
        [[ "$(< "$out/$fault-$scene_set/run.exit")" != 0 && ! -e "$out/$fault-$scene_set/comparison.json" ]]
    done
done
echo 'Reversal comparisons reject corpus, replay, scene and initial-input mismatches.'
