#!/usr/bin/env bash
# The policy comparison requires disjoint corpora and matching recorded starts.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]];mkdir "$out"
PUPPYBOT_PROJECT="$project" bash "$project/datasets/visual-control/expanded-rooms-v1/test-compare-neutral-drive.sh" "$out/fixture" > /dev/null
mock="$out/fixture/fixture/fixture/fixture/fixture/fixture/mock";root="$mock/build/flex/sim/expanded-rooms-v1/large-model-v1";training="$root/forward-return-training-v1";admission="$root/forward-return-admission-v1"
mkdir -p "$training" "$admission/known/expanded";printf '0\n' > "$training/run.exit";printf '0\n' > "$admission/run.exit"
printf '{"passed":true,"episodes":358,"reusedScenesSameSplit":true,"existingDataBytePreserved":true,"newHistoriesIndependentlyAudited":true,"actorInputsUnchanged":true,"automaticPromotion":false}\n' > "$admission/coverage.json"
printf '{"sameInitialActorParameters":true,"sameSeed":true,"seed":203,"optimizerStepsPerModel":98,"trainingDataDiffer":true,"validationDataDiffer":true,"bothNewFittingHistoriesSampled":true,"driveFeedbackDropMilli":1000,"driveFeedbackRowsStayedZero":true,"contactFeedbackPreserved":true,"automaticPromotion":false}\n' > "$training/comparison.json"
for kind in baseline candidate;do
    mkdir -p "$training/$kind/policy";printf '%s weights\n' "$kind" > "$training/$kind/policy/weights.bin";sha="$(sha256sum "$training/$kind/policy/weights.bin" | cut -d' ' -f1)";data=corpus;if [[ "$kind" == candidate ]];then data=new-corpus;fi
    jq -n --arg sha "$sha" --arg data "$data" '{weightsSHA256:$sha,dataSHA256:$data,seed:203,memoryWidth:256,driveFeedbackDropMilli:1000,taskFeedback:false}' > "$training/$kind/policy/receipt.json"
done
cat > "$out/audit" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
mkdir "$3";sha=corpus;count=354;if [[ "$2" == */expanded-corpus ]];then sha=new-corpus;count=358;fi
if [[ "${PUPPYBOT_TEST_BAD_CORPUS:-0}" == 1 ]];then sha=wrong;fi
jq -n --arg sha "$sha" --argjson count "$count" '{passed:true,dataSHA256:$sha,corpusHistories:$count,episodes:8,exactCaseAndEnvironmentFilesDisjoint:true,reservedFinalUntouched:true}' > "$3/summary.json"
EOF
cat > "$out/benchmark" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
cp -aL "$PUPPYBOT_TEST_BASELINE" "$PUPPYBOT_DIVERSE_BENCHMARK_OUT"
sha="$(sha256sum "$PUPPYBOT_DIVERSE_POLICY/weights.bin" | cut -d' ' -f1)"
jq --arg sha "$sha" '.policyWeightsSHA256=$sha | .rows|=map(.policyWeightsSHA256=$sha)' "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.json" > "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.tmp";mv "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.tmp" "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.json"
if [[ "$PUPPYBOT_DIVERSE_POLICY" == */candidate/policy && "${PUPPYBOT_TEST_BAD_AUDIT:-0}" == 1 ]];then jq '.rows[0].auditPassed=false' "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.json" > "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.tmp";mv "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.tmp" "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/score.json";fi
if [[ "$PUPPYBOT_DIVERSE_POLICY" == */candidate/policy && "${PUPPYBOT_TEST_BAD_SCENE:-0}" == 1 ]];then seed=9980000;if [[ "$PUPPYBOT_DIVERSE_SCENE_SET" == wide-heading ]];then seed=9990000;fi;printf 'changed\n' > "$PUPPYBOT_DIVERSE_BENCHMARK_OUT/0/$seed/scene/case.json";fi
EOF
cat > "$out/input-audit" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
mkdir "$3";if [[ "${PUPPYBOT_TEST_BAD_INPUT:-0}" == 1 ]];then exit 1;fi
printf '{"passed":true,"episodes":8,"sceneFilesIdentical":true,"initialActorImagesAndFeedbackIdentical":true,"policyReplaysPassed":true}\n' > "$3/summary.json"
EOF
chmod +x "$out/audit" "$out/benchmark" "$out/input-audit"
driver="$project/datasets/visual-control/expanded-rooms-v1/compare-forward-return-pilot.sh"
export PUPPYBOT_PROJECT="$mock" PUPPYBOT_FORWARD_RETURN_CORPUS_AUDIT="$out/audit" PUPPYBOT_FORWARD_RETURN_BENCHMARK="$out/benchmark" PUPPYBOT_FORWARD_RETURN_INPUT_AUDIT="$out/input-audit" PUPPYBOT_FORWARD_RETURN_BENCHMARK_WAIT_RUN="$root/capacity/run"
for scene_set in standard wide-heading;do
    export PUPPYBOT_TEST_BASELINE="$out/fixture/pair-$scene_set/candidate" PUPPYBOT_FORWARD_RETURN_SCENE_SET="$scene_set"
    PUPPYBOT_FORWARD_RETURN_BENCHMARK_OUT="$out/pair-$scene_set" bash "$driver" > "$out/pair-$scene_set.log" 2>&1
    jq -e --arg scene "$scene_set" '.complete and .sceneSet==$scene and .identicalCases and .identicalInitialCameraAndOwnFeedback and .uniqueStartingPoses==8 and .trainingDataDiffer and .validationDataDiffer and .bothNewFittingHistoriesSampled and (.automaticPromotion|not)' "$out/pair-$scene_set/comparison.json" > /dev/null
    for fault in PUPPYBOT_TEST_BAD_CORPUS PUPPYBOT_TEST_BAD_AUDIT PUPPYBOT_TEST_BAD_SCENE PUPPYBOT_TEST_BAD_INPUT;do
        if env "$fault=1" PUPPYBOT_FORWARD_RETURN_BENCHMARK_OUT="$out/$fault-$scene_set" bash "$driver" > "$out/$fault-$scene_set.log" 2>&1;then echo "$fault was accepted for $scene_set." >&2;exit 1;fi
        [[ "$(< "$out/$fault-$scene_set/run.exit")" != 0 && ! -e "$out/$fault-$scene_set/comparison.json" ]]
    done
done
echo 'Forward-return policy comparisons reject corpus, replay, scene and initial-input mismatches.'
