#!/usr/bin/env bash
# Item 7: the camera tilted up (wrist pitch 82 instead of 75): teacher on every level, then noisy teacher data and students.
set -euo pipefail
cd /home/teppo/Work/my/puppybot
export PUPPYBOT_PROJECT=$PWD LD_LIBRARY_PATH=$PWD/build/flex/rocm-runtime
R=$PWD/build/flex/sim/levels-v1; H=$PWD/datasets/visual-control/chase-v1; P=$R/pitch82
mkdir -p "$P"
echo "== sweep teacher at pitch 82 $(date +%T)"
PUPPYBOT_LEVELS="1 2 3 4 5" bash "$H/levels/score.sh" "$P" sweep teacher --sweep-teacher --camera-pitch 82
echo "== noisy teacher games at pitch 82 $(date +%T)"
nice -n 10 env PUPPYBOT_LEVELS_TEACHER=--sweep-teacher PUPPYBOT_CHASE_SHARDS=8 PUPPYBOT_CHASE_EPISODES=16 bash "$H/levels/collect.sh" "$P" dart 910000 --action-noise 3 --camera-pitch 82
[[ -f "$P/data-dart/data.bin" ]] || "$R/sweep-L4/aggregate" "$P/data-dart" 300 0 $(for L in 0 1 2 3 4; do for k in 0 1 2 3 4 5 6 7; do printf '%s ' "$P/dart-L$L/shard-$k/data.bin"; done; done)
echo "== students at pitch 82 $(date +%T)"
[[ -f "$P/score-dart.json" ]] || PUPPYBOT_EVAL_FLAGS="--fetch --camera-pitch 82" bash "$H/seeds.sh" "$P" dart 3 --data "$P/data-dart/data.bin" --policy build/flex/sim/chase-v1/train-d5-agg --categorical --mirror-augment --carry-cue --epochs 30 --batch 2 --checkpoint-every 10
echo "dart standard $(jq -c .deliveriesPerMinute "$P/score-dart.json")"
for s in 0 1 2; do PUPPYBOT_LEVELS="1 2 3 4 5" bash "$H/levels/score.sh" "$P" "dart-s$s" "$P/dart-s$s" --camera-pitch 82 > /dev/null; done
for L in 1 2 3 4 5; do echo "dart L$L $(jq -s -c 'map(.meanDeliveriesPerMinute) | {runs:., mean:(add/length)}' "$P/eval-L$L/score-dart-s0.json" "$P/eval-L$L/score-dart-s1.json" "$P/eval-L$L/score-dart-s2.json")"; done
echo "== done $(date +%T)"
