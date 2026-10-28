#!/usr/bin/env bash
# Verify an older 128-state policy runs on the current simulator.
set -euo pipefail
policy="$(realpath "${1:?Policy required}")";scene="$(realpath "${2:?Scene required}")"
out="${3:?New output directory required}";runtime="$(realpath "${4:?Frozen runtime required}")"
[[ ! -e "$out" ]];mkdir "$out";out="$(cd "$out" && pwd)"
sha="$(sha256sum "$policy/weights.bin" | cut -d' ' -f1)"
jq -e --arg sha "$sha" '.weightsSHA256==$sha and (.memoryWidth // 128)==128 and .memoryPoseAuxiliary and (.taskFeedback|not)' "$policy/receipt.json" > /dev/null
cd "$runtime"
./build/flex/control/control run --policy "$policy" --scene "$scene" --output "$out/run" --episodes 1 --seed 9960002 --horizon 12 > "$out/run.log" 2>&1
jq -e --arg sha "$sha" '.complete and .episodes==1 and .rows[0].policyWeightsSHA256==$sha and .rows[0].maximumBrickDistanceM==0.35 and (.rows[0].taskEventHint|not) and (.rows[0].suppliedMap|not)' "$out/run/summary.json" > /dev/null
for file in case.json environment.bin;do cmp "$scene/$file" "$out/run/9960002/scene/$file";done
./build/flex/control/control verify --run "$out/run/9960002" --policy "$out/run/policy" --output "$out/verified" > "$out/verify.log" 2>&1
jq -e --arg sha "$sha" '.passed and .commandReplayMaxAbsError==0 and .weightsSHA256==$sha and .taskEventHintAbsent' "$out/verified/result.json" > /dev/null
echo 'Earlier small pose policy runs and replays on the current simulator.'
