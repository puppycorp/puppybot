#!/usr/bin/env bash
# Collect chase-game demonstrations on training layouts 12-17 in parallel shards, then aggregate into one PVDATA04 file.
# PUPPYBOT_CHASE_POLICY makes that policy drive while the teacher labels every step.
# Games are lean (no video, trace or sensor PNGs) with wheel-only odometry unless PUPPYBOT_CHASE_FULL=1.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
out="${1:?New output directory required}"
shards="${PUPPYBOT_CHASE_SHARDS:-16}" per="${PUPPYBOT_CHASE_EPISODES:-16}" validation="${PUPPYBOT_CHASE_VALIDATION:-2}"
policy="${PUPPYBOT_CHASE_POLICY:-}" seed_base="${PUPPYBOT_CHASE_SEED:-700000}" driver=() record=(--lean --wheel-odometry)
[[ -z "$policy" ]] || driver=(--policy "$policy")
[[ "${PUPPYBOT_CHASE_FULL:-0}" != 1 ]] || record=()
scenes="$project/build/flex/sim/expanded-rooms-v1/scenes"
cd "$project"
[[ ! -e "$out" ]]; mkdir -p "$out/catalogs"
"$project/build/flex/control/compiler" "$project/datasets/visual-control/chase-v1/aggregate.flex" -o "$out/aggregate"
for ((k=0; k<shards; k++)); do
    mkdir "$out/catalogs/$k"
    for ((i=0; i<per; i++)); do ln -s "$scenes/$((12 + i % 6))/$(((k * 8 + i / 6) % 16))" "$out/catalogs/$k/$i"; done
done
pids=()
for ((k=0; k<shards; k++)); do
    env -u WAYLAND_DISPLAY -u DISPLAY SDL_VIDEODRIVER=offscreen nice -n 19 build/flex/control/control collect --chase \
        --scene-catalog "$out/catalogs/$k" --output "$out/shard-$k" --episodes "$per" --validation "$validation" \
        --horizon 300 --seed $((seed_base + k * 1000)) "${record[@]}" "${driver[@]}" > "$out/shard-$k.log" 2>&1 & pids+=("$!")
done
status=0; for pid in "${pids[@]}"; do wait "$pid" || status=1; done
(( status == 0 )) || { echo 'A chase shard failed; shards and logs retained.' >&2; exit 1; }
# Whole 300-step games; training on this file matches the legacy merged and packed file exactly.
"$out/aggregate" "$out/data" 300 0 $(for ((k=0; k<shards; k++)); do printf '%s ' "$out/shard-$k/data.bin"; done)
jq -s '{episodes:length,reaches:(map(.reaches)|add),meanReachesPerMinute:(map(.reachesPerMinute)|add/length),meanContactSteps:(map(.contactSteps)|add/length)}' "$out"/shard-*/expert-*/result.json > "$out/teacher-summary.json"
cat "$out/teacher-summary.json"
