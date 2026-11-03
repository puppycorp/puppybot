#!/usr/bin/env bash
# The runs/28 students (mtrw, masked kturn games) trained 8 more epochs with a brick heatmap head on the first
# convolution, labelled from the teacher's camera detections (levels/heat-labels.py), against 8 more epochs without
# it. Aimed at the bricks students turn away from at the image edge after a delivery (entry 36). The heatmap turns
# off the fused training path (an epoch takes 180 s, not 27 s), and that path's GPU work stopped completing 11-12
# minutes into both first attempts. So training runs in 2-epoch chunks, each continuing the last one's weights
# (Adam restarts), with a chunk killed and retried when it runs over 20 minutes; the control (ccont) is chunked the
# same way. cont: the control trained 8 epochs in one go.
set -euo pipefail
cd /home/teppo/Work/my/puppybot
export PUPPYBOT_PROJECT=$PWD LD_LIBRARY_PATH=$PWD/build/flex/rocm-runtime
H=$PWD/datasets/visual-control/chase-v1; P=$PWD/build/flex/sim/levels-v2/pitch82; S=$H/levels; D=$P/data-kmask
[[ -f "$D/heat/receipt.json" ]] || python3 -I "$S/heat-labels.py" "$D/data.bin" "$D/heat" $(ls -d "$P"/kturn-L[0-5]/shard-?)
# Train in its own process group so a hung trainer child is killed with it.
chunk() {
    local out=$1 policy=$2 seed=$3 try; shift 3
    for try in 1 2 3; do
        [[ ! -f "$out/receipt.json" ]] || return 0
        rm -rf "$out"
        setsid nice -n 10 build/flex/control/control train --output "$out" --seed "$seed" --data "$D/data.bin" --memory-map "$D/map.bin" "$@" --transition-weight-one --policy "$policy" --categorical --mirror-augment --carry-cue --epochs 2 --batch 2 --checkpoint-every 2 > "$out.log" 2>&1 &
        local pid=$! waited=0
        while kill -0 $pid 2>/dev/null && (( waited < 1200 )); do sleep 10; waited=$((waited + 10)); done
        if kill -0 $pid 2>/dev/null; then echo "  $out stalled on try $try, retrying"; kill -KILL -- -$pid; wait $pid || true; continue; fi
        wait $pid || echo "  $out failed on try $try (see $out.log)"
    done
    [[ -f "$out/receipt.json" ]]
}
echo "== students $(date +%T)"
for kind in ccont hmap; do
    extra=(); [[ $kind != hmap ]] || extra=(--target-heatmap "$D/heat")
    for s in 0 1 2; do
        name=$kind-s$s out=$P/$kind-s$s policy=$P/mtrw-s$s
        if [[ ! -f "$out/receipt.json" ]]; then
            for c in 1 2 3 4; do chunk "$out.c$c" "$policy" $((7 + s + 10 * c)) "${extra[@]}"; policy=$out.c$c
                [[ ! -f "$policy/data.bin" ]] || { cmp -s "$policy/data.bin" "$D/data.bin" && rm "$policy/data.bin"; }; done
            mv "$P/$kind-s$s.c4" "$out"
        fi
        [[ -f "$P/eval/score-$name.json" ]] || bash "$H/evaluate.sh" "$P/eval" "$name" "$out" --fetch --camera-pitch 82 > "$out.eval.log" 2>&1
        PUPPYBOT_LEVELS="1 2 3 4 5" bash "$S/score.sh" "$P" "$name" "$out" --camera-pitch 82 > /dev/null
        echo "$name standard $(jq -c '{d:.meanDeliveriesPerMinute,b:.meanBackForthShare}' "$P/eval/score-$name.json")"
        for L in 1 2 3 4 5; do echo "  L$L $(jq -c '{d:.meanDeliveriesPerMinute,b:.meanBackForthShare,g:.gamesMostlyBackForth}' "$P/eval-L$L/score-$name.json")"; done
        echo "  L4 $(python3 -I "$S/l5cross.py" "$P"/eval-L4/$name/*/99*)"
    done
done
echo "== done $(date +%T)"
