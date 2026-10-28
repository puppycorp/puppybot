#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
base="$project/build/flex/sim/expanded-rooms-v1"
root="$base/large-model-v1"
out="$root/mirrored-long-return-v1"
policy="$root/expanded-236-mirrored"
[[ ! -e "$out" ]]
/usr/bin/mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
for index in 1 2; do
    /usr/bin/jq -e '.found and .auditPassed and (.physicalReturned|not)' "$root/expanded-benchmark/mirrored/$index/benchmark-row.json" > /dev/null
done
export PATH="$base/unseen-benchmark-v2/native-path"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1
cd "$root/workspace"
for index in 1 2; do
    seed=$((9960000+index)); run="$out/$index"
    ../runtime/control run --policy "$policy" --scene "$base/unseen-benchmark-v2/scenes/18/$index" --output "$run" --episodes 1 --seed "$seed" --horizon 600 --large-model > "$out/$index.log" 2>&1
    ../runtime/control verify --run "$run/$seed" --policy "$run/policy" --output "$run/verified" --large-model > "$out/$index-verified.log" 2>&1
    /usr/bin/jq -e '.passed and .commandReplayMaxAbsError==0 and .consumptionEventsProjected==1' "$run/verified/result.json" > /dev/null
    /usr/bin/jq -c '[.action,.state.pose]' "$root/expanded-benchmark/mirrored/$index/$seed/decisions.jsonl" > "$out/$index-original-prefix.jsonl"
    /usr/bin/jq -c 'select(input_line_number<=300)|[.action,.state.pose]' "$run/$seed/decisions.jsonl" > "$out/$index-long-prefix.jsonl"
    /usr/bin/cmp "$out/$index-original-prefix.jsonl" "$out/$index-long-prefix.jsonl"
done
/usr/bin/jq -s '{exploratory:true,episodes:length,approaches:map(select(.rows[0].found))|length,returns:map(select(.rows[0].success))|length,horizonActions:600,original300ActionsAndPosesReproduced:true,rows:map(.rows[0])}' "$out/1/summary.json" "$out/2/summary.json" > "$out/summary.json"
