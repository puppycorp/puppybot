#!/usr/bin/env bash
# Longer training on the door-early DAgger set: data-edag (1024 games) for 60 epochs instead of 30, three fresh
# students edag60-s*, scored like edag-s*.
set -euo pipefail
cd /home/teppo/Work/my/puppybot
export PUPPYBOT_PROJECT=$PWD LD_LIBRARY_PATH=$PWD/build/flex/rocm-runtime
R=$PWD/build/flex/sim/levels-v1; H=$PWD/datasets/visual-control/chase-v1; P=$R/pitch82; S=$H/levels
for s in 0 1 2; do
    out=$P/edag60-s$s
    [[ -f "$out/receipt.json" ]] || nice -n 10 build/flex/control/control train --output "$out" --seed $((7 + s)) --data "$P/data-edag/data.bin" --policy build/flex/sim/chase-v1/train-d5-agg --categorical --mirror-augment --carry-cue --epochs 60 --batch 2 --checkpoint-every 20 > "$out.log" 2>&1
    [[ ! -f "$out/data.bin" ]] || { cmp -s "$out/data.bin" "$P/data-edag/data.bin" && rm "$out/data.bin"; }
    [[ -f "$P/eval/score-edag60-s$s.json" ]] || bash "$H/evaluate.sh" "$P/eval" "edag60-s$s" "$out" --fetch --camera-pitch 82 > "$out.eval.log" 2>&1
    echo "edag60-s$s standard $(jq .meanDeliveriesPerMinute "$P/eval/score-edag60-s$s.json") best epoch $(jq -s 'min_by(.validationLoss)|.epoch' "$out/curves.jsonl")"
done
for s in 0 1 2; do PUPPYBOT_LEVELS="1 2 3 4 5" bash "$H/levels/score.sh" "$P" "edag60-s$s" "$P/edag60-s$s" --camera-pitch 82 > /dev/null; done
for L in 1 2 3 4 5; do echo "edag60 L$L $(jq -s -c 'map(.meanDeliveriesPerMinute) | {runs:., mean:(add/length)}' "$P/eval-L$L/score-edag60-s0.json" "$P/eval-L$L/score-edag60-s1.json" "$P/eval-L$L/score-edag60-s2.json")"; done
for s in 0 1 2; do echo "edag60-s$s L5: $(python3 -I "$S/l5cross.py" "$P"/eval-L5/edag60-s$s/*/99*)"; done
echo "== done $(date +%T)"
