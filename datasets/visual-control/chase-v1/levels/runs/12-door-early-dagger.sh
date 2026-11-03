#!/usr/bin/env bash
# DAgger with the door-early teacher: early-s2 drives 64 level-4 and 64 level-5 games at pitch 82 while the sweep
# teacher (--door-pass --door-early) labels every step; added to data-early (1024 games) for three fresh students.
set -euo pipefail
cd /home/teppo/Work/my/puppybot
export PUPPYBOT_PROJECT=$PWD LD_LIBRARY_PATH=$PWD/build/flex/rocm-runtime
R=$PWD/build/flex/sim/levels-v1; H=$PWD/datasets/visual-control/chase-v1; P=$R/pitch82; S=$H/levels
echo "== early-s2 drives, door-early teacher labels $(date +%T)"
PUPPYBOT_LEVELS="4 5" PUPPYBOT_LEVELS_TEACHER=--sweep-teacher PUPPYBOT_CHASE_SHARDS=8 PUPPYBOT_CHASE_EPISODES=8 PUPPYBOT_CHASE_POLICY=$P/early-s2 \
    nice -n 10 bash "$H/levels/collect.sh" "$P" edag 2100000 --camera-pitch 82 --door-pass --door-early
echo "student-driven L5: $(python3 -I "$S/l5cross.py" "$P"/edag-L5/shard-*/expert-*)"
python3 -I "$S/confusion.py" "$P"/edag-L5/shard-*/data.bin
[[ -f "$P/data-edag/data.bin" ]] || "$R/sweep-L4/aggregate" "$P/data-edag" 300 0 $(ls "$P"/dart-L[0-3]/shard-?/data.bin "$P"/early-L[45]/shard-?/data.bin "$P"/edag-L[45]/shard-?/data.bin) > /dev/null
echo "== students $(date +%T)"
for s in 0 1 2; do
    out=$P/edag-s$s
    [[ -f "$out/receipt.json" ]] || nice -n 10 build/flex/control/control train --output "$out" --seed $((7 + s)) --data "$P/data-edag/data.bin" --policy build/flex/sim/chase-v1/train-d5-agg --categorical --mirror-augment --carry-cue --epochs 30 --batch 2 --checkpoint-every 10 > "$out.log" 2>&1
    [[ ! -f "$out/data.bin" ]] || { cmp -s "$out/data.bin" "$P/data-edag/data.bin" && rm "$out/data.bin"; }
    [[ -f "$P/eval/score-edag-s$s.json" ]] || bash "$H/evaluate.sh" "$P/eval" "edag-s$s" "$out" --fetch --camera-pitch 82 > "$out.eval.log" 2>&1
    echo "edag-s$s standard $(jq .meanDeliveriesPerMinute "$P/eval/score-edag-s$s.json")"
done
for s in 0 1 2; do PUPPYBOT_LEVELS="1 2 3 4 5" bash "$H/levels/score.sh" "$P" "edag-s$s" "$P/edag-s$s" --camera-pitch 82 > /dev/null; done
for L in 1 2 3 4 5; do echo "edag L$L $(jq -s -c 'map(.meanDeliveriesPerMinute) | {runs:., mean:(add/length)}' "$P/eval-L$L/score-edag-s0.json" "$P/eval-L$L/score-edag-s1.json" "$P/eval-L$L/score-edag-s2.json")"; done
for s in 0 1 2; do echo "edag-s$s L5: $(python3 -I "$S/l5cross.py" "$P"/eval-L5/edag-s$s/*/99*)"; done
echo "== done $(date +%T)"
