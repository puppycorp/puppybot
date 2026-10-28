#!/usr/bin/env bash
# Score one chase player on unseen layouts 18/19: 32 one-minute games, same seeds and placements for every player.
# Usage: evaluate.sh OUTPUT_ROOT NAME (teacher | forward | POLICY_DIR) [extra run flags such as --blackout --large-model]
# Game g (0-31) uses seed 990000+g on scenes/(18+g%2)/(8*(g/16)+(g%16)/2), whatever the split into parallel parts.
# Games are lean with wheel-only odometry unless PUPPYBOT_CHASE_FULL=1 (needed for viewer videos).
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
root="${1:?Output root required}"; name="${2:?Player name required}"; player="${3:?teacher, forward or policy directory required}"; shift 3
parts="${PUPPYBOT_CHASE_PARTS:-8}" record=(--lean --wheel-odometry)
[[ "${PUPPYBOT_CHASE_FULL:-0}" != 1 ]] || record=()
(( parts >= 1 && parts <= 16 && 32 % parts == 0 )) || { echo 'PUPPYBOT_CHASE_PARTS must divide 32 and give at least two games per part.' >&2; exit 1; }
n=$((32 / parts)); scenes="$project/build/flex/sim/expanded-rooms-v1/unseen-benchmark-v2/scenes"
cd "$project"
mkdir -p "$root/catalogs"
for ((p=0; p<parts; p++)); do
    catalog="$root/catalogs/$parts-$p"
    if [[ ! -d "$catalog" ]]; then mkdir "$catalog"; for ((j=0; j<n; j++)); do g=$((p * n + j)); ln -s "$scenes/$((18 + g % 2))/$((8 * (g / 16) + (g % 16) / 2))" "$catalog/$j"; done; fi
done
[[ ! -e "$root/$name" ]]; mkdir "$root/$name"
pids=()
for ((p=0; p<parts; p++)); do
    seed=$((990000 + p * n)) out="$root/$name/$p" log="$root/$name/$p.log" catalog="$root/catalogs/$parts-$p"
    run=(env -u WAYLAND_DISPLAY -u DISPLAY SDL_VIDEODRIVER=offscreen nice -n 19 build/flex/control/control)
    if [[ "$player" == teacher ]]; then
        "${run[@]}" collect --chase --scene-catalog "$catalog" --output "$out" --episodes "$n" --validation 1 --horizon 300 --seed "$seed" "${record[@]}" > "$log" 2>&1 & pids+=("$!")
    elif [[ "$player" == forward ]]; then
        "${run[@]}" run --chase --chase-forward --scene-catalog "$catalog" --output "$out" --episodes "$n" --horizon 300 --seed "$seed" "${record[@]}" > "$log" 2>&1 & pids+=("$!")
    else
        "${run[@]}" run --chase --policy "$player" --scene-catalog "$catalog" --output "$out" --episodes "$n" --horizon 300 --seed "$seed" "${record[@]}" "$@" > "$log" 2>&1 & pids+=("$!")
    fi
done
status=0; for pid in "${pids[@]}"; do wait "$pid" || status=1; done
(( status == 0 )) || { echo "Chase evaluation $name failed; logs retained." >&2; exit 1; }
jq -s --arg name "$name" '{player:$name,games:length,reaches:(map(.reaches)|add),meanReachesPerMinute:(map(.reachesPerMinute)|add/length),
  gamesWithAReach:(map(select(.reaches>0))|length),meanContactSteps:(map(.contactSteps)|add/length),meanPathM:(map(.pathM)|add/length),
  reachesBySeed:(sort_by(.seed)|map(.reaches))}' $(find "$root/$name" -name result.json | sort) > "$root/score-$name.json"
jq -c 'del(.reachesBySeed)' "$root/score-$name.json"
