#!/usr/bin/env bash
# Synthetic control-flow test: no simulator or reserved layout is used.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(/usr/bin/realpath -m "${1:?New output directory required}")"
[[ ! -e "$out" ]]
mock="$out/mock"
pair="$mock/build/flex/sim/expanded-rooms-v1/large-model-v1/coverage-return-pair-v1"
mkdir -p "$pair/baseline-policy" "$pair/augmented-policy"
printf '0\n' > "$pair/run.exit"
capacity="$mock/build/flex/sim/expanded-rooms-v1/large-model-v1/return-weight-benchmark-queue-v1";mkdir "$capacity";printf '0\n' > "$capacity/run.exit"
printf '{"exploratory":true,"optimizerStepsPerModel":109,"initialWeightsIdentical":true,"additionalFittingHistorySeen":true,"trainingOrdersIdentical":false,"reservedFinalStillRequired":true,"automaticPromotion":false}\n' > "$pair/comparison.json"
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
if [[ "${PUPPYBOT_TEST_SCENE_MISMATCH:-0}" == 1 && "$root" == */augmented ]];then printf 'changed\n' > "$root/0/9960000/scene/case.json";fi
/usr/bin/jq -n --arg sha "$sha" --argjson count "$count" --argjson fault "${PUPPYBOT_TEST_FAULT:-0}" '{episodes:32,completedRecordings:32,auditedEpisodes:32,approaches:$count,returns:$count,openReturns:$count,hiddenReturns:0,meanClosestM:1,meanSuccessfulSimulationSeconds:null,rows:[range(0;32)|{caseIndex:.,layoutId:(18+(./16|floor)),seed:(9960000+.),recordingCompleted:true,auditPassed:(if .==0 and $fault==1 then false else true end),policyWeightsSHA256:$sha,maximumBrickDistanceM:0.35,suppliedMap:false,taskEventHint:false,found:(.==0 and $count==1),physicalReturned:(.==0 and $count==1)}]}' > "$root/score.json"
printf '0\n' > "$root/run.exit"
EOF
driver="$project/datasets/visual-control/expanded-rooms-v1/benchmark-coverage-return-pair.sh"
PUPPYBOT_PROJECT="$mock" PUPPYBOT_COVERAGE_RETURN_BENCHMARK_SCRIPT="$out/benchmark" PUPPYBOT_COVERAGE_RETURN_BENCHMARK_OUT="$out/good" /usr/bin/bash "$driver" > "$out/good.log" 2>&1
/usr/bin/jq -e '.complete and .identicalCases and .gainedApproaches==1 and .gainedReturns==1 and (.automaticPromotion|not)' "$out/good/comparison.json" > /dev/null
if PUPPYBOT_PROJECT="$mock" PUPPYBOT_TEST_FAULT=1 PUPPYBOT_COVERAGE_RETURN_BENCHMARK_SCRIPT="$out/benchmark" PUPPYBOT_COVERAGE_RETURN_BENCHMARK_OUT="$out/bad-audit" /usr/bin/bash "$driver" > "$out/bad-audit.log" 2>&1;then echo 'Unaudited episode was accepted.' >&2;exit 1;fi
[[ "$(< "$out/bad-audit/run.exit")" == 1 && ! -e "$out/bad-audit/comparison.json" ]]
if PUPPYBOT_PROJECT="$mock" PUPPYBOT_TEST_SCENE_MISMATCH=1 PUPPYBOT_COVERAGE_RETURN_BENCHMARK_SCRIPT="$out/benchmark" PUPPYBOT_COVERAGE_RETURN_BENCHMARK_OUT="$out/bad-scene" /usr/bin/bash "$driver" > "$out/bad-scene.log" 2>&1;then echo 'Mismatched scenes were accepted.' >&2;exit 1;fi
[[ "$(< "$out/bad-scene/run.exit")" != 0 && ! -e "$out/bad-scene/comparison.json" ]]
echo 'Return comparison accepts verified scenes and rejects failed audits or changed scenes.'
