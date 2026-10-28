#!/usr/bin/env bash
# Synthetic episodes exercise the benchmark and its scene and audit guards.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]]
PUPPYBOT_PROJECT="$project" bash "$project/datasets/visual-control/expanded-rooms-v1/test-diverse-development.sh" "$out" > /dev/null
mock="$out/mock";base="$mock/build/flex/sim/expanded-rooms-v1";root="$base/large-model-v1";runtime="$root/phase-large-tests-v1/runtime"
ln -s "$out/good" "$root/diverse-development-v1"
mkdir -p "$root/student-only-admission-v1/expanded" "$root/coverage-v2-student-admission-v1/expanded" "$root/runtime" "$root/capacity" "$runtime/build/flex/control" "$out/policy" "$base/unseen-benchmark-v2/native-path"
printf 'old data\n' > "$root/student-only-admission-v1/expanded/data.bin";printf 'new data\n' > "$root/coverage-v2-student-admission-v1/expanded/data.bin"
printf 'weights\n' > "$out/policy/weights.bin";printf 'actor\n' > "$out/policy/policy"
sha="$(sha256sum "$out/policy/weights.bin" | cut -d' ' -f1)";data_sha="$(sha256sum "$root/student-only-admission-v1/expanded/data.bin" | cut -d' ' -f1)"
jq -n --arg sha "$sha" --arg data "$data_sha" '{weightsSHA256:$sha,dataSHA256:$data,memoryWidth:256,taskFeedback:false}' > "$out/policy/receipt.json"
printf '0\n' > "$root/capacity/run.exit";printf 'simulator\n' > "$runtime/build/flex/control/simulator"
cat > "$runtime/build/flex/control/control" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
command="$1";shift
while (( $# ));do case "$1" in --scene) scene="$2";shift 2;; --output) output="$2";shift 2;; --seed) seed="$2";shift 2;; --run|--policy|--episodes|--horizon) shift 2;; *) shift;; esac;done
if [[ "$command" == run ]];then
    mkdir -p "$output/$seed/scene" "$output/policy";cp "$scene/case.json" "$output/$seed/scene/case.json";cp "$scene/environment.bin" "$output/$seed/scene/environment.bin"
    if [[ "${PUPPYBOT_TEST_BAD_SCENE:-0}" == 1 ]];then printf 'changed\n' > "$output/$seed/scene/case.json";fi
    jq '{pose:.startPose}' "$scene/layout.json" > "$output/$seed/initial.json"
    if [[ "${PUPPYBOT_TEST_BAD_POSE:-0}" == 1 ]];then jq '.pose[0]+=1' "$output/$seed/initial.json" > "$output/initial.tmp";cp "$output/initial.tmp" "$output/$seed/initial.json";fi
    printf '{"state":{"case":{"passed":false}}}\n' > "$output/$seed/decisions.jsonl"
    jq -n --arg sha "$PUPPYBOT_TEST_POLICY_SHA" --argjson seed "$seed" '{complete:true,episodes:1,rows:[{seed:$seed,steps:1,policyWeightsSHA256:$sha,maximumBrickDistanceM:0.35,suppliedMap:false,taskEventHint:false,found:false,leftStartRoom:false,simulationSeconds:65.9}]}' > "$output/summary.json"
else
    [[ "$command" == verify ]];mkdir "$output"
    jq -n --arg sha "$PUPPYBOT_TEST_POLICY_SHA" --argjson passed "$([[ "${PUPPYBOT_TEST_BAD_AUDIT:-0}" == 1 ]] && printf false || printf true)" '{passed:$passed,commandReplayMaxAbsError:0,modelCommandsReplayed:1,PNGAndActorFramesMatched:2,weightsSHA256:$sha,returnPoseChecked:true,taskEventHintAbsent:true}' > "$output/result.json"
fi
EOF
cat > "$root/runtime/measure-brick-distance" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
mkdir "$2";sha="$(sha256sum "$1/decisions.jsonl" | cut -d' ' -f1)"
jq -n --arg sha "$sha" '{decisionsSHA256:$sha,evaluationOnly:true,referencePositionsEnteredActor:false,consumed:false,closestPlanarBaseToBrickM:1}' > "$2/result.json"
EOF
chmod +x "$runtime/build/flex/control/control" "$root/runtime/measure-brick-distance"
driver="$project/datasets/visual-control/expanded-rooms-v1/benchmark-diverse-development.sh"
export PUPPYBOT_PROJECT="$mock" PUPPYBOT_TEST_POLICY_SHA="$sha" PUPPYBOT_DIVERSE_POLICY="$out/policy" PUPPYBOT_DIVERSE_WAIT_RUN="$root/capacity/run"
PUPPYBOT_DIVERSE_BENCHMARK_OUT="$out/benchmark" bash "$driver" > "$out/benchmark.log" 2>&1
jq -e '.passed and .developmentOnly and .episodes==8 and .auditedEpisodes==8 and .uniqueStartingPoses==8 and .approaches==0 and .returns==0 and (.automaticPromotion|not)' "$out/benchmark/score.json" > /dev/null
for fault in PUPPYBOT_TEST_BAD_SCENE PUPPYBOT_TEST_BAD_POSE PUPPYBOT_TEST_BAD_AUDIT;do
    if env "$fault=1" PUPPYBOT_DIVERSE_BENCHMARK_OUT="$out/$fault" bash "$driver" > "$out/$fault.log" 2>&1;then echo "$fault was accepted." >&2;exit 1;fi
    [[ "$(< "$out/$fault/run.exit")" != 0 && ! -e "$out/$fault/score.json" ]]
done
echo 'Distinct-start benchmark rejects changed scenes, starting poses and audits.'
