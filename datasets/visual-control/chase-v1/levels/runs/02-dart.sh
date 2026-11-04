#!/usr/bin/env bash
# Item 4 (DART) plus the learning-rate control for the size comparison.
# CPU collection overlaps GPU training only, never an evaluation.
set -euo pipefail
cd /home/teppo/Work/my/puppybot
export PUPPYBOT_PROJECT=$PWD LD_LIBRARY_PATH=$PWD/build/flex/rocm-runtime
R=$PWD/build/flex/sim/levels-v1; H=$PWD/datasets/visual-control/chase-v1
stats() {  # NAME: seed-mean score file from ROOT/eval
    jq -s --arg name "$1" 'def stats(f): (map(f)) as $v | ($v|add/length) as $m | {mean:$m,sd:($v|map((.-$m)*(.-$m))|add/(length-1)|sqrt),runs:$v};
      {configuration:$name,seeds:length,reachesPerMinute:stats(.meanReachesPerMinute),deliveriesPerMinute:stats(.meanDeliveriesPerMinute)}' \
      "$R/eval/score-$1-s0.json" "$R/eval/score-$1-s1.json" "$R/eval/score-$1-s2.json" > "$R/score-$1.json"
    echo "$1 standard $(jq -c .deliveriesPerMinute "$R/score-$1.json")"
}
levels() {  # NAME LEVELS
    for s in 0 1 2; do PUPPYBOT_LEVELS="$2" bash "$H/levels/score.sh" "$R" "$1-s$s" "$R/$1-s$s" > /dev/null; done
    for L in $2; do echo "$1 L$L $(jq -s -c 'map(.meanDeliveriesPerMinute) | {runs:., mean:(add/length)}' "$R/eval-L$L/score-$1-s0.json" "$R/eval-L$L/score-$1-s1.json" "$R/eval-L$L/score-$1-s2.json")"; done
}
echo "== DART collection and small at 2e-4 $(date +%T)"
nice -n 10 env PUPPYBOT_LEVELS_TEACHER=--sweep-teacher PUPPYBOT_CHASE_SHARDS=8 PUPPYBOT_CHASE_EPISODES=16 bash "$H/levels/collect.sh" "$R" dart 910000 --action-noise 3 > "$R/dart.log" 2>&1 & collect=$!
for s in 0 1 2; do
    [[ -f "$R/small200-s$s/receipt.json" ]] || nice -n 10 build/flex/control/control train --output "$R/small200-s$s" --seed $((7 + s)) --data "$R/data-mix/data.bin" --from-scratch --categorical --mirror-augment --carry-cue --epochs 40 --batch 2 --checkpoint-every 10 --learning-rate-micros 200 > "$R/small200-s$s.log" 2>&1
done
wait $collect; cat "$R/dart.log"
echo "== scoring small at 2e-4 $(date +%T)"
for s in 0 1 2; do [[ -f "$R/eval/score-small200-s$s.json" ]] || bash "$H/evaluate.sh" "$R/eval" "small200-s$s" "$R/small200-s$s" --fetch > "$R/small200-s$s.eval.log" 2>&1; done
stats small200; levels small200 "1 2 3 4"
echo "== DART students $(date +%T)"
[[ -f "$R/data-dart/data.bin" ]] || "$R/sweep-L4/aggregate" "$R/data-dart" 300 0 $(for L in 0 1 2 3 4; do for k in 0 1 2 3 4 5 6 7; do printf '%s ' "$R/dart-L$L/shard-$k/data.bin"; done; done)
[[ -f "$R/score-dart.json" ]] || PUPPYBOT_EVAL_FLAGS=--fetch bash "$H/seeds.sh" "$R" dart 3 --data "$R/data-dart/data.bin" --policy build/flex/sim/chase-v1/train-d5-agg --categorical --mirror-augment --carry-cue --epochs 30 --batch 2 --checkpoint-every 10
echo "dart standard $(jq -c .deliveriesPerMinute "$R/score-dart.json")"
levels dart "1 2 3 4 5"
echo "== done $(date +%T)"
