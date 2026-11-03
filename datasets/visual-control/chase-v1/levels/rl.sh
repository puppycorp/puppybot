#!/usr/bin/env bash
# Reinforcement learning by advantage-weighted regression, starting from the pitch-82 noisy-teacher student.
# Iteration k: the policy plays 288 games with sampled actions (32 per level 0-2, 64 per level 3-5), awr.py keeps
# rows with high advantage, and 2 epochs of training from the policy on those rows plus the 640 pitch-82 noisy
# teacher games (an anchor against drift) give the next one, scored deterministically.
# Usage: rl.sh FIRST LAST
# Written for the level numbering before 2 Nov 2026 (4 other room, 5 doorway drill); the current code swaps them.
set -euo pipefail
cd /home/teppo/Work/my/puppybot
export PUPPYBOT_PROJECT=$PWD LD_LIBRARY_PATH=$PWD/build/flex/rocm-runtime
R=$PWD/build/flex/sim/levels-v1; H=$PWD/datasets/visual-control/chase-v1; S=$H/levels
RL=$R/rl; mkdir -p "$RL"; [[ -e "$RL/p0" ]] || ln -s "$R/pitch82/dart-s2" "$RL/p0"
for ((k=$1; k<=$2; k++)); do
    P=$RL/p$((k - 1)); I=$RL/it$k; mkdir -p "$I"
    echo "== iteration $k $(date +%T)"
    flags=(--camera-pitch 82 --sample-actions)
    PUPPYBOT_LEVELS="0 1 2" PUPPYBOT_LEVELS_TEACHER=--sweep-teacher PUPPYBOT_CHASE_SHARDS=4 PUPPYBOT_CHASE_EPISODES=8 PUPPYBOT_CHASE_POLICY=$P \
        bash "$H/levels/collect.sh" "$I" g $((1100000 + k * 100000)) "${flags[@]}" | cut -d' ' -f1,2
    PUPPYBOT_LEVELS="3 4 5" PUPPYBOT_LEVELS_TEACHER=--sweep-teacher PUPPYBOT_CHASE_SHARDS=4 PUPPYBOT_CHASE_EPISODES=16 PUPPYBOT_CHASE_POLICY=$P \
        bash "$H/levels/collect.sh" "$I" g $((1100000 + k * 100000)) "${flags[@]}" | cut -d' ' -f1,2
    [[ -f "$I/g-L5/shard-3/rl.bin" ]] || python3 -I "$S/awr.py" 0.25 2 "$k" $(for L in 0 1 2 3 4 5; do for s in 0 1 2 3; do printf '%s=%s ' "$L" "$I/g-L$L/shard-$s/data.bin"; done; done)
    [[ -f "$I/data/data.bin" ]] || "$R/sweep-L4/aggregate" "$I/data" 300 0 $(ls "$I"/g-L?/shard-?/rl.bin) $(ls "$R"/pitch82/dart-L?/shard-?/data.bin) > /dev/null
    [[ -f "$I/train/receipt.json" ]] || nice -n 10 build/flex/control/control train --output "$I/train" --seed $((7 + k)) --data "$I/data/data.bin" --policy "$P" --categorical --mirror-augment --carry-cue --epochs 2 --batch 2 --checkpoint-every 1 --learning-rate-micros 200 > "$I/train.log" 2>&1
    [[ -d "$RL/p$k" ]] || bash "$H/levels/checkpoint.sh" "$I/train" 2 "$RL/p$k"
    [[ -f "$RL/eval/score-p$k.json" ]] || bash "$H/evaluate.sh" "$RL/eval" "p$k" "$RL/p$k" --fetch --camera-pitch 82 > "$RL/p$k.eval.log" 2>&1
    PUPPYBOT_LEVELS="3 4 5" bash "$H/levels/score.sh" "$RL" "p$k" "$RL/p$k" --camera-pitch 82 > /dev/null
    echo "p$k standard $(jq .meanDeliveriesPerMinute "$RL/eval/score-p$k.json") L3 $(jq .meanDeliveriesPerMinute "$RL/eval-L3/score-p$k.json") L4 $(jq .meanDeliveriesPerMinute "$RL/eval-L4/score-p$k.json") L5 $(jq .meanDeliveriesPerMinute "$RL/eval-L5/score-p$k.json") loss $(tail -1 "$I/train/curves.jsonl" | jq -c '[.trainingLoss,.validationLoss]')"
done
echo "== done $(date +%T)"
