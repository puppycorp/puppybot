#!/usr/bin/env bash
# Straight bias: dart-s2 played with its straight-ahead logit raised by B hundredths (1 checks it matches plain play),
# on the standard test and levels 3-5, with level 5 split by brick room.
set -euo pipefail
cd /home/teppo/Work/my/puppybot
export PUPPYBOT_PROJECT=$PWD LD_LIBRARY_PATH=$PWD/build/flex/rocm-runtime
R=$PWD/build/flex/sim/levels-v1; H=$PWD/datasets/visual-control/chase-v1; P=$R/pitch82; S=$H/levels; B=$P/bias
mkdir -p "$B"
for b in ${BIASES:-1 50 100 200}; do
    name=s2-b$b
    [[ -f "$B/eval/score-$name.json" ]] || bash "$H/evaluate.sh" "$B/eval" "$name" "$P/dart-s2" --fetch --camera-pitch 82 --straight-bias $b > "$B/$name.eval.log" 2>&1
    PUPPYBOT_LEVELS="3 4 5" bash "$H/levels/score.sh" "$B" "$name" "$P/dart-s2" --camera-pitch 82 --straight-bias $b > /dev/null
    echo "bias $b standard $(jq .meanDeliveriesPerMinute "$B/eval/score-$name.json") L3 $(jq .meanDeliveriesPerMinute "$B/eval-L3/score-$name.json") L4 $(jq .meanDeliveriesPerMinute "$B/eval-L4/score-$name.json") L5 $(jq .meanDeliveriesPerMinute "$B/eval-L5/score-$name.json") | $(python3 -I "$S/l5cross.py" "$B"/eval-L5/$name/*/99*)"
done
