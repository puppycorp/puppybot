#!/usr/bin/env bash
# Check extended-episode pairing with fake recordings; no simulator is used.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]]
mock="$out/mock";base="$mock/build/flex/sim/expanded-rooms-v1";root="$base/large-model-v1"
training="$root/student-only-training-v1";baseline="$root/student-only-benchmark-v1/augmented";previous="$root/long-return-diagnostic-v1";runtime="$root/phase-large-tests-v1/runtime"
mkdir -p "$training/policy" "$baseline" "$previous/verified" "$previous/run/9960002" "$runtime/build/flex/control" "$base/unseen-benchmark-v2/scenes/18" "$base/unseen-benchmark-v2/native-path"
printf 'weights\n' > "$training/policy/weights.bin";printf 'binary\n' > "$training/policy/policy";sha="$(sha256sum "$training/policy/weights.bin" | cut -d' ' -f1)"
jq -n --arg sha "$sha" '{weightsSHA256:$sha,memoryWidth:256,taskFeedback:false}' > "$training/policy/receipt.json"
printf '0\n' > "$training/run.exit";printf '0\n' > "$root/student-only-benchmark-v1/run.exit";printf '0\n' > "$previous/run.exit"
jq -n --arg sha "$sha" '{episodes:32,auditedEpisodes:32,completedRecordings:32,rows:[range(0;32) as $i|{caseIndex:$i,found:([2,3,8,9,10]|index($i)!=null),policyWeightsSHA256:$sha,auditPassed:true,taskEventHint:false,suppliedMap:false}]}' > "$baseline/score.json"
jq -n '{passed:true,diagnosticOnly:true,identicalFirst300ActorInputsAndCommands:true,original:{found:true,returned:false,steps:300},extended:{found:true,returned:false,steps:600,simulationSeconds:125.9},modelCommandsReplayed:600,automaticPromotion:false}' > "$previous/result.json"
jq -n --arg sha "$sha" '{passed:true,commandReplayMaxAbsError:0,weightsSHA256:$sha,consumptionEventsProjected:1,taskEventHintAbsent:true}' > "$previous/verified/result.json"
for index in 2 3 8 9 10;do
    case_seed=$((9960000+index));run="$baseline/$index/$case_seed";scene="$base/unseen-benchmark-v2/scenes/18/$index"
    mkdir -p "$run/scene" "$baseline/$index/verified" "$scene"
    for file in case.json environment.bin;do printf 'scene %s %s\n' "$index" "$file" > "$scene/$file";cp "$scene/$file" "$run/scene/$file";done
    printf '{"found":true,"success":false,"steps":300}\n' > "$run/result.json"
    for ((n=0;n<300;n++));do printf '{"action":[0,1],"actorSHA256":"same","proprio":[0,0,0,0,0,0,0]}\n';done > "$run/decisions.jsonl"
    jq -n --arg sha "$sha" '{passed:true,commandReplayMaxAbsError:0,weightsSHA256:$sha,consumptionEventsProjected:1,taskEventHintAbsent:true}' > "$baseline/$index/verified/result.json"
done
cp "$baseline/2/9960002/decisions.jsonl" "$previous/run/9960002/decisions.jsonl"
printf 'simulator\n' > "$runtime/build/flex/control/simulator"
cat > "$runtime/build/flex/control/control" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
command="$1";shift
while (( $# ));do case "$1" in --policy) policy="$2";shift 2;; --scene) scene="$2";shift 2;; --output) output="$2";shift 2;; --seed) seed="$2";shift 2;; --run) run="$2";shift 2;; --episodes|--horizon) shift 2;; *) shift;; esac;done
if [[ "$command" == run ]];then
    mkdir -p "$output/$seed";cp -a "$scene" "$output/$seed/scene";ln -s "$policy" "$output/policy"
    for ((n=0;n<600;n++));do actor=same;if [[ "${PUPPYBOT_TEST_BAD_PREFIX:-0}" == 1 && "$seed" == 9960003 && "$n" == 0 ]];then actor=changed;fi;printf '{"action":[0,1],"actorSHA256":"%s","proprio":[0,0,0,0,0,0,0]}\n' "$actor";done > "$output/$seed/decisions.jsonl"
    returned=false;if [[ "$seed" == 9960008 ]];then returned=true;fi
    jq -n --argjson returned "$returned" '{found:true,success:$returned,steps:600,simulationSeconds:125.9}' > "$output/$seed/result.json"
elif [[ "$command" == verify ]];then
    mkdir "$output";sha="$(sha256sum "$policy/weights.bin" | cut -d' ' -f1)";passed=true;if [[ "${PUPPYBOT_TEST_BAD_AUDIT:-0}" == 1 ]];then passed=false;fi
    jq -n --arg sha "$sha" --argjson passed "$passed" '{passed:$passed,commandReplayMaxAbsError:0,weightsSHA256:$sha,consumptionEventsProjected:1,taskEventHintAbsent:true,modelCommandsReplayed:600}' > "$output/result.json"
else exit 1;fi
EOF
chmod +x "$runtime/build/flex/control/control"
driver="$project/datasets/visual-control/expanded-rooms-v1/diagnose-long-return-cohort.sh"
PUPPYBOT_PROJECT="$mock" PUPPYBOT_LONG_RETURN_COHORT_OUT="$out/good" bash "$driver" > "$out/good.log" 2>&1
jq -e '.passed and .diagnosticOnly and .selectedAfterObservedApproach and .episodes==5 and .returns==1 and .identicalFirst300ActorInputsAndCommands and (.automaticPromotion|not)' "$out/good/summary.json" > /dev/null
for fault in PUPPYBOT_TEST_BAD_PREFIX PUPPYBOT_TEST_BAD_AUDIT;do
    if env "$fault=1" PUPPYBOT_PROJECT="$mock" PUPPYBOT_LONG_RETURN_COHORT_OUT="$out/$fault" bash "$driver" > "$out/$fault.log" 2>&1;then echo "$fault was accepted." >&2;exit 1;fi
    [[ "$(< "$out/$fault/run.exit")" != 0 && ! -e "$out/$fault/summary.json" ]]
done
echo 'Extended-return diagnosis rejects changed prefixes and failed audits.'
