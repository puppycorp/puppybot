#!/usr/bin/env bash
# Search timer: as the early-s* students (data-early, same seeds) with --search-cue, so the carry-cue slot also
# says how long the robot has searched for the current brick (vd_search_cue); played with --search-cue as time-s*.
set -euo pipefail
cd /home/teppo/Work/my/puppybot
export PUPPYBOT_PROJECT=$PWD LD_LIBRARY_PATH=$PWD/build/flex/rocm-runtime
R=$PWD/build/flex/sim/levels-v1; H=$PWD/datasets/visual-control/chase-v1; P=$R/pitch82; S=$H/levels
echo "== students $(date +%T)"
for s in 0 1 2; do
    out=$P/time-s$s
    [[ -f "$out/receipt.json" ]] || nice -n 10 build/flex/control/control train --output "$out" --seed $((7 + s)) --data "$P/data-early/data.bin" --policy build/flex/sim/chase-v1/train-d5-agg --categorical --mirror-augment --carry-cue --search-cue --epochs 30 --batch 2 --checkpoint-every 10 > "$out.log" 2>&1
    [[ ! -f "$out/data.bin" ]] || { cmp -s "$out/data.bin" "$P/data-early/data.bin" && rm "$out/data.bin"; }
    [[ -f "$P/eval/score-time-s$s.json" ]] || bash "$H/evaluate.sh" "$P/eval" "time-s$s" "$out" --fetch --camera-pitch 82 --search-cue > "$out.eval.log" 2>&1
    echo "time-s$s standard $(jq .meanDeliveriesPerMinute "$P/eval/score-time-s$s.json")"
done
for s in 0 1 2; do PUPPYBOT_LEVELS="1 2 3 4 5" bash "$S/score.sh" "$P" "time-s$s" "$P/time-s$s" --camera-pitch 82 --search-cue > /dev/null; done
for L in 1 2 3 4 5; do echo "time L$L $(jq -s -c 'map(.meanDeliveriesPerMinute) | {runs:., mean:(add/length)}' "$P/eval-L$L/score-time-s0.json" "$P/eval-L$L/score-time-s1.json" "$P/eval-L$L/score-time-s2.json")"; done
for s in 0 1 2; do echo "time-s$s L5: $(python3 -I "$S/l5cross.py" "$P"/eval-L5/time-s$s/*/99*)"; done
echo "== done $(date +%T)"
