#!/usr/bin/env bash
# New level numbering (4 doorway drill, 5 other room), root levels-v2. The exploring teacher now routes to a seen
# brick when walls or the box block the straight line, and its wall reverses keep turning like a three-point turn
# (explore-kturn, scored by hand). Collect its games as in runs/25 (drill games doubled) and train three seeds of
# the ftrw student on them (rtrw).
set -euo pipefail
cd /home/teppo/Work/my/puppybot
export PUPPYBOT_PROJECT=$PWD LD_LIBRARY_PATH=$PWD/build/flex/rocm-runtime
R=$PWD/build/flex/sim/levels-v1; H=$PWD/datasets/visual-control/chase-v1; P=$PWD/build/flex/sim/levels-v2/pitch82; S=$H/levels; D=$P/data-kturn
mkdir -p "$P"
echo "== teacher games $(date +%T)"
PUPPYBOT_LEVELS="0 1 2 3 5" PUPPYBOT_CHASE_SHARDS=8 PUPPYBOT_CHASE_EPISODES=16 nice -n 10 bash "$S/collect.sh" "$P" kturn 950000 --action-noise 3 --camera-pitch 82 --record-map
PUPPYBOT_LEVELS=4 PUPPYBOT_CHASE_SHARDS=8 PUPPYBOT_CHASE_EPISODES=32 nice -n 10 bash "$S/collect.sh" "$P" kturn 950000 --action-noise 3 --camera-pitch 82 --record-map
for L in 0 1 2 3 4 5; do echo "teacher training L$L: $(python3 -I "$S/backforth.py" "$P"/kturn-L$L/shard-*/expert-*)"; done
[[ -f "$D/map.bin" ]] || "$R/map-aggregate" "$D" 300 0 $(ls "$P"/kturn-L[0-5]/shard-?/data.bin) > /dev/null
echo "== students $(date +%T)"
for s in 0 1 2; do
    name=rtrw-s$s out=$P/rtrw-s$s
    [[ -f "$out/receipt.json" ]] || nice -n 10 build/flex/control/control train --output "$out" --seed $((7 + s)) --data "$D/data.bin" --memory-map "$D/map.bin" --transition-weight-one --policy build/flex/sim/chase-v1/train-d5-agg --categorical --mirror-augment --carry-cue --epochs 30 --batch 2 --checkpoint-every 10 > "$out.log" 2>&1
    [[ ! -f "$out/data.bin" ]] || { cmp -s "$out/data.bin" "$D/data.bin" && rm "$out/data.bin"; }
    [[ -f "$P/eval/score-$name.json" ]] || bash "$H/evaluate.sh" "$P/eval" "$name" "$out" --fetch --camera-pitch 82 > "$out.eval.log" 2>&1
    PUPPYBOT_LEVELS="1 2 3 4 5" bash "$S/score.sh" "$P" "$name" "$out" --camera-pitch 82 > /dev/null
    echo "$name standard $(jq -c '{d:.meanDeliveriesPerMinute,b:.meanBackForthShare}' "$P/eval/score-$name.json")"
    for L in 1 2 3 4 5; do echo "  L$L $(jq -c '{d:.meanDeliveriesPerMinute,b:.meanBackForthShare,g:.gamesMostlyBackForth}' "$P/eval-L$L/score-$name.json")"; done
    echo "  L4 $(python3 -I "$S/l5cross.py" "$P"/eval-L4/$name/*/99*)"
done
echo "== done $(date +%T)"
