#!/usr/bin/env bash
# Sequential GPU queue: size experiment, sweep students, memory recordings, checkpoint selection.
set -euo pipefail
cd /home/teppo/Work/my/puppybot
export PUPPYBOT_PROJECT=$PWD LD_LIBRARY_PATH=$PWD/build/flex/rocm-runtime
R=$PWD/build/flex/sim/levels-v1; H=$PWD/datasets/visual-control/chase-v1; S=$H/levels
best() { for s in 0 1 2; do printf '%s %s\n' "$(jq .meanDeliveriesPerMinute "$R/eval/score-$1-s$s.json")" "$1-s$s"; done | sort -gr | head -1 | cut -d' ' -f2; }
echo "== size $(date +%T)"
bash "$H/levels/size.sh" "$R"
echo "== sweep students $(date +%T)"
[[ -f "$R/data-sweep/data.bin" ]] || "$R/sweep-L4/aggregate" "$R/data-sweep" 300 0 $(for L in 0 1 2 3 4; do for k in 0 1 2 3 4 5 6 7; do printf '%s ' "$R/sweep-L$L/shard-$k/data.bin"; done; done)
[[ -f "$R/score-swp.json" ]] || PUPPYBOT_EVAL_FLAGS=--fetch bash "$H/seeds.sh" "$R" swp 3 --data "$R/data-sweep/data.bin" --policy build/flex/sim/chase-v1/train-d5-agg --categorical --mirror-augment --carry-cue --epochs 30 --batch 2 --checkpoint-every 10
echo "swp standard $(jq -c .deliveriesPerMinute "$R/score-swp.json")"
for s in 0 1 2; do PUPPYBOT_LEVELS="1 2 3 4 5" bash "$H/levels/score.sh" "$R" "swp-s$s" "$R/swp-s$s"; PUPPYBOT_LEVELS=5 bash "$H/levels/score.sh" "$R" "mix-s$s" "$R/mix-s$s"; done
echo "== memory recordings $(date +%T)"
# Untrained controls: the random starting weights of the from-scratch runs.
[[ -d "$R/init-small" ]] || bash "$H/levels/checkpoint.sh" "$R/small-s0" 0 "$R/init-small"
[[ -d "$R/init-large" ]] || bash "$H/levels/checkpoint.sh" "$R/large-s0" 0 "$R/init-large"
record() {  # NAME POLICY [flags]
    local name=$1 policy=$2; shift 2
    for L in 0 3 4; do
        level=(); [[ $L == 0 ]] || level=(--level $L)
        two=0; [[ $L != 4 ]] || two=1
        [[ -f "$R/memory-L$L/score-$name.json" ]] || PUPPYBOT_EVAL_TWO_ROOM=$two bash "$H/evaluate.sh" "$R/memory-L$L" "$name" "$policy" --fetch "${level[@]}" --record-memory "$@" > "$R/memory-L$L-$name.log" 2>&1
    done
}
record mix-s2 "$R/mix-s2"; record init-small "$R/init-small"; sw=$(best swp); record "$sw" "$R/$sw"
lg=$(best large); record "$lg" "$R/$lg" --large-model; record init-large "$R/init-large" --large-model
probe_dirs() { for n in "$@"; do printf '%s=%s,%s,%s\n' "$n" "$R/memory-L0/$n" "$R/memory-L3/$n" "$R/memory-L4/$n"; done; }
python3 -I "$S/probe.py" 128 $(probe_dirs mix-s2 "$sw" init-small)
python3 -I "$S/probe.py" 256 $(probe_dirs "$lg" init-large)
echo "== checkpoints $(date +%T)"
for m in mix-s0 mix-s1 mix-s2 swp-s0 swp-s1 swp-s2; do
    for e in 10 20 30; do
        [[ -d "$R/ckpt/$m-e$e" ]] || { mkdir -p "$R/ckpt"; bash "$H/levels/checkpoint.sh" "$R/$m" $e "$R/ckpt/$m-e$e"; }
        [[ -f "$R/ckpt/eval/score-$m-e$e.json" ]] || bash "$H/evaluate.sh" "$R/ckpt/eval" "$m-e$e" "$R/ckpt/$m-e$e" --fetch > "$R/ckpt/$m-e$e.log" 2>&1
    done
    echo "$m selected-epoch $(jq -s 'map(select(.selected))|last|.epoch' "$R/$m/curves.jsonl") final $(jq .meanDeliveriesPerMinute "$R/eval/score-$m.json") e10 $(jq .meanDeliveriesPerMinute "$R/ckpt/eval/score-$m-e10.json") e20 $(jq .meanDeliveriesPerMinute "$R/ckpt/eval/score-$m-e20.json") e30 $(jq .meanDeliveriesPerMinute "$R/ckpt/eval/score-$m-e30.json")"
done
echo "== done $(date +%T)"
