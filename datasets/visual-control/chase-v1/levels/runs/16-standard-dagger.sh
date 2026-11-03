#!/usr/bin/env bash
# DAgger on normal placement: the collapsed seeds edag-s0 and edag-s1 each drive 64 level-0 games at pitch 82 while
# the sweep teacher labels every step (sdag0-L0, sdag1-L0), in place of half the dart-L0 and dart-L1 teacher games
# (shards 4-7) in data-edag: 1024 games from 64 shards; three fresh students sdag-s*.
set -euo pipefail
cd /home/teppo/Work/my/puppybot
export PUPPYBOT_PROJECT=$PWD LD_LIBRARY_PATH=$PWD/build/flex/rocm-runtime
R=$PWD/build/flex/sim/levels-v1; H=$PWD/datasets/visual-control/chase-v1; P=$R/pitch82; S=$H/levels
for s in 0 1; do
    echo "== edag-s$s drives normal placement, teacher labels $(date +%T)"
    PUPPYBOT_LEVELS=0 PUPPYBOT_LEVELS_TEACHER=--sweep-teacher PUPPYBOT_CHASE_SHARDS=4 PUPPYBOT_CHASE_EPISODES=16 PUPPYBOT_CHASE_POLICY=$P/edag-s$s \
        nice -n 10 bash "$H/levels/collect.sh" "$P" sdag$s $((2200000 + s * 100000)) --camera-pitch 82
done
python3 -I "$S/confusion.py" "$P"/sdag[01]-L0/shard-?/data.bin
[[ -f "$P/data-sdag/data.bin" ]] || "$R/sweep-L4/aggregate" "$P/data-sdag" 300 0 $(ls "$P"/dart-L[01]/shard-[0-3]/data.bin "$P"/dart-L[23]/shard-?/data.bin "$P"/early-L[45]/shard-?/data.bin "$P"/edag-L[45]/shard-?/data.bin "$P"/sdag[01]-L0/shard-?/data.bin) > /dev/null
echo "== students $(date +%T)"
for s in 0 1 2; do
    out=$P/sdag-s$s
    [[ -f "$out/receipt.json" ]] || nice -n 10 build/flex/control/control train --output "$out" --seed $((7 + s)) --data "$P/data-sdag/data.bin" --policy build/flex/sim/chase-v1/train-d5-agg --categorical --mirror-augment --carry-cue --epochs 30 --batch 2 --checkpoint-every 10 > "$out.log" 2>&1
    [[ ! -f "$out/data.bin" ]] || { cmp -s "$out/data.bin" "$P/data-sdag/data.bin" && rm "$out/data.bin"; }
    [[ -f "$P/eval/score-sdag-s$s.json" ]] || bash "$H/evaluate.sh" "$P/eval" "sdag-s$s" "$out" --fetch --camera-pitch 82 > "$out.eval.log" 2>&1
    echo "sdag-s$s standard $(jq .meanDeliveriesPerMinute "$P/eval/score-sdag-s$s.json")"
done
for s in 0 1 2; do PUPPYBOT_LEVELS="1 2 3 4 5" bash "$H/levels/score.sh" "$P" "sdag-s$s" "$P/sdag-s$s" --camera-pitch 82 > /dev/null; done
for L in 1 2 3 4 5; do echo "sdag L$L $(jq -s -c 'map(.meanDeliveriesPerMinute) | {runs:., mean:(add/length)}' "$P/eval-L$L/score-sdag-s0.json" "$P/eval-L$L/score-sdag-s1.json" "$P/eval-L$L/score-sdag-s2.json")"; done
for s in 0 1 2; do echo "sdag-s$s L5: $(python3 -I "$S/l5cross.py" "$P"/eval-L5/sdag-s$s/*/99*)"; done
echo "== done $(date +%T)"
