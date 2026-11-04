#!/usr/bin/env bash
# Gated straight bias: dart-s2 with its straight logit raised by B hundredths only after A steps without the brick,
# on the standard test, levels 1 and 3-5, with level 5 split by brick room. Configurations are B:A pairs.
set -euo pipefail
cd /home/teppo/Work/my/puppybot
export PUPPYBOT_PROJECT=$PWD LD_LIBRARY_PATH=$PWD/build/flex/rocm-runtime
R=$PWD/build/flex/sim/levels-v1; H=$PWD/datasets/visual-control/chase-v1; P=$R/pitch82; S=$H/levels; B=$P/bias
POLICY=${POLICY:-dart-s2}
for c in ${CONFIGS:-200:40 200:80 300:80}; do
    b=${c%:*}; a=${c#*:}; name=${POLICY#dart-}-b$b-a$a; flags=(--camera-pitch 82 --straight-bias $b --straight-after $a)
    [[ -f "$B/eval/score-$name.json" ]] || bash "$H/evaluate.sh" "$B/eval" "$name" "$P/$POLICY" --fetch "${flags[@]}" > "$B/$name.eval.log" 2>&1
    PUPPYBOT_LEVELS="1 3 4 5" bash "$H/levels/score.sh" "$B" "$name" "$P/$POLICY" "${flags[@]}" > /dev/null
    echo "$name standard $(jq .meanDeliveriesPerMinute "$B/eval/score-$name.json") L1 $(jq .meanDeliveriesPerMinute "$B/eval-L1/score-$name.json") L3 $(jq .meanDeliveriesPerMinute "$B/eval-L3/score-$name.json") L4 $(jq .meanDeliveriesPerMinute "$B/eval-L4/score-$name.json") L5 $(jq .meanDeliveriesPerMinute "$B/eval-L5/score-$name.json") | $(python3 -I "$S/l5cross.py" "$B"/eval-L5/$name/*/99*)"
done
