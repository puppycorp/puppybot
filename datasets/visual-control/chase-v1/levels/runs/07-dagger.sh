#!/usr/bin/env bash
# DAgger at pitch 82: dart-s2 drives 288 games (32 on each of levels 0-2, 64 on each of levels 3-5) while the sweep
# teacher labels every step, then three seeds fine-tune dart-s2 on them for 10 epochs (lean on disk: each training
# copy of the data is dropped once it matches), scored on every level with level 5 split by brick room.
set -euo pipefail
cd /home/teppo/Work/my/puppybot
export PUPPYBOT_PROJECT=$PWD LD_LIBRARY_PATH=$PWD/build/flex/rocm-runtime
R=$PWD/build/flex/sim/levels-v1; H=$PWD/datasets/visual-control/chase-v1; P=$R/pitch82; S=$H/levels
echo "== dart-s2 drives, teacher labels $(date +%T)"
PUPPYBOT_LEVELS="0 1 2" PUPPYBOT_LEVELS_TEACHER=--sweep-teacher PUPPYBOT_CHASE_SHARDS=8 PUPPYBOT_CHASE_EPISODES=4 PUPPYBOT_CHASE_POLICY=$P/dart-s2 \
    nice -n 10 bash "$H/levels/collect.sh" "$P" dag 1900000 --camera-pitch 82
PUPPYBOT_LEVELS="3 4 5" PUPPYBOT_LEVELS_TEACHER=--sweep-teacher PUPPYBOT_CHASE_SHARDS=8 PUPPYBOT_CHASE_EPISODES=8 PUPPYBOT_CHASE_POLICY=$P/dart-s2 \
    nice -n 10 bash "$H/levels/collect.sh" "$P" dag 1900000 --camera-pitch 82
echo "student-driven level 5: $(python3 -I "$S/l5cross.py" "$P"/dag-L5/shard-*/expert-*)"
[[ -f "$P/data-dag/data.bin" ]] || "$R/sweep-L4/aggregate" "$P/data-dag" 300 0 $(ls "$P"/dag-L?/shard-?/data.bin) > /dev/null
echo "free $(df -h --output=avail /home | tail -1)"
echo "== students $(date +%T)"
for s in 0 1 2; do
    out=$P/dag-s$s
    [[ -f "$out/receipt.json" ]] || nice -n 10 build/flex/control/control train --output "$out" --seed $((7 + s)) --data "$P/data-dag/data.bin" --policy "$P/dart-s2" --categorical --mirror-augment --carry-cue --epochs 10 --batch 2 --checkpoint-every 5 > "$out.log" 2>&1
    [[ ! -f "$out/data.bin" ]] || { cmp -s "$out/data.bin" "$P/data-dag/data.bin" && rm "$out/data.bin"; }
    [[ -f "$P/eval/score-dag-s$s.json" ]] || bash "$H/evaluate.sh" "$P/eval" "dag-s$s" "$out" --fetch --camera-pitch 82 > "$out.eval.log" 2>&1
    echo "dag-s$s standard $(jq .meanDeliveriesPerMinute "$P/eval/score-dag-s$s.json") free $(df -h --output=avail /home | tail -1)"
done
for s in 0 1 2; do PUPPYBOT_LEVELS="1 2 3 4 5" bash "$H/levels/score.sh" "$P" "dag-s$s" "$P/dag-s$s" --camera-pitch 82 > /dev/null; done
for L in 1 2 3 4 5; do echo "dag L$L $(jq -s -c 'map(.meanDeliveriesPerMinute) | {runs:., mean:(add/length)}' "$P/eval-L$L/score-dag-s0.json" "$P/eval-L$L/score-dag-s1.json" "$P/eval-L$L/score-dag-s2.json")"; done
for s in 0 1 2; do echo "dag-s$s L5: $(python3 -I "$S/l5cross.py" "$P"/eval-L5/dag-s$s/*/99*)"; done
echo "== done $(date +%T)"
