#!/usr/bin/env bash
# Round R of continued training: the students of the round before (round 0 is runs/29's ccont, 16 epochs past the
# masked kturn games' mtrw) trained 8 more epochs on the same data in one go, as cont was. Usage: 30-more-epochs.sh R
set -euo pipefail
cd /home/teppo/Work/my/puppybot
export PUPPYBOT_PROJECT=$PWD LD_LIBRARY_PATH=$PWD/build/flex/rocm-runtime
H=$PWD/datasets/visual-control/chase-v1; P=$PWD/build/flex/sim/levels-v2/pitch82; S=$H/levels; D=$P/data-kmask
R=$1; base=more$((R - 1)); (( R > 1 )) || base=ccont
echo "== round $R from $base $(date +%T)"
for s in 0 1 2; do
    name=more$R-s$s out=$P/more$R-s$s
    if [[ ! -f "$out/receipt.json" ]]; then
        rm -rf "$out"
        nice -n 10 build/flex/control/control train --output "$out" --seed $((7 + s + 100 * R)) --data "$D/data.bin" --memory-map "$D/map.bin" --transition-weight-one --policy "$P/$base-s$s" --categorical --mirror-augment --carry-cue --epochs 8 --batch 2 --checkpoint-every 8 > "$out.log" 2>&1
        [[ ! -f "$out/data.bin" ]] || { cmp -s "$out/data.bin" "$D/data.bin" && rm "$out/data.bin"; }
    fi
    [[ -f "$P/eval/score-$name.json" ]] || bash "$H/evaluate.sh" "$P/eval" "$name" "$out" --fetch --camera-pitch 82 > "$out.eval.log" 2>&1
    PUPPYBOT_LEVELS="1 2 3 4 5" bash "$S/score.sh" "$P" "$name" "$out" --camera-pitch 82 > /dev/null
    echo "$name standard $(jq -c '{d:.meanDeliveriesPerMinute,b:.meanBackForthShare}' "$P/eval/score-$name.json")"
    for L in 1 2 3 4 5; do echo "  L$L $(jq -c '{d:.meanDeliveriesPerMinute,b:.meanBackForthShare,g:.gamesMostlyBackForth}' "$P/eval-L$L/score-$name.json")"; done
    echo "  L4 $(python3 -I "$S/l5cross.py" "$P"/eval-L4/$name/*/99*)"
done
echo "== done $(date +%T)"
