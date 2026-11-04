#!/usr/bin/env bash
# Door-pass teacher data: noisy sweep-teacher games with --door-pass on levels 4 (128) and 5 (256) at pitch 82, on the
# seeds of dart-L4/L5, plus dart-L0..3; three students against door-s* (same games, grid-route doorways).
set -euo pipefail
cd /home/teppo/Work/my/puppybot
export PUPPYBOT_PROJECT=$PWD LD_LIBRARY_PATH=$PWD/build/flex/rocm-runtime
R=$PWD/build/flex/sim/levels-v1; H=$PWD/datasets/visual-control/chase-v1; P=$R/pitch82; S=$H/levels
echo "== door-pass teacher games $(date +%T)"
nice -n 10 env PUPPYBOT_LEVELS=4 PUPPYBOT_LEVELS_TEACHER=--sweep-teacher PUPPYBOT_CHASE_SHARDS=8 PUPPYBOT_CHASE_EPISODES=16 bash "$H/levels/collect.sh" "$P" pass 910000 --action-noise 3 --camera-pitch 82 --door-pass
nice -n 10 env PUPPYBOT_LEVELS=5 PUPPYBOT_LEVELS_TEACHER=--sweep-teacher PUPPYBOT_CHASE_SHARDS=8 PUPPYBOT_CHASE_EPISODES=32 bash "$H/levels/collect.sh" "$P" pass 910000 --action-noise 3 --camera-pitch 82 --door-pass
echo "teacher training layouts L5: $(python3 -I "$S/l5cross.py" "$P"/pass-L5/shard-*/expert-*)"
[[ -f "$P/data-pass/data.bin" ]] || "$R/sweep-L4/aggregate" "$P/data-pass" 300 0 $(ls "$P"/dart-L[0-3]/shard-?/data.bin "$P"/pass-L[45]/shard-?/data.bin) > /dev/null
echo "== students $(date +%T)"
for s in 0 1 2; do
    out=$P/pass-s$s
    [[ -f "$out/receipt.json" ]] || nice -n 10 build/flex/control/control train --output "$out" --seed $((7 + s)) --data "$P/data-pass/data.bin" --policy build/flex/sim/chase-v1/train-d5-agg --categorical --mirror-augment --carry-cue --epochs 30 --batch 2 --checkpoint-every 10 > "$out.log" 2>&1
    [[ ! -f "$out/data.bin" ]] || { cmp -s "$out/data.bin" "$P/data-pass/data.bin" && rm "$out/data.bin"; }
    [[ -f "$P/eval/score-pass-s$s.json" ]] || bash "$H/evaluate.sh" "$P/eval" "pass-s$s" "$out" --fetch --camera-pitch 82 > "$out.eval.log" 2>&1
    echo "pass-s$s standard $(jq .meanDeliveriesPerMinute "$P/eval/score-pass-s$s.json")"
done
for s in 0 1 2; do PUPPYBOT_LEVELS="1 2 3 4 5" bash "$H/levels/score.sh" "$P" "pass-s$s" "$P/pass-s$s" --camera-pitch 82 > /dev/null; done
for L in 1 2 3 4 5; do echo "pass L$L $(jq -s -c 'map(.meanDeliveriesPerMinute) | {runs:., mean:(add/length)}' "$P/eval-L$L/score-pass-s0.json" "$P/eval-L$L/score-pass-s1.json" "$P/eval-L$L/score-pass-s2.json")"; done
for s in 0 1 2; do echo "pass-s$s L5: $(python3 -I "$S/l5cross.py" "$P"/eval-L5/pass-s$s/*/99*)"; done
echo "== done $(date +%T)"
