#!/usr/bin/env bash
# Rest of queue7 with the disk nearly full: train door seeds one at a time, dropping each training copy of the data
# once it matches data-door, then score as queue7 does.
set -euo pipefail
cd /home/teppo/Work/my/puppybot
export PUPPYBOT_PROJECT=$PWD LD_LIBRARY_PATH=$PWD/build/flex/rocm-runtime
R=$PWD/build/flex/sim/levels-v1; H=$PWD/datasets/visual-control/chase-v1; P=$R/pitch82; S=$H/levels
for s in 0 1 2; do
    out=$P/door-s$s
    [[ -f "$out/receipt.json" ]] || nice -n 10 build/flex/control/control train --output "$out" --seed $((7 + s)) --data "$P/data-door/data.bin" --policy build/flex/sim/chase-v1/train-d5-agg --categorical --mirror-augment --carry-cue --epochs 30 --batch 2 --checkpoint-every 10 > "$out.log" 2>&1
    [[ ! -f "$out/data.bin" ]] || { cmp -s "$out/data.bin" "$P/data-door/data.bin" && rm "$out/data.bin"; }
    [[ -f "$P/eval/score-door-s$s.json" ]] || bash "$H/evaluate.sh" "$P/eval" "door-s$s" "$out" --fetch --camera-pitch 82 > "$out.eval.log" 2>&1
    echo "door-s$s standard $(jq .meanDeliveriesPerMinute "$P/eval/score-door-s$s.json") free $(df -h --output=avail /home | tail -1)"
done
for s in 0 1 2; do PUPPYBOT_LEVELS="1 2 3 4 5" bash "$H/levels/score.sh" "$P" "door-s$s" "$P/door-s$s" --camera-pitch 82 > /dev/null; done
for L in 1 2 3 4 5; do echo "door L$L $(jq -s -c 'map(.meanDeliveriesPerMinute) | {runs:., mean:(add/length)}' "$P/eval-L$L/score-door-s0.json" "$P/eval-L$L/score-door-s1.json" "$P/eval-L$L/score-door-s2.json")"; done
for s in 0 1 2; do echo "door-s$s L5 split: $(python3 -I "$S/l5split.py" "$P"/eval-L5/door-s$s/*/99* | tr '\n' ' ')"; done
echo "== done $(date +%T)"
