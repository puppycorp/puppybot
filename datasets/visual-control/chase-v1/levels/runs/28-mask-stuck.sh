#!/usr/bin/env bash
# The runs/27 students again on the kturn games with the teacher's back-and-forth unlabelled (levels/mask-stuck.py,
# away from the brick and the box; frames kept as input): data-kmask, students mtrw. New level numbering, root
# levels-v2.
set -euo pipefail
cd /home/teppo/Work/my/puppybot
export PUPPYBOT_PROJECT=$PWD LD_LIBRARY_PATH=$PWD/build/flex/rocm-runtime
R=$PWD/build/flex/sim/levels-v1; H=$PWD/datasets/visual-control/chase-v1; P=$PWD/build/flex/sim/levels-v2/pitch82; mkdir -p "$P"
S=$H/levels; K=$P/data-kturn; D=$P/data-kmask
if [[ ! -f "$D/mask.json" ]]; then
    mkdir -p "$D"; cp --reflink=always "$K/data.bin" "$K/map.bin" "$D/"
    python3 -I "$S/mask-stuck.py" "$D/data.bin" $(ls -d "$P"/kturn-L[0-5]/shard-?) > "$D/mask.json"
fi
cat "$D/mask.json"
echo "== students $(date +%T)"
for s in 0 1 2; do
    name=mtrw-s$s out=$P/mtrw-s$s
    [[ -f "$out/receipt.json" ]] || nice -n 10 build/flex/control/control train --output "$out" --seed $((7 + s)) --data "$D/data.bin" --memory-map "$D/map.bin" --transition-weight-one --policy build/flex/sim/chase-v1/train-d5-agg --categorical --mirror-augment --carry-cue --epochs 30 --batch 2 --checkpoint-every 10 > "$out.log" 2>&1
    [[ ! -f "$out/data.bin" ]] || { cmp -s "$out/data.bin" "$D/data.bin" && rm "$out/data.bin"; }
    [[ -f "$P/eval/score-$name.json" ]] || bash "$H/evaluate.sh" "$P/eval" "$name" "$out" --fetch --camera-pitch 82 > "$out.eval.log" 2>&1
    PUPPYBOT_LEVELS="1 2 3 4 5" bash "$S/score.sh" "$P" "$name" "$out" --camera-pitch 82 > /dev/null
    echo "$name standard $(jq -c '{d:.meanDeliveriesPerMinute,b:.meanBackForthShare}' "$P/eval/score-$name.json")"
    for L in 1 2 3 4 5; do echo "  L$L $(jq -c '{d:.meanDeliveriesPerMinute,b:.meanBackForthShare,g:.gamesMostlyBackForth}' "$P/eval-L$L/score-$name.json")"; done
    echo "  L4 $(python3 -I "$S/l5cross.py" "$P"/eval-L4/$name/*/99*)"
done
echo "== done $(date +%T)"
