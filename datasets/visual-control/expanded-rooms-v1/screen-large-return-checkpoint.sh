#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$project/build/flex/sim/expanded-rooms-v1/large-model-v1"
training="$root/return-training-v1"
out="$root/return-epoch5-probe"
[[ ! -e "$out" ]]
/usr/bin/mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
while ! /usr/bin/jq -se 'any(.[]; .epoch==5)' "$training/policy/curves.jsonl" > /dev/null 2>&1; do
    if [[ -f "$training/run.exit" ]]; then echo 'Training ended before checkpoint 5 was available.' >&2; exit 1; fi
    [[ -f "$training/run.pid" ]] && kill -0 "$(< "$training/run.pid")" || { echo 'Training ended without a status.' >&2; exit 1; }
    /usr/bin/sleep 20
done
cd "$root/correction-v3/runtime"
../publish-large-checkpoint "$training/policy/epoch-5.bin" "$training/policy/data.bin" "$training/policy/seed.bin" "$out/policy" 5 "$training/policy/target-position" --mirror-augment > "$out/publish.log" 2>&1
/usr/bin/cmp "$training/policy/epoch-5.bin" "$out/policy/weights.bin"
/usr/bin/jq -e '.memoryWidth==256 and .epochs==5 and .sequenceMirrorAugmentation and (.taskFeedback|not)' "$out/policy/receipt.json" > /dev/null
export PUPPYBOT_POLICY="$out/policy"
export PUPPYBOT_SCREEN_OUTPUT="$out/screen"
export PUPPYBOT_SCREEN_CASES=return
/usr/bin/bash "$root/source/datasets/screen-large-model.sh" > "$out/screen.log" 2>&1
