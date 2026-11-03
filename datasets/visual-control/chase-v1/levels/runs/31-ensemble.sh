#!/usr/bin/env bash
# The three more1 students (runs/30, diary 38) playing together (--ensemble, mean of their action probabilities, as
# in runs/15), on the standard test and levels 1-5 at pitch 82, with the doorway drill split by brick room.
set -euo pipefail
cd /home/teppo/Work/my/puppybot
export PUPPYBOT_PROJECT=$PWD LD_LIBRARY_PATH=$PWD/build/flex/rocm-runtime
H=$PWD/datasets/visual-control/chase-v1; P=$PWD/build/flex/sim/levels-v2/pitch82; S=$H/levels; E=$P/ensemble
mkdir -p "$E"
export PUPPYBOT_CHASE_PARTS=${PUPPYBOT_CHASE_PARTS:-2}  # three policies per game: more than about 8 policy processes at once starve on the GPU
for c in ${CONFIGS:-more1}; do
    flags=(--camera-pitch 82 --ensemble "$P/$c-s1" --ensemble "$P/$c-s2")
    [[ -f "$E/eval/score-$c.json" ]] || bash "$H/evaluate.sh" "$E/eval" "$c" "$P/$c-s0" --fetch "${flags[@]}" > "$E/$c.eval.log" 2>&1
    PUPPYBOT_LEVELS="1 2 3 4 5" bash "$S/score.sh" "$E" "$c" "$P/$c-s0" "${flags[@]}" > /dev/null
    echo "$c ensemble standard $(jq -c '{d:.meanDeliveriesPerMinute,b:.meanBackForthShare}' "$E/eval/score-$c.json")"
    for L in 1 2 3 4 5; do echo "  L$L $(jq -c '{d:.meanDeliveriesPerMinute,b:.meanBackForthShare,g:.gamesMostlyBackForth}' "$E/eval-L$L/score-$c.json")"; done
    echo "  L4 $(python3 -I "$S/l5cross.py" "$E"/eval-L4/$c/*/99*)"
done
