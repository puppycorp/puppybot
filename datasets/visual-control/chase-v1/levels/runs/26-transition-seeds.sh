#!/usr/bin/env bash
# Without the eightfold drive-change loss weight the map student stopped rocking and passed doorways (runs/25 ftrw-s0).
# Two more seeds of it (ftrw), and seed 0 with the reversal penalty on top (ftrv).
set -euo pipefail
cd /home/teppo/Work/my/puppybot
export PUPPYBOT_PROJECT=$PWD LD_LIBRARY_PATH=$PWD/build/flex/rocm-runtime
R=$PWD/build/flex/sim/levels-v1; H=$PWD/datasets/visual-control/chase-v1; P=$R/pitch82; S=$H/levels; D=$P/data-exfix
for name in ftrw-s1 ftrw-s2 ftrv-s0; do
    out=$P/$name; s=${name##*-s}; extra=(--transition-weight-one)
    [[ $name != ftrv-* ]] || extra+=(--reversal-penalty-milli 1000)
    [[ -f "$out/receipt.json" ]] || nice -n 10 build/flex/control/control train --output "$out" --seed $((7 + s)) --data "$D/data.bin" --memory-map "$D/map.bin" "${extra[@]}" --policy build/flex/sim/chase-v1/train-d5-agg --categorical --mirror-augment --carry-cue --epochs 30 --batch 2 --checkpoint-every 10 > "$out.log" 2>&1
    [[ ! -f "$out/data.bin" ]] || { cmp -s "$out/data.bin" "$D/data.bin" && rm "$out/data.bin"; }
    [[ -f "$P/eval/score-$name.json" ]] || bash "$H/evaluate.sh" "$P/eval" "$name" "$out" --fetch --camera-pitch 82 > "$out.eval.log" 2>&1
    PUPPYBOT_LEVELS="1 2 3 4 5" bash "$S/score.sh" "$P" "$name" "$out" --camera-pitch 82 > /dev/null
    echo "$name standard $(jq -c '{d:.meanDeliveriesPerMinute,p:.meanPingPongShare}' "$P/eval/score-$name.json")"
    for L in 1 2 3 4 5; do echo "  L$L $(jq -c '{d:.meanDeliveriesPerMinute,p:.meanPingPongShare,g:.gamesMostlyPingPong}' "$P/eval-L$L/score-$name.json")"; done
    echo "  L5 $(python3 -I "$S/l5cross.py" "$P"/eval-L5/$name/*/99*)"
done
echo "== done $(date +%T)"
