#!/usr/bin/env bash
# Seed selection for the doorway specialist: five more students on data-edag2 (edag2-s3..s7), all eight scored on
# levels 4 and 5 of the training-layout selection games (PUPPYBOT_EVAL_SELECTION=1, never the test games); the best
# by level 4 + level 5 plays the test levels alone and as the main policy of the --ensemble-until 35 mix.
set -euo pipefail
cd /home/teppo/Work/my/puppybot
export PUPPYBOT_PROJECT=$PWD LD_LIBRARY_PATH=$PWD/build/flex/rocm-runtime
R=$PWD/build/flex/sim/levels-v1; H=$PWD/datasets/visual-control/chase-v1; P=$R/pitch82; S=$H/levels; E=$P/ensemble; Q=$P/select
mkdir -p "$Q"
echo "== students $(date +%T)"
for s in 3 4 5 6 7; do
    out=$P/edag2-s$s
    [[ -f "$out/receipt.json" ]] || nice -n 10 build/flex/control/control train --output "$out" --seed $((7 + s)) --data "$P/data-edag2/data.bin" --policy build/flex/sim/chase-v1/train-d5-agg --categorical --mirror-augment --carry-cue --epochs 30 --batch 2 --checkpoint-every 10 > "$out.log" 2>&1
    [[ ! -f "$out/data.bin" ]] || { cmp -s "$out/data.bin" "$P/data-edag2/data.bin" && rm "$out/data.bin"; }
done
echo "== selection games $(date +%T)"
for s in 0 1 2 3 4 5 6 7; do
    PUPPYBOT_EVAL_SELECTION=1 PUPPYBOT_LEVELS="4 5" bash "$S/score.sh" "$Q" "edag2-s$s" "$P/edag2-s$s" --camera-pitch 82 > /dev/null
    echo "edag2-s$s selection L4 $(jq .meanDeliveriesPerMinute "$Q/eval-L4/score-edag2-s$s.json") L5 $(jq .meanDeliveriesPerMinute "$Q/eval-L5/score-edag2-s$s.json") | $(python3 -I "$S/l5cross.py" "$Q"/eval-L5/edag2-s$s/*/98*)"
done
best=$(for s in 0 1 2 3 4 5 6 7; do echo "$(jq -s 'map(.meanDeliveriesPerMinute)|add' "$Q"/eval-L[45]/score-edag2-s$s.json) $s"; done | sort -rn | head -1 | cut -d' ' -f2)
echo "== chosen edag2-s$best $(date +%T)"
[[ -f "$P/eval/score-edag2-s$best.json" ]] || bash "$H/evaluate.sh" "$P/eval" "edag2-s$best" "$P/edag2-s$best" --fetch --camera-pitch 82 > "$P/edag2-s$best.eval.log" 2>&1
PUPPYBOT_LEVELS="1 2 3 4 5" bash "$S/score.sh" "$P" "edag2-s$best" "$P/edag2-s$best" --camera-pitch 82 > /dev/null
echo "edag2-s$best alone standard $(jq .meanDeliveriesPerMinute "$P/eval/score-edag2-s$best.json") $(for L in 1 2 3 4 5; do printf 'L%s %s ' $L "$(jq .meanDeliveriesPerMinute "$P/eval-L$L/score-edag2-s$best.json")"; done)| $(python3 -I "$S/l5cross.py" "$P"/eval-L5/edag2-s$best/*/99*)"
c=mix35e2s$best; flags=(--camera-pitch 82 --ensemble "$P/dart-s1" --ensemble "$P/dart-s2" --ensemble-until 35)
export PUPPYBOT_CHASE_PARTS=2
[[ -f "$E/eval/score-$c.json" ]] || bash "$H/evaluate.sh" "$E/eval" "$c" "$P/edag2-s$best" --fetch "${flags[@]}" > "$E/$c.eval.log" 2>&1
PUPPYBOT_LEVELS="1 2 3 4 5" bash "$S/score.sh" "$E" "$c" "$P/edag2-s$best" "${flags[@]}" > /dev/null
echo "$c standard $(jq .meanDeliveriesPerMinute "$E/eval/score-$c.json") $(for L in 1 2 3 4 5; do printf 'L%s %s ' $L "$(jq .meanDeliveriesPerMinute "$E/eval-L$L/score-$c.json")"; done)| $(python3 -I "$S/l5cross.py" "$E"/eval-L5/$c/*/99*)"
echo "== done $(date +%T)"
