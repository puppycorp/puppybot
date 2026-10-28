#!/usr/bin/env bash
# Exercise audit and overlap rejection using small synthetic benchmark records.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]]
mock="$out/mock";base="$mock/build/flex/sim/expanded-rooms-v1";root="$base/large-model-v1"
runtime="$root/phase-large-tests-v1/runtime";baseline="$root/student-only-benchmark-v1/augmented";data="$root/coverage-v2-student-admission-v1/expanded";scenes="$base/unseen-benchmark-v2/scenes";policy="$out/policy"
mkdir -p "$runtime/build/flex/control" "$root/workspace/build/flex/control" "$root/runtime" "$baseline" "$data" "$scenes" "$policy/kernels" "$base/unseen-benchmark-v2/native-path"
printf '0\n' > "$root/student-only-benchmark-v1/run.exit";printf '{"passed":true,"episodes":316,"newHistoriesIndependentlyAudited":true,"existingDataBytePreserved":true}\n' > "$root/coverage-v2-student-admission-v1/coverage.json"
printf '{"episodes":32,"completedRecordings":32,"auditedEpisodes":32,"approaches":5,"returns":0,"rows":[]}\n' > "$baseline/score.json"
printf 'weights\n' > "$policy/weights.bin";printf 'binary\n' > "$policy/policy";printf 'kernel\n' > "$policy/kernels/test"
sha="$(sha256sum "$policy/weights.bin" | cut -d' ' -f1)";binary="$(sha256sum "$policy/policy" | cut -d' ' -f1)"
jq -n --arg sha "$sha" --arg binary "$binary" '{weightsSHA256:$sha,binarySHA256:$binary,memoryWidth:128,memoryPoseAuxiliary:true,taskFeedback:false}' > "$policy/receipt.json"
printf 'simulator\n' > "$runtime/build/flex/control/simulator";cp "$runtime/build/flex/control/simulator" "$root/workspace/build/flex/control/simulator"
for ((i=0;i<316;i++));do mkdir -p "$data/expert-$i/scene";printf 'training-case-%s\n' "$i" > "$data/expert-$i/scene/case.json";printf 'training-environment-%s\n' "$i" > "$data/expert-$i/scene/environment.bin";done
for layout in 18 19;do for scene in {0..15};do
    index=$(((layout-18)*16+scene));seed=$((9960000+index));mkdir -p "$scenes/$layout/$scene" "$baseline/$index/$seed/scene"
    for file in case.json environment.bin;do printf 'development-%s-%s-%s\n' "$layout" "$scene" "$file" > "$scenes/$layout/$scene/$file";cp "$scenes/$layout/$scene/$file" "$baseline/$index/$seed/scene/$file";done
done;done
cat > "$runtime/build/flex/control/control" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
command="$1";shift
while (( $# ));do case "$1" in --policy) policy="$2";shift 2;; --scene) scene="$2";shift 2;; --output) output="$2";shift 2;; --seed) seed="$2";shift 2;; --run|--episodes|--horizon) shift 2;; *) shift;; esac;done
sha="$(sha256sum "$policy/weights.bin" | cut -d' ' -f1)"
if [[ "$command" == run ]];then
    mkdir -p "$output/$seed";cp -a "$scene" "$output/$seed/scene";ln -s "$policy" "$output/policy"
    printf '{"state":{"case":{"passed":false}}}\n' > "$output/$seed/decisions.jsonl"
    jq -n --arg sha "$sha" --argjson seed "$seed" '{complete:true,episodes:1,rows:[{seed:$seed,policyWeightsSHA256:$sha,maximumBrickDistanceM:0.35,suppliedMap:false,taskEventHint:false,found:false,simulationSeconds:60}]}' > "$output/summary.json"
elif [[ "$command" == verify ]];then
    mkdir "$output";passed=true;if [[ "${PUPPYBOT_TEST_BAD_AUDIT:-0}" == 1 ]];then passed=false;fi
    jq -n --arg sha "$sha" --argjson passed "$passed" '{passed:$passed,commandReplayMaxAbsError:0,weightsSHA256:$sha}' > "$output/result.json"
else exit 1;fi
EOF
cat > "$root/runtime/measure-brick-distance" <<'EOF'
#!/usr/bin/env bash
mkdir "$2";printf '{"closestPlanarBaseToBrickM":1.25}\n' > "$2/result.json"
EOF
chmod +x "$runtime/build/flex/control/control" "$root/runtime/measure-brick-distance"
driver="$project/datasets/visual-control/expanded-rooms-v1/benchmark-small-pose.sh"
PUPPYBOT_PROJECT="$mock" PUPPYBOT_SMALL_POSE_POLICY="$policy" PUPPYBOT_SMALL_POSE_BENCHMARK_OUT="$out/good" bash "$driver" > "$out/good.log" 2>&1
jq -e '.complete and .identicalSceneBytesChecked and .noExactTrainingSceneFileOverlap and .smallerPoseModel.episodes==32 and .smallerPoseModel.auditedEpisodes==32 and (.automaticPromotion|not)' "$out/good/comparison.json" > /dev/null
cp "$data/expert-0/scene/case.json" "$scenes/18/0/case.json"
if PUPPYBOT_PROJECT="$mock" PUPPYBOT_SMALL_POSE_POLICY="$policy" PUPPYBOT_SMALL_POSE_BENCHMARK_OUT="$out/bad-overlap" bash "$driver" > "$out/bad-overlap.log" 2>&1;then echo 'Training overlap was accepted.' >&2;exit 1;fi
[[ "$(< "$out/bad-overlap/run.exit")" != 0 && ! -e "$out/bad-overlap/comparison.json" ]]
cp "$baseline/0/9960000/scene/case.json" "$scenes/18/0/case.json"
if PUPPYBOT_TEST_BAD_AUDIT=1 PUPPYBOT_PROJECT="$mock" PUPPYBOT_SMALL_POSE_POLICY="$policy" PUPPYBOT_SMALL_POSE_BENCHMARK_OUT="$out/bad-audit" bash "$driver" > "$out/bad-audit.log" 2>&1;then echo 'Failed episode audits were accepted.' >&2;exit 1;fi
[[ "$(< "$out/bad-audit/run.exit")" != 0 && ! -e "$out/bad-audit/comparison.json" ]]
echo 'Small-policy benchmark rejects training overlap and failed episode audits.'
