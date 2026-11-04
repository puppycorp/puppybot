#!/usr/bin/env bash
# Doorway generalization: the door-early teacher plays 64 level-4 and 64 level-5 games on 16 new two-room layouts from
# generate-diverse (odd IDs 27-57: varied bounds, doorway, start pose, floor colour and an obstacle), added to
# data-early (1024 games from 56 shards); three students div-s* with the seeds of early-s*.
set -euo pipefail
cd /home/teppo/Work/my/puppybot
export PUPPYBOT_PROJECT=$PWD LD_LIBRARY_PATH=$PWD/build/flex/rocm-runtime
R=$PWD/build/flex/sim/levels-v1; H=$PWD/datasets/visual-control/chase-v1; P=$R/pitch82; S=$H/levels; D=$R/diverse-scenes
[[ -d "$D/57" ]] || build/flex/control/diverse-generator "$D" 26 58 fit
echo "== door-early teacher on diverse two-room layouts $(date +%T)"
PUPPYBOT_CHASE_SCENES=$D PUPPYBOT_CHASE_LAYOUTS="$(seq -s ' ' 27 2 57)" PUPPYBOT_LEVELS="4 5" PUPPYBOT_LEVELS_TEACHER=--sweep-teacher PUPPYBOT_CHASE_SHARDS=4 PUPPYBOT_CHASE_EPISODES=16 \
    nice -n 10 bash "$S/collect.sh" "$P" div 2500000 --action-noise 3 --camera-pitch 82 --door-pass --door-early
echo "teacher L5: $(python3 -I "$S/l5cross.py" "$P"/div-L5/shard-*/expert-*)"
[[ -f "$P/data-div/data.bin" ]] || "$R/sweep-L4/aggregate" "$P/data-div" 300 0 $(ls "$P"/dart-L[0-3]/shard-?/data.bin "$P"/early-L[45]/shard-?/data.bin "$P"/div-L[45]/shard-?/data.bin) > /dev/null
echo "== students $(date +%T)"
for s in 0 1 2; do
    out=$P/div-s$s
    [[ -f "$out/receipt.json" ]] || nice -n 10 build/flex/control/control train --output "$out" --seed $((7 + s)) --data "$P/data-div/data.bin" --policy build/flex/sim/chase-v1/train-d5-agg --categorical --mirror-augment --carry-cue --epochs 30 --batch 2 --checkpoint-every 10 > "$out.log" 2>&1
    [[ ! -f "$out/data.bin" ]] || { cmp -s "$out/data.bin" "$P/data-div/data.bin" && rm "$out/data.bin"; }
    [[ -f "$P/eval/score-div-s$s.json" ]] || bash "$H/evaluate.sh" "$P/eval" "div-s$s" "$out" --fetch --camera-pitch 82 > "$out.eval.log" 2>&1
    echo "div-s$s standard $(jq .meanDeliveriesPerMinute "$P/eval/score-div-s$s.json")"
done
for s in 0 1 2; do PUPPYBOT_LEVELS="1 2 3 4 5" bash "$S/score.sh" "$P" "div-s$s" "$P/div-s$s" --camera-pitch 82 > /dev/null; done
for L in 1 2 3 4 5; do echo "div L$L $(jq -s -c 'map(.meanDeliveriesPerMinute) | {runs:., mean:(add/length)}' "$P/eval-L$L/score-div-s0.json" "$P/eval-L$L/score-div-s1.json" "$P/eval-L$L/score-div-s2.json")"; done
for s in 0 1 2; do echo "div-s$s L5: $(python3 -I "$S/l5cross.py" "$P"/eval-L5/div-s$s/*/99*)"; done
echo "== done $(date +%T)"
