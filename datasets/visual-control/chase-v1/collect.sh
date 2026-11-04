#!/usr/bin/env bash
# Collect chase-game demonstrations on training layouts 12-17 in parallel shards, then aggregate into one PVDATA04 file.
# PUPPYBOT_CHASE_POLICY makes that policy drive while the teacher labels every step.
# Games are lean (no video, trace or sensor PNGs) with wheel-only odometry unless PUPPYBOT_CHASE_FULL=1.
# PUPPYBOT_CHASE_TWO_ROOM=1 (for --level 4 or 5) uses only the two-room layouts 13, 15 and 17.
# PUPPYBOT_CHASE_SCENES and PUPPYBOT_CHASE_LAYOUTS (a space-separated list) play other generated layouts instead.
# Usage: collect.sh OUTPUT [extra collect flags such as --fetch]
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
out="${1:?New output directory required}"; shift
shards="${PUPPYBOT_CHASE_SHARDS:-16}" per="${PUPPYBOT_CHASE_EPISODES:-16}" validation="${PUPPYBOT_CHASE_VALIDATION:-2}"
policy="${PUPPYBOT_CHASE_POLICY:-}" seed_base="${PUPPYBOT_CHASE_SEED:-700000}" two_room="${PUPPYBOT_CHASE_TWO_ROOM:-0}" driver=() record=(--lean --wheel-odometry)
[[ -z "$policy" ]] || driver=(--policy "$policy")
[[ "${PUPPYBOT_CHASE_FULL:-0}" != 1 ]] || record=()
scenes="${PUPPYBOT_CHASE_SCENES:-$project/build/flex/sim/expanded-rooms-v1/scenes}" layouts=(${PUPPYBOT_CHASE_LAYOUTS:-})
cd "$project"
[[ ! -e "$out" ]]; mkdir -p "$out/catalogs"
"$project/build/flex/control/compiler" "$project/datasets/visual-control/chase-v1/aggregate.flex" -o "$out/aggregate"
for ((k=0; k<shards; k++)); do
    mkdir "$out/catalogs/$k"
    for ((i=0; i<per; i++)); do
        layout=$((12 + i % 6)) variant=$(((k * 8 + i / 6) % 16))
        [[ "$two_room" != 1 ]] || { layout=$((13 + 2 * (i % 3))); variant=$(((k * 8 + i / 3) % 16)); }
        (( ${#layouts[@]} == 0 )) || { layout=${layouts[$(((k * per + i) % ${#layouts[@]}))]}; variant=$(((k * per + i) / ${#layouts[@]} % 16)); }
        ln -s "$scenes/$layout/$variant" "$out/catalogs/$k/$i"
    done
done
pids=()
for ((k=0; k<shards; k++)); do
    env -u WAYLAND_DISPLAY -u DISPLAY SDL_VIDEODRIVER=offscreen nice -n 19 build/flex/control/control collect --chase \
        --scene-catalog "$out/catalogs/$k" --output "$out/shard-$k" --episodes "$per" --validation "$validation" \
        --horizon 300 --seed $((seed_base + k * 1000)) "${record[@]}" "${driver[@]}" "$@" > "$out/shard-$k.log" 2>&1 & pids+=("$!")
done
status=0; for pid in "${pids[@]}"; do wait "$pid" || status=1; done
(( status == 0 )) || { echo 'A chase shard failed; shards and logs retained.' >&2; exit 1; }
# Whole 300-step games; training on this file matches the legacy merged and packed file exactly.
"$out/aggregate" "$out/data" 300 0 $(for ((k=0; k<shards; k++)); do printf '%s ' "$out/shard-$k/data.bin"; done)
jq -s '{episodes:length,reaches:(map(.reaches)|add),meanReachesPerMinute:(map(.reachesPerMinute)|add/length),meanContactSteps:(map(.contactSteps)|add/length)}
  + if .[0].deliveries == null then {} else {deliveries:(map(.deliveries)|add),meanDeliveriesPerMinute:(map(.deliveriesPerMinute)|add/length)} end' "$out"/shard-*/expert-*/result.json > "$out/teacher-summary.json"
cat "$out/teacher-summary.json"
