#!/usr/bin/env bash
# Score one chase player on unseen layouts 18/19: 32 one-minute games, same seeds and placements for every player.
# Usage: evaluate.sh OUTPUT_ROOT NAME (teacher | forward | POLICY_DIR) [extra flags such as --fetch --blackout --large-model]
# Game g (0-31) uses seed 990000+g on scenes/(18+g%2)/(8*(g/16)+(g%16)/2), whatever the split into parallel parts.
# PUPPYBOT_EVAL_TWO_ROOM=1 (for --level 4 or 5) uses the two-room layout only: scenes/19/(g%16).
# PUPPYBOT_EVAL_SELECTION=1 plays training layouts instead, for choosing among students without the test games:
# seed 980000+g on training scenes/(12+g%6)/(g%16), or two-room scenes/(13+2*(g%3))/(g%16).
# PUPPYBOT_EVAL_SELECTION_SEED overrides that base for selection games; callers must audit it against training seeds.
# Games are lean with wheel-only odometry unless PUPPYBOT_CHASE_FULL=1 (needed for viewer videos).
# meanPingPongShare: share of actions in runs of at least six that flip drive direction and do not turn (rocking in place);
# gamesMostlyPingPong counts games above 20%. meanBackForthShare and gamesMostlyBackForth do the same for actions in
# 20-action stretches that end under 0.25 m and 45 degrees from where they began with at least four drive reversals,
# which also catches loops slower than ping-pong.
# PUPPYBOT_CHASE_HORIZON sets the game length in 0.2 s actions (default 300, one minute; teachers at most 512).
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
root="${1:?Output root required}"; name="${2:?Player name required}"; player="${3:?teacher, forward or policy directory required}"; shift 3
parts="${PUPPYBOT_CHASE_PARTS:-8}" horizon="${PUPPYBOT_CHASE_HORIZON:-300}" record=(--lean --wheel-odometry) two_room="${PUPPYBOT_EVAL_TWO_ROOM:-0}" selection="${PUPPYBOT_EVAL_SELECTION:-0}"
[[ "${PUPPYBOT_CHASE_FULL:-0}" != 1 ]] || record=()
(( parts >= 1 && parts <= 16 && 32 % parts == 0 )) || { echo 'PUPPYBOT_CHASE_PARTS must divide 32 and give at least two games per part.' >&2; exit 1; }
n=$((32 / parts)); scenes="$project/build/flex/sim/expanded-rooms-v1/unseen-benchmark-v2/scenes"
cd "$project"
mkdir -p "$root/catalogs"
suffix=""; [[ "$two_room" != 1 ]] || suffix="-two-room"
base=990000; [[ "$selection" != 1 ]] || { base=${PUPPYBOT_EVAL_SELECTION_SEED:-980000}; suffix="$suffix-selection"; }
[[ "$base" =~ ^(0|[1-9][0-9]{0,9})$ ]] && (( base <= 2147483615 )) || { echo 'Selection seed base must be a nonnegative integer at most 2147483615.' >&2; exit 1; }
for ((p=0; p<parts; p++)); do
    catalog="$root/catalogs/$parts-$p$suffix"
    if [[ ! -d "$catalog" ]]; then mkdir "$catalog"; for ((j=0; j<n; j++)); do g=$((p * n + j)); scene="$scenes/$((18 + g % 2))/$((8 * (g / 16) + (g % 16) / 2))"; [[ "$two_room" != 1 ]] || scene="$scenes/19/$((g % 16))"
        if [[ "$selection" == 1 ]]; then scene="$project/build/flex/sim/expanded-rooms-v1/scenes/$((12 + g % 6))/$((g % 16))"; [[ "$two_room" != 1 ]] || scene="$project/build/flex/sim/expanded-rooms-v1/scenes/$((13 + 2 * (g % 3)))/$((g % 16))"; fi
        ln -s "$scene" "$catalog/$j"; done; fi
done
[[ ! -e "$root/$name" ]]; mkdir "$root/$name"
pids=()
for ((p=0; p<parts; p++)); do
    seed=$((base + p * n)) out="$root/$name/$p" log="$root/$name/$p.log" catalog="$root/catalogs/$parts-$p$suffix"
    run=(env -u WAYLAND_DISPLAY -u DISPLAY SDL_VIDEODRIVER=offscreen nice -n 19 build/flex/control/control)
    if [[ "$player" == teacher ]]; then
        "${run[@]}" collect --chase --scene-catalog "$catalog" --output "$out" --episodes "$n" --validation 1 --horizon "$horizon" --seed "$seed" "${record[@]}" "$@" > "$log" 2>&1 & pids+=("$!")
    elif [[ "$player" == forward ]]; then
        "${run[@]}" run --chase --chase-forward --scene-catalog "$catalog" --output "$out" --episodes "$n" --horizon "$horizon" --seed "$seed" "${record[@]}" "$@" > "$log" 2>&1 & pids+=("$!")
    else
        "${run[@]}" run --chase --policy "$player" --scene-catalog "$catalog" --output "$out" --episodes "$n" --horizon "$horizon" --seed "$seed" "${record[@]}" "$@" > "$log" 2>&1 & pids+=("$!")
    fi
done
status=0; for pid in "${pids[@]}"; do wait "$pid" || status=1; done
(( status == 0 )) || { echo "Chase evaluation $name failed; logs retained." >&2; exit 1; }
jq -s --arg name "$name" '{player:$name,games:length,reaches:(map(.reaches)|add),meanReachesPerMinute:(map(.reachesPerMinute)|add/length),
  gamesWithAReach:(map(select(.reaches>0))|length),meanContactSteps:(map(.contactSteps)|add/length),meanPathM:(map(.pathM)|add/length),
  reachesBySeed:(sort_by(.seed)|map(.reaches))}
  + if .[0].deliveries == null then {} else {deliveries:(map(.deliveries)|add),meanDeliveriesPerMinute:(map(.deliveriesPerMinute)|add/length),
  gamesWithADelivery:(map(select(.deliveries>0))|length),deliveriesBySeed:(sort_by(.seed)|map(.deliveries))} end
  + if .[0].pingPongSteps == null then {} else {meanPingPongShare:(map(.pingPongSteps/.steps)|add/length),
  gamesMostlyPingPong:(map(select(.pingPongSteps*5>.steps))|length)} end
  + if .[0].backForthSteps == null then {} else {meanBackForthShare:(map(.backForthSteps/.steps)|add/length),
  gamesMostlyBackForth:(map(select(.backForthSteps*5>.steps))|length)} end' $(find "$root/$name" -name result.json | sort) > "$root/score-$name.json"
jq -c 'del(.reachesBySeed, .deliveriesBySeed)' "$root/score-$name.json"
