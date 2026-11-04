#!/usr/bin/env bash
# Collect search-teacher fetch games for normal placement (L0) and levels 1-5 on the training layouts.
# Usage: collect.sh ROOT PREFIX SEED_BASE [extra flags such as --action-noise 3]; level L writes ROOT/PREFIX-LL with seeds from SEED_BASE + L*10000.
# Shard and policy settings pass through to ../collect.sh (PUPPYBOT_CHASE_SHARDS, _EPISODES, _VALIDATION, _POLICY).
# PUPPYBOT_LEVELS_TEACHER picks the teacher flag (default --explore-teacher) and PUPPYBOT_LEVELS the levels (default 0 1 2 3 4).
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
root="${1:?Output root required}"; prefix="${2:?Output prefix required}"; seed="${3:?Seed base required}"; shift 3; teacher="${PUPPYBOT_LEVELS_TEACHER:---explore-teacher}"
cd "$project"
for L in ${PUPPYBOT_LEVELS:-0 1 2 3 4}; do
    [[ ! -f "$root/$prefix-L$L/data/data.bin" ]] || continue
    level=(); [[ $L == 0 ]] || level=(--level $L)
    two=0; [[ $L -lt 4 ]] || two=1
    PUPPYBOT_CHASE_TWO_ROOM=$two PUPPYBOT_CHASE_SEED=$((seed + L * 10000)) bash datasets/visual-control/chase-v1/collect.sh "$root/$prefix-L$L" --fetch "$teacher" "${level[@]}" "$@" > "$root/$prefix-L$L.log" 2>&1 || { echo "Level $L collection failed; see $root/$prefix-L$L.log" >&2; exit 1; }
    echo "L$L $(jq -c '{episodes,meanDeliveriesPerMinute}' "$root/$prefix-L$L/teacher-summary.json") disagreements $(cat "$root/$prefix-L$L"/shard-*/expert-*/result.json | jq -s 'map(.teacherDisagreements)|add/length')"
done
