#!/usr/bin/env bash
# Score one fetch player on the 32 test games of every search level (PUPPYBOT_LEVELS, default 1-5), one level at a time;
# levels already scored are kept.
# Usage: score.sh ROOT NAME (teacher | POLICY_DIR) [extra flags such as --explore-teacher]
# Level L writes ROOT/eval-LL/NAME and ROOT/eval-LL/score-NAME.json; levels 4 and 5 play the two-room layout 19.
# Levels 4 and 5 swapped on 2 Nov 2026 (4 is now the doorway drill, 5 the other room). Games since then record
# levelPlacement, and a root whose level 4 or 5 games lack it holds the old numbering and is refused.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
root="${1:?Output root required}"; name="${2:?Player name required}"; player="${3:?teacher or policy directory required}"; shift 3
cd "$project"
for L in ${PUPPYBOT_LEVELS:-1 2 3 4 5}; do
    two=0; [[ $L -lt 4 ]] || two=1
    old=$(find "$root/eval-L$L" -mindepth 4 -maxdepth 4 -name result.json -print -quit 2>/dev/null || true)
    [[ $two != 1 || -z "$old" ]] || jq -e .levelPlacement "$old" > /dev/null || { echo "$root/eval-L$L holds games from before the level 4/5 swap; score into a new root." >&2; exit 1; }
    [[ -f "$root/eval-L$L/score-$name.json" ]] || PUPPYBOT_EVAL_TWO_ROOM=$two bash datasets/visual-control/chase-v1/evaluate.sh "$root/eval-L$L" "$name" "$player" --fetch --level $L "$@" > "$root/eval-L$L-$name.log" 2>&1 || { echo "Level $L $name failed; see $root/eval-L$L-$name.log" >&2; exit 1; }
    echo "L$L $name $(jq -c '{d:.meanDeliveriesPerMinute,g:.gamesWithADelivery,r:.meanReachesPerMinute,p:.meanPingPongShare,b:.meanBackForthShare}' "$root/eval-L$L/score-$name.json")"
done
