#!/usr/bin/env bash
# Mixed ensemble: the doorway student edag-s2 votes with dart-s1 and dart-s2 until STEPS steps pass without carrying or
# a delivery (--ensemble-until), then drives alone; standard test and levels 1-5 at pitch 82, level 5 split by room.
set -euo pipefail
cd /home/teppo/Work/my/puppybot
export PUPPYBOT_PROJECT=$PWD LD_LIBRARY_PATH=$PWD/build/flex/rocm-runtime
R=$PWD/build/flex/sim/levels-v1; H=$PWD/datasets/visual-control/chase-v1; P=$R/pitch82; S=$H/levels; E=$P/ensemble
mkdir -p "$E"
export PUPPYBOT_CHASE_PARTS=${PUPPYBOT_CHASE_PARTS:-2}  # three policies per game: more than about 8 policy processes at once starve on the GPU
for until in ${UNTIL:-20 35 60}; do
    c=mix$until
    flags=(--camera-pitch 82 --ensemble "$P/dart-s1" --ensemble "$P/dart-s2" --ensemble-until "$until")
    [[ -f "$E/eval/score-$c.json" ]] || bash "$H/evaluate.sh" "$E/eval" "$c" "$P/edag-s2" --fetch "${flags[@]}" > "$E/$c.eval.log" 2>&1
    PUPPYBOT_LEVELS="1 2 3 4 5" bash "$H/levels/score.sh" "$E" "$c" "$P/edag-s2" "${flags[@]}" > /dev/null
    echo "$c standard $(jq .meanDeliveriesPerMinute "$E/eval/score-$c.json") $(for L in 1 2 3 4 5; do printf 'L%s %s ' $L "$(jq .meanDeliveriesPerMinute "$E/eval-L$L/score-$c.json")"; done)| $(python3 -I "$S/l5cross.py" "$E"/eval-L5/$c/*/99*)"
done
