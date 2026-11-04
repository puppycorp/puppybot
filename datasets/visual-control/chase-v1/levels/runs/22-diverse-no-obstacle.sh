#!/usr/bin/env bash
# Obstacle check for runs/20: the same 16 diverse two-room layouts and seeds, generated with --no-obstacle; the
# door-early teacher plays 64 level-4 and 64 level-5 games there, added to data-early (1024 games from 56 shards);
# three students dno-s* with the seeds of early-s*.
set -euo pipefail
cd /home/teppo/Work/my/puppybot
export PUPPYBOT_PROJECT=$PWD LD_LIBRARY_PATH=$PWD/build/flex/rocm-runtime
R=$PWD/build/flex/sim/levels-v1; H=$PWD/datasets/visual-control/chase-v1; P=$R/pitch82; S=$H/levels; D=$R/diverse-scenes-no-obstacle
[[ -d "$D/57" ]] || build/flex/control/diverse-generator "$D" 26 58 fit --no-obstacle
echo "== door-early teacher on diverse two-room layouts $(date +%T)"
PUPPYBOT_CHASE_SCENES=$D PUPPYBOT_CHASE_LAYOUTS="$(seq -s ' ' 27 2 57)" PUPPYBOT_LEVELS="4 5" PUPPYBOT_LEVELS_TEACHER=--sweep-teacher PUPPYBOT_CHASE_SHARDS=4 PUPPYBOT_CHASE_EPISODES=16 \
    nice -n 10 bash "$S/collect.sh" "$P" dno 2500000 --action-noise 3 --camera-pitch 82 --door-pass --door-early
echo "teacher L5: $(python3 -I "$S/l5cross.py" "$P"/dno-L5/shard-*/expert-*)"
[[ -f "$P/data-dno/data.bin" ]] || "$R/sweep-L4/aggregate" "$P/data-dno" 300 0 $(ls "$P"/dart-L[0-3]/shard-?/data.bin "$P"/early-L[45]/shard-?/data.bin "$P"/dno-L[45]/shard-?/data.bin) > /dev/null
echo "== students $(date +%T)"
for s in 0 1 2; do
    out=$P/dno-s$s
    [[ -f "$out/receipt.json" ]] || nice -n 10 build/flex/control/control train --output "$out" --seed $((7 + s)) --data "$P/data-dno/data.bin" --policy build/flex/sim/chase-v1/train-d5-agg --categorical --mirror-augment --carry-cue --epochs 30 --batch 2 --checkpoint-every 10 > "$out.log" 2>&1
    [[ ! -f "$out/data.bin" ]] || { cmp -s "$out/data.bin" "$P/data-dno/data.bin" && rm "$out/data.bin"; }
    [[ -f "$P/eval/score-dno-s$s.json" ]] || bash "$H/evaluate.sh" "$P/eval" "dno-s$s" "$out" --fetch --camera-pitch 82 > "$out.eval.log" 2>&1
    echo "dno-s$s standard $(jq .meanDeliveriesPerMinute "$P/eval/score-dno-s$s.json")"
done
for s in 0 1 2; do PUPPYBOT_LEVELS="1 2 3 4 5" bash "$S/score.sh" "$P" "dno-s$s" "$P/dno-s$s" --camera-pitch 82 > /dev/null; done
for L in 1 2 3 4 5; do echo "dno L$L $(jq -s -c 'map(.meanDeliveriesPerMinute) | {runs:., mean:(add/length)}' "$P/eval-L$L/score-dno-s0.json" "$P/eval-L$L/score-dno-s1.json" "$P/eval-L$L/score-dno-s2.json")"; done
for s in 0 1 2; do echo "dno-s$s L5: $(python3 -I "$S/l5cross.py" "$P"/eval-L5/dno-s$s/*/99*)"; done
echo "== done $(date +%T)"
