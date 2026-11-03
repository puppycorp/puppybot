#!/usr/bin/env bash
# Item 5 (self-imitation) and item 6 (staged curriculum). Strictly one GPU job at a time.
set -euo pipefail
cd /home/teppo/Work/my/puppybot
export PUPPYBOT_PROJECT=$PWD LD_LIBRARY_PATH=$PWD/build/flex/rocm-runtime
R=$PWD/build/flex/sim/levels-v1; H=$PWD/datasets/visual-control/chase-v1; A=$R/sweep-L4/aggregate
stats() {  # NAME
    jq -s --arg name "$1" 'def stats(f): (map(f)) as $v | ($v|add/length) as $m | {mean:$m,sd:($v|map((.-$m)*(.-$m))|add/(length-1)|sqrt),runs:$v};
      {configuration:$name,seeds:length,reachesPerMinute:stats(.meanReachesPerMinute),deliveriesPerMinute:stats(.meanDeliveriesPerMinute)}' \
      "$R/eval/score-$1-s0.json" "$R/eval/score-$1-s1.json" "$R/eval/score-$1-s2.json" > "$R/score-$1.json"
    echo "$1 standard $(jq -c .deliveriesPerMinute "$R/score-$1.json")"
}
levels() {  # NAME LEVELS
    for s in 0 1 2; do PUPPYBOT_LEVELS="$2" bash "$H/levels/score.sh" "$R" "$1-s$s" "$R/$1-s$s" > /dev/null; done
    for L in $2; do echo "$1 L$L $(jq -s -c 'map(.meanDeliveriesPerMinute) | {runs:., mean:(add/length)}' "$R/eval-L$L/score-$1-s0.json" "$R/eval-L$L/score-$1-s1.json" "$R/eval-L$L/score-$1-s2.json")"; done
}
train_eval() {  # NAME SEED FLAGS...: train one model unless present, then score it on the standard test
    local name=$1 s=$2; shift 2
    [[ -f "$R/$name-s$s/receipt.json" ]] || nice -n 10 build/flex/control/control train --output "$R/$name-s$s" --seed $((7 + s)) "$@" > "$R/$name-s$s.log" 2>&1
    [[ -f "$R/eval/score-$name-s$s.json" ]] || bash "$H/evaluate.sh" "$R/eval" "$name-s$s" "$R/$name-s$s" --fetch > "$R/$name-s$s.eval.log" 2>&1
}
sweep_shards() { for L in "$@"; do for k in 0 1 2 3 4 5 6 7; do printf '%s ' "$R/dart-L$L/shard-$k/data.bin"; done; done; }
student=$R/dart-s2
# Teacher games with 3% noise bursts (item 4) for level 5 as well.
nice -n 10 env PUPPYBOT_LEVELS=5 PUPPYBOT_LEVELS_TEACHER=--sweep-teacher PUPPYBOT_CHASE_SHARDS=8 PUPPYBOT_CHASE_EPISODES=16 bash "$H/levels/collect.sh" "$R" dart 910000 --action-noise 3
echo "== self-imitation collection $(date +%T)"
if [[ ! -f "$R/self-smoke/teacher-summary.json" ]]; then
    PUPPYBOT_CHASE_SHARDS=1 PUPPYBOT_CHASE_EPISODES=2 PUPPYBOT_CHASE_VALIDATION=1 PUPPYBOT_CHASE_POLICY=$student PUPPYBOT_CHASE_SEED=979000 \
        bash "$H/collect.sh" "$R/self-smoke" --fetch --sweep-teacher --self-imitate 200 --action-noise 3 > "$R/self-smoke.log" 2>&1
fi
cat "$R"/self-smoke/shard-0/*/result.json | jq -c '{controller,deliveries,noisySteps,selfImitationRows}'
PUPPYBOT_LEVELS="0 1 2 3 4 5" PUPPYBOT_LEVELS_TEACHER=--sweep-teacher PUPPYBOT_CHASE_SHARDS=4 PUPPYBOT_CHASE_EPISODES=16 PUPPYBOT_CHASE_POLICY=$student \
    bash "$H/levels/collect.sh" "$R" self 980000 --self-imitate 200 --action-noise 3
for L in 0 1 2 3 4 5; do echo "self L$L kept $(cat "$R"/self-L$L/shard-*/*/result.json | jq -s '{rows:(map(.selfImitationRows)|add),steps:(map(.steps)|add),deliveries:(map(.deliveriesPerMinute)|add/length)}' -c)"; done
echo "== self-imitation students $(date +%T)"
# Only games with a kept cycle (keep.py), so no batch is all weight 0.
[[ -f "$R/data-self/data.bin" ]] || "$A" "$R/data-self" 300 0 $(sweep_shards 0 1 2 3 4) $(ls "$R"/self-L?/shard-?/kept.bin)
for s in 0 1 2; do train_eval self "$s" --data "$R/data-self/data.bin" --policy "$student" --categorical --mirror-augment --carry-cue --epochs 15 --batch 2 --checkpoint-every 5; done
# Control: the same 15 further epochs on the noisy teacher games alone.
for s in 0 1 2; do train_eval more "$s" --data "$R/data-dart/data.bin" --policy "$student" --categorical --mirror-augment --carry-cue --epochs 15 --batch 2 --checkpoint-every 5; done
stats self; stats more; levels self "1 2 3 4 5"; levels more "1 2 3 4 5"
echo "== staged curriculum $(date +%T)"
[[ -f "$R/data-st1/data.bin" ]] || "$A" "$R/data-st1" 300 0 $(sweep_shards 0 1 2)
[[ -f "$R/data-st2/data.bin" ]] || "$A" "$R/data-st2" 300 0 $(sweep_shards 0 1 2 3)
[[ -f "$R/data-st3/data.bin" ]] || "$A" "$R/data-st3" 300 0 $(sweep_shards 0 1 2 3 4 5)
common=(--categorical --mirror-augment --carry-cue --batch 2 --checkpoint-every 5)
for s in 0 1 2; do
    # Equal game-epochs: 20 x 384, 15 x 512 and 10 x 768 games against 30 x 768 games mixed.
    [[ -f "$R/stage1-s$s/receipt.json" ]] || nice -n 10 build/flex/control/control train --output "$R/stage1-s$s" --seed $((7 + s)) --data "$R/data-st1/data.bin" --policy build/flex/sim/chase-v1/train-d5-agg --epochs 20 "${common[@]}" > "$R/stage1-s$s.log" 2>&1
    [[ -f "$R/stage2-s$s/receipt.json" ]] || nice -n 10 build/flex/control/control train --output "$R/stage2-s$s" --seed $((7 + s)) --data "$R/data-st2/data.bin" --policy "$R/stage1-s$s" --epochs 15 "${common[@]}" > "$R/stage2-s$s.log" 2>&1
    train_eval staged "$s" --data "$R/data-st3/data.bin" --policy "$R/stage2-s$s" --epochs 10 "${common[@]}"
    train_eval mixed "$s" --data "$R/data-st3/data.bin" --policy build/flex/sim/chase-v1/train-d5-agg --epochs 30 "${common[@]}"
done
stats staged; stats mixed; levels staged "1 2 3 4 5"; levels mixed "1 2 3 4 5"
echo "== done $(date +%T)"
