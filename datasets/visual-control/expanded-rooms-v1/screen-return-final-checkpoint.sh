#!/usr/bin/env bash
set -euo pipefail

project="${PUPPYBOT_PROJECT:?Project root is required}"
base="$project/build/flex/sim/expanded-rooms-v1"
run="$base/return-quick-v1"
probe="$base/correction-probe-v1"
out="$base/return-quick-final-v1"
[[ ! -e "$out/run.exit" && ! -e "$out/policy" ]]
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
printf '%s\n' "$BASHPID" > "$out/run.pid"
while [[ ! -f "$run/run.exit" ]];do
    [[ -f "$run/run.pid" ]] && kill -0 "$(< "$run/run.pid")" || { echo 'Return screen disappeared without a terminal status.' >&2;exit 1; }
    /usr/bin/sleep 10
done
[[ "$(< "$run/run.exit")" == 0 ]] || { echo 'Selected-checkpoint screen did not complete.' >&2;exit 1; }
cd "$project"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
/usr/bin/sha256sum -c "$probe/screen-inputs.sha256" > "$out/screen-integrity-before.log"
/usr/bin/jq -e '.exploratory and .allEpisodeAuditsPassed and (.qualifiesForPromotion|not)' "$run/comparison.json" > /dev/null
/usr/bin/cmp "$run/initial/weights.bin" "$run/model/weights.bin"
/usr/bin/jq -s 'length==21 and .[-1].epoch==20 and .[-1].optimizerSteps==120 and ([.[]|select(.selected)|.epoch]|last)==0' "$run/model/curves.jsonl" > /dev/null
export PATH="$out/native-path"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1
cd "$out/runtime"
"$out/publish" "$run/model/epoch-20.bin" "$run/merged-16/data.bin" "$run/model/initial.bin" "$out/policy" 20 "$run/targets" > "$out/publish.log" 2>&1
/usr/bin/cmp "$run/model/epoch-20.bin" "$out/policy/weights.bin"
./build/flex/control/forward-tests "$out/policy" "$run/merged-16/data.bin" "$out/forward" > "$out/forward.log" 2>&1
/usr/bin/jq -e '.passed and .logitMaxAbsError==0 and .memoryMaxAbsError==0 and .resetBitIdentical' "$out/forward/result.json" > /dev/null
cd "$project"
/usr/bin/bash "$probe/screen-benchmark.sh" "$out/policy" screen-return-epoch20-v1
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
/usr/bin/sha256sum -c "$probe/screen-inputs.sha256" > "$out/screen-integrity-after.log"
/usr/bin/jq -s '{exploratory:true,selection:"epoch 20 chosen after validation selected unchanged initial weights; not independent checkpoint selection",initial:.[0],epoch20:.[1],allEpisodeAuditsPassed:all(.[];.completedRecordings==8 and .auditedEpisodes==8 and .auditFailures==0),qualifiesForPromotion:false,retainedPolicyOverwritten:false}' "$probe/score-screen-contact-quick-v1.json" "$probe/score-screen-return-epoch20-v1.json" > "$out/comparison.json"
echo 'Post-hoc epoch-20 return-policy screen completed; no promotion claim.'
