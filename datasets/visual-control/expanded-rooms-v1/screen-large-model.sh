#!/usr/bin/env bash
set -euo pipefail

project="${PUPPYBOT_PROJECT:?Project root is required}"
base="$project/build/flex/sim/expanded-rooms-v1"
root="$base/large-model-v1"
out="${PUPPYBOT_SCREEN_OUTPUT:-$root/early-screen}"
policy="${PUPPYBOT_POLICY:-$root/large}"
[[ ! -e "$out" ]]
/usr/bin/mkdir -p "$out"
export PATH="$base/unseen-benchmark-v2/native-path"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1
cd "$root/workspace"
cases=(0 1 16 17)
if [[ "${PUPPYBOT_SCREEN_CASES:-default}" == return ]]; then cases=(1 2 16 17)
elif [[ "${PUPPYBOT_SCREEN_CASES:-default}" == observed ]]; then cases=(2 15 16 17)
else [[ "${PUPPYBOT_SCREEN_CASES:-default}" == default ]]; fi
summaries=()
for index in "${cases[@]}"; do
    layout=$((18+index/16)); scene=$((index%16)); seed=$((9960000+index))
    extra=(--large-model); if (( layout%2 )); then extra+=(--hidden-target); fi
    ../runtime/control run --policy "$policy" --scene "$base/unseen-benchmark-v2/scenes/$layout/$scene" --output "$out/$index" --episodes 1 --seed "$seed" --horizon 300 "${extra[@]}" > "$out/$index.log" 2>&1
    ../runtime/control verify --run "$out/$index/$seed" --policy "$out/$index/policy" --output "$out/$index/verified" --large-model > "$out/$index-verified.log" 2>&1
    /usr/bin/jq -e '.passed and .commandReplayMaxAbsError==0' "$out/$index/verified/result.json" > /dev/null
    summaries+=("$out/$index/summary.json")
done
/usr/bin/jq -s '{exploratory:true,episodes:length,approaches:map(select(.rows[0].found))|length,returns:map(select(.rows[0].success))|length,rows:map(.rows[0])}' "${summaries[@]}" > "$out/summary.json"
