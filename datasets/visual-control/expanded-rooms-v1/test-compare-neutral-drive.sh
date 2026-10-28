#!/usr/bin/env bash
# Neutral-drive comparisons require matching data and verified zero rows.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]];mkdir "$out"
PUPPYBOT_PROJECT="$project" bash "$project/datasets/visual-control/expanded-rooms-v1/test-compare-drive-feedback-ablation.sh" "$out/fixture" > /dev/null
mock="$out/fixture/fixture/fixture/fixture/fixture/mock";root="$mock/build/flex/sim/expanded-rooms-v1/large-model-v1";screen="$root/neutral-drive-training-v2"
mkdir -p "$screen/policy";printf 'neutral model\n' > "$screen/policy/weights.bin";sha="$(sha256sum "$screen/policy/weights.bin" | cut -d' ' -f1)"
jq -n --arg sha "$sha" '{weightsSHA256:$sha,dataSHA256:"corpus",memoryWidth:256,driveFeedbackDropMilli:1000,taskFeedback:false}' > "$screen/policy/receipt.json"
printf '0\n' > "$screen/run.exit"
printf '{"sameTrainingData":true,"sameValidationData":true,"trainingOrdersIdentical":true,"firstMirrorMasksIdentical":true,"optimizerStepsPerModel":98,"onlyInitialDriveFeedbackRowsAblated":true,"driveFeedbackDropMilli":1000,"driveFeedbackRowsStayedZero":true,"contactFeedbackPreserved":true,"candidateEpochOneSelected":true,"automaticPromotion":false}\n' > "$screen/comparison.json"
cat > "$out/fake-zero" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${PUPPYBOT_TEST_BAD_ZERO:-0}" == 1 ]];then exit 1;fi
sha="$(sha256sum "$1" | cut -d' ' -f1)";jq -n --arg sha "$sha" '{passed:true,weightsSHA256:$sha,bytesChecked:15360,driveFeedbackValuesZero:5}' > "$2"
EOF
chmod +x "$out/fake-zero"
driver="$project/datasets/visual-control/expanded-rooms-v1/compare-neutral-drive.sh"
export PUPPYBOT_PROJECT="$mock" PUPPYBOT_NEUTRAL_CORPUS_AUDIT="$out/fixture/fixture/incomplete-return-fake-audit" PUPPYBOT_NEUTRAL_BENCHMARK="$out/fixture/fixture/fixture/fixture/fixture/student-fake-benchmark" PUPPYBOT_NEUTRAL_VERIFY_ZERO="$out/fake-zero" PUPPYBOT_NEUTRAL_BENCHMARK_WAIT_RUN="$root/capacity/run"
for scene_set in standard wide-heading;do
    baseline="$root/incomplete-return-standard-comparison-v1/candidate";if [[ "$scene_set" == wide-heading ]];then baseline="$root/incomplete-return-wide-comparison-v1/candidate";fi
    export PUPPYBOT_TEST_BASELINE="$baseline" PUPPYBOT_NEUTRAL_SCENE_SET="$scene_set"
    PUPPYBOT_NEUTRAL_BENCHMARK_OUT="$out/pair-$scene_set" bash "$driver" > "$out/pair-$scene_set.log" 2>&1
    jq -e --arg scene "$scene_set" '.complete and .sceneSet==$scene and .identicalCases and .uniqueStartingPoses==8 and .sameTrainingData and .sameValidationData and .trainingOrdersIdentical and .onlyInitialDriveFeedbackRowsAblated and .driveFeedbackDropMilli==1000 and .driveFeedbackRowsStayedZero and .contactFeedbackPreserved and (.automaticPromotion|not)' "$out/pair-$scene_set/comparison.json" > /dev/null
    for fault in PUPPYBOT_TEST_BAD_ZERO PUPPYBOT_TEST_BAD_CORPUS PUPPYBOT_TEST_BAD_AUDIT PUPPYBOT_TEST_BAD_SCENE;do
        if env "$fault=1" PUPPYBOT_NEUTRAL_BENCHMARK_OUT="$out/$fault-$scene_set" bash "$driver" > "$out/$fault-$scene_set.log" 2>&1;then echo "$fault was accepted for $scene_set." >&2;exit 1;fi
        [[ "$(< "$out/$fault-$scene_set/run.exit")" != 0 && ! -e "$out/$fault-$scene_set/comparison.json" ]]
    done
done
echo 'Neutral-drive comparisons reject nonzero rows and bad corpus, replay or scenes.'
