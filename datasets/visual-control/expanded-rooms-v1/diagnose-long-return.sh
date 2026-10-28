#!/usr/bin/env bash
# Give a known brick-finding student additional time without changing its
# inputs or controller. This is diagnostic, not the 300-action task score.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
base="$project/build/flex/sim/expanded-rooms-v1";root="$base/large-model-v1"
training="$root/student-only-training-v1";policy="$training/policy"
prior="$training/screen/2/9960002";scene="$base/unseen-benchmark-v2/scenes/18/2";runtime="$root/phase-large-tests-v1/runtime"
out="${PUPPYBOT_LONG_RETURN_OUT:?New output directory required}"
[[ ! -e "$out" ]];mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
while [[ ! -f "$training/run.exit" ]];do [[ -f "$training/run.pid" ]] && kill -0 "$(< "$training/run.pid")" || { echo 'Training ended without status.' >&2;exit 1; };sleep 20;done
[[ "$(< "$training/run.exit")" == 0 ]]
jq -e '.found and (.success|not) and .steps==300 and .maximumBrickDistanceM==0.35' "$prior/result.json" > /dev/null
jq -e '.passed and .modelCommandsReplayed==300 and .commandReplayMaxAbsError==0 and .consumptionEventsProjected>=1 and .taskEventHintAbsent' "$training/screen/2/verified/result.json" > /dev/null
sha256sum "$policy/weights.bin" "$policy/policy" "$policy/receipt.json" "$prior/result.json" "$prior/decisions.jsonl" "$training/screen/2/verified/result.json" "$scene/case.json" "$scene/environment.bin" "$runtime/build/flex/control/control" "$runtime/build/flex/control/simulator" > "$out/inputs.sha256"
sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1 PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
cd "$runtime"
./build/flex/control/control run --policy "$policy" --scene "$scene" --output "$out/run" --episodes 1 --seed 9960002 --horizon 600 --large-model > "$out/run.log" 2>&1
./build/flex/control/control verify --run "$out/run/9960002" --policy "$out/run/policy" --output "$out/verified" --large-model > "$out/verify.log" 2>&1
jq -e '.passed and .commandReplayMaxAbsError==0 and .consumptionEventsProjected>=1 and .taskEventHintAbsent' "$out/verified/result.json" > /dev/null
for file in case.json environment.bin;do cmp "$prior/scene/$file" "$out/run/9960002/scene/$file";done
head -n 300 "$prior/decisions.jsonl" | jq -c '[.action,.actorSHA256,.proprio]' > "$out/prior-prefix.jsonl"
head -n 300 "$out/run/9960002/decisions.jsonl" | jq -c '[.action,.actorSHA256,.proprio]' > "$out/long-prefix.jsonl"
cmp "$out/prior-prefix.jsonl" "$out/long-prefix.jsonl"
sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
jq -n --slurpfile prior "$prior/result.json" --slurpfile extended "$out/run/9960002/result.json" --slurpfile audit "$out/verified/result.json" '{passed:true,diagnosticOnly:true,strict300ActionResultUnchanged:true,original:{found:$prior[0].found,returned:$prior[0].success,steps:$prior[0].steps},extended:{found:$extended[0].found,returned:$extended[0].success,steps:$extended[0].steps,simulationSeconds:$extended[0].simulationSeconds,pathM:$extended[0].pathM},identicalFirst300ActorInputsAndCommands:true,modelCommandsReplayed:$audit[0].modelCommandsReplayed,automaticPromotion:false}' > "$out/result.json"
echo 'Long-horizon student return diagnostic completed.'
