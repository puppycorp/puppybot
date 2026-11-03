#!/usr/bin/env bash
# Doorway drill: 256 noisy sweep-teacher level-5 games at pitch 82 added to the 640 pitch-82 games, three students,
# scored on every level with level 5 split into same-room and past-doorway bricks.
set -euo pipefail
cd /home/teppo/Work/my/puppybot
export PUPPYBOT_PROJECT=$PWD LD_LIBRARY_PATH=$PWD/build/flex/rocm-runtime
R=$PWD/build/flex/sim/levels-v1; H=$PWD/datasets/visual-control/chase-v1; P=$R/pitch82; S=$H/levels
echo "== noisy teacher doorway drill at pitch 82 $(date +%T)"
nice -n 10 env PUPPYBOT_LEVELS=5 PUPPYBOT_LEVELS_TEACHER=--sweep-teacher PUPPYBOT_CHASE_SHARDS=8 PUPPYBOT_CHASE_EPISODES=32 bash "$H/levels/collect.sh" "$P" dart 910000 --action-noise 3 --camera-pitch 82
echo "teacher training layouts: $(python3 -I "$S/l5split.py" "$P"/dart-L5/shard-*/expert-* | tr '\n' ' ')"
[[ -f "$P/data-door/data.bin" ]] || "$R/sweep-L4/aggregate" "$P/data-door" 300 0 $(ls "$P"/dart-L?/shard-?/data.bin) > /dev/null
echo "== students $(date +%T)"
[[ -f "$P/score-door.json" ]] || PUPPYBOT_EVAL_FLAGS="--fetch --camera-pitch 82" bash "$H/seeds.sh" "$P" door 3 --data "$P/data-door/data.bin" --policy build/flex/sim/chase-v1/train-d5-agg --categorical --mirror-augment --carry-cue --epochs 30 --batch 2 --checkpoint-every 10
echo "door standard $(jq -c .deliveriesPerMinute "$P/score-door.json")"
for s in 0 1 2; do PUPPYBOT_LEVELS="1 2 3 4 5" bash "$H/levels/score.sh" "$P" "door-s$s" "$P/door-s$s" --camera-pitch 82 > /dev/null; done
for L in 1 2 3 4 5; do echo "door L$L $(jq -s -c 'map(.meanDeliveriesPerMinute) | {runs:., mean:(add/length)}' "$P/eval-L$L/score-door-s0.json" "$P/eval-L$L/score-door-s1.json" "$P/eval-L$L/score-door-s2.json")"; done
for s in 0 1 2; do echo "door-s$s L5 split: $(python3 -I "$S/l5split.py" "$P"/eval-L5/door-s$s/*/99* | tr '\n' ' ')"; done
echo "== done $(date +%T)"
