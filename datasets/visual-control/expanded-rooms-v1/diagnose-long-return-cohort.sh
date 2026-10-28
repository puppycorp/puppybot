#!/usr/bin/env bash
# Give every observed brick approach more time; this is post-hoc diagnosis.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
base="$project/build/flex/sim/expanded-rooms-v1";root="$base/large-model-v1"
training="$root/student-only-training-v1";policy="$training/policy";baseline="$root/student-only-benchmark-v1/augmented"
previous="$root/long-return-diagnostic-v1";runtime="$root/phase-large-tests-v1/runtime"
out="${PUPPYBOT_LONG_RETURN_COHORT_OUT:?New output directory required}"
[[ ! -e "$out" ]];mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
if [[ -n "${PUPPYBOT_LONG_RETURN_WAIT_RUN:-}" ]];then
    job="$PUPPYBOT_LONG_RETURN_WAIT_RUN"
    while [[ ! -f "$job.exit" ]];do [[ -f "$job.pid" ]] && kill -0 "$(< "$job.pid")" || { echo 'Previous benchmark ended without a status.' >&2;exit 1; };sleep 20;done
    printf '%s\n' "$(< "$job.exit")" > "$out/prior-benchmark-status.txt"
fi
[[ "$(< "$training/run.exit")" == 0 && "$(< "$root/student-only-benchmark-v1/run.exit")" == 0 && "$(< "$previous/run.exit")" == 0 ]]
sha="$(sha256sum "$policy/weights.bin" | cut -d' ' -f1)"
jq -e --arg sha "$sha" '.weightsSHA256==$sha and .memoryWidth==256 and (.taskFeedback|not)' "$policy/receipt.json" > /dev/null
jq -e --arg sha "$sha" '.episodes==32 and .auditedEpisodes==32 and .completedRecordings==32 and ([.rows[]|select(.found)|.caseIndex]|sort)==[2,3,8,9,10] and all(.rows[];.policyWeightsSHA256==$sha and .auditPassed and (.taskEventHint|not) and (.suppliedMap|not))' "$baseline/score.json" > /dev/null
jq -e '.passed and .diagnosticOnly and .identicalFirst300ActorInputsAndCommands and .original.found and (.original.returned|not) and .original.steps==300 and .extended.steps==600 and (.automaticPromotion|not)' "$previous/result.json" > /dev/null
jq -e --arg sha "$sha" '.passed and .commandReplayMaxAbsError==0 and .weightsSHA256==$sha and .consumptionEventsProjected>=1 and .taskEventHintAbsent' "$previous/verified/result.json" > /dev/null
sha256sum "$policy/weights.bin" "$policy/policy" "$policy/receipt.json" "$baseline/score.json" "$previous/result.json" "$previous/verified/result.json" "$previous/run/9960002/decisions.jsonl" "$runtime/build/flex/control/control" "$runtime/build/flex/control/simulator" > "$out/inputs.sha256"
for index in 2 3 8 9 10;do
    case_seed=$((9960000+index));prior="$baseline/$index/$case_seed"
    jq -e --arg sha "$sha" '.passed and .commandReplayMaxAbsError==0 and .weightsSHA256==$sha and .consumptionEventsProjected>=1 and .taskEventHintAbsent' "$baseline/$index/verified/result.json" > /dev/null
    sha256sum "$prior/result.json" "$prior/decisions.jsonl" "$baseline/$index/verified/result.json" "$prior/scene/case.json" "$prior/scene/environment.bin" >> "$out/inputs.sha256"
done
sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
head -n 300 "$baseline/2/9960002/decisions.jsonl" | jq -c '[.action,.actorSHA256,.proprio]' > "$out/case-2-prefix.jsonl"
head -n 300 "$previous/run/9960002/decisions.jsonl" | jq -c '[.action,.actorSHA256,.proprio]' > "$out/case-2-long-prefix.jsonl"
cmp "$out/case-2-prefix.jsonl" "$out/case-2-long-prefix.jsonl"
jq -n --slurpfile result "$previous/result.json" '{caseIndex:2,found:true,returned:$result[0].extended.returned,steps:$result[0].extended.steps,simulationSeconds:$result[0].extended.simulationSeconds,modelCommandsReplayed:$result[0].modelCommandsReplayed}' > "$out/case-2.json"
export PATH="$base/unseen-benchmark-v2/native-path:$PATH" XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1 PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
cd "$runtime"
for index in 3 8 9 10;do
    case_seed=$((9960000+index));prior="$baseline/$index/$case_seed";scene="$base/unseen-benchmark-v2/scenes/18/$index";run="$out/case-$index"
    ./build/flex/control/control run --policy "$policy" --scene "$scene" --output "$run" --episodes 1 --seed "$case_seed" --horizon 600 --large-model > "$out/case-$index.log" 2>&1
    ./build/flex/control/control verify --run "$run/$case_seed" --policy "$run/policy" --output "$out/case-$index-verified" --large-model > "$out/case-$index-verify.log" 2>&1
    jq -e --arg sha "$sha" '.passed and .commandReplayMaxAbsError==0 and .weightsSHA256==$sha and .consumptionEventsProjected>=1 and .taskEventHintAbsent' "$out/case-$index-verified/result.json" > /dev/null
    for file in case.json environment.bin;do cmp "$prior/scene/$file" "$run/$case_seed/scene/$file";done
    head -n 300 "$prior/decisions.jsonl" | jq -c '[.action,.actorSHA256,.proprio]' > "$out/case-$index-prefix.jsonl"
    head -n 300 "$run/$case_seed/decisions.jsonl" | jq -c '[.action,.actorSHA256,.proprio]' > "$out/case-$index-long-prefix.jsonl"
    cmp "$out/case-$index-prefix.jsonl" "$out/case-$index-long-prefix.jsonl"
    jq -n --argjson index "$index" --slurpfile result "$run/$case_seed/result.json" --slurpfile audit "$out/case-$index-verified/result.json" '{caseIndex:$index,found:$result[0].found,returned:$result[0].success,steps:$result[0].steps,simulationSeconds:$result[0].simulationSeconds,modelCommandsReplayed:$audit[0].modelCommandsReplayed}' > "$out/case-$index.json"
    jq -e '.found and .steps>300 and .steps<=600 and .modelCommandsReplayed==.steps' "$out/case-$index.json" > /dev/null
done
sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
jq -s '{passed:true,diagnosticOnly:true,selectedAfterObservedApproach:true,episodes:length,extendedHorizonActions:600,identicalFirst300ActorInputsAndCommands:true,approaches:(map(select(.found))|length),returns:(map(select(.returned))|length),meanSimulationSecondsAmongReturns:(map(select(.returned)|.simulationSeconds)|if length>0 then add/length else null end),strict300ActionResultUnchanged:true,automaticPromotion:false,rows:sort_by(.caseIndex)}' "$out"/case-{2,3,8,9,10}.json > "$out/summary.json"
jq -e '.passed and .episodes==5 and .approaches==5 and .identicalFirst300ActorInputsAndCommands and (.automaticPromotion|not)' "$out/summary.json" > /dev/null
echo 'Post-hoc 600-action return diagnostics completed for all five approaches.'
