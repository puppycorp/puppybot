#!/usr/bin/env bash
# Integration check on an audited recording. Uses software rendering and no policy.
set -euo pipefail
worker="$(realpath "${1:?Coverage label executable required}")"
query="$(realpath "${2:?Coverage query executable required}")"
runtime="$(realpath "${3:?Simulator runtime required}")"
scene="$(realpath "${4:?Original scene required}")"
recording="$(realpath "${5:?Original recording required}")"
data="$(realpath "${6:?Packed data required}")"
episode="${7:?Packed episode index required}"
out="$(realpath -m "${8:?New output directory required}")"
[[ "$episode" =~ ^[0-9]+$ && ! -e "$out" ]]; mkdir -p "$out/recording"
sim="$runtime/build/flex/control/simulator"; [[ -x "$worker" && -x "$query" && -x "$sim" ]]
initial="$(jq -er '.totalSteps|select(type=="number" and .>=0 and floor==.)' "$recording/initial.json")"
jq -rn 'limit(9; inputs|select(.step!=null)|.step)' "$recording/decisions.jsonl" > "$out/steps.txt"
[[ "$(wc -l < "$out/steps.txt")" == 9 ]]
cp "$recording/decisions.jsonl" "$out/recording/decisions.jsonl"
for step in "$initial" $(cat "$out/steps.txt"); do [[ "$step" =~ ^[0-9]+$ ]]; cp "$recording/actor-$step.rgb" "$recording/actor-$step.feedback" "$out/recording/"; done
run() { (cd "$runtime"; LIBGL_ALWAYS_SOFTWARE=1 "$@" ); }
run "$worker" "$sim" "$scene" "$out/recording" "$data" "$episode" 10 "$out/good" > "$out/good.log" 2>&1
jq -e '.searchLabels==10 and .replayedCommands==9 and .observationFramesMatched==10 and .termination=="label-limit" and .actorInputsUnchanged and .recordedActionsReplayed and .teacherLabelsOnly and (.datasetModified|not) and (.autonomousSuccessClaimed|not)' "$out/good/result.json" > /dev/null
[[ "$(sha256sum "$out/good/teacher-search.jsonl" | cut -d' ' -f1)" == "$(jq -r .teacherSearchSHA256 "$out/good/result.json")" ]]
run "$query" "$sim" "$scene" "$out/recording" "$data" "$episode" 3 "$out/query" > "$out/query.log" 2>&1
jq -s -e --slurpfile q "$out/query/result.json" 'length==10 and all(to_entries[]; .key==.value.step) and .[3].label==$q[0].action and .[3].goal==$q[0].goal and .[3].source==$q[0].source' "$out/good/teacher-search.jsonl" > /dev/null
printf '\001' | dd of="$out/recording/actor-$initial.rgb" bs=1 seek=0 conv=notrunc status=none
if run "$worker" "$sim" "$scene" "$out/recording" "$data" "$episode" 10 "$out/bad-image" > "$out/bad-image.log" 2>&1; then echo 'Changed actor pixels accepted.' >&2; exit 1; fi
rg -Fq 'replayed camera input differs from recording' "$out/bad-image.log"; [[ ! -e "$out/bad-image/result.json" ]]
cp "$recording/actor-$initial.rgb" "$out/recording/actor-$initial.rgb"
first="$(head -n 1 "$out/steps.txt")"
jq -c --argjson step "$first" 'if .step==$step then .action=[0,(if .action[1]>0 then -1 else 1 end)] else . end' "$recording/decisions.jsonl" > "$out/recording/decisions.jsonl"
if run "$worker" "$sim" "$scene" "$out/recording" "$data" "$episode" 10 "$out/bad-action" > "$out/bad-action.log" 2>&1; then echo 'Changed recorded command accepted.' >&2; exit 1; fi
rg -Fq 'recorded action differs from packed executed command' "$out/bad-action.log"; [[ ! -e "$out/bad-action/result.json" ]]
echo 'Coverage search-label replay matches the point query and rejects changed inputs and commands.'
