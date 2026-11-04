#!/usr/bin/env bash
# Teacher fix: the exploring teacher now reverses three actions when its route meets a wall instead of rocking in
# place (entry 33). Score it on levels 1-3 (4 and 5 done), collect the runs/24 games again with the same seeds
# (data-exfix), then one seed of the map student four ways: as before (fmap), hidden drive feedback on a quarter of
# the sequences (fdrop), the reversal penalty (frev) and without the eightfold drive-change loss weight (ftrw).
set -euo pipefail
cd /home/teppo/Work/my/puppybot
export PUPPYBOT_PROJECT=$PWD LD_LIBRARY_PATH=$PWD/build/flex/rocm-runtime
R=$PWD/build/flex/sim/levels-v1; H=$PWD/datasets/visual-control/chase-v1; P=$R/pitch82; S=$H/levels; D=$P/data-exfix
echo "== fixed teacher on the test games $(date +%T)"
PUPPYBOT_LEVELS="1 2 3 4 5" bash "$S/score.sh" "$P" explore-commit teacher --camera-pitch 82 --explore-teacher
echo "== fixed teacher games $(date +%T)"
PUPPYBOT_LEVELS="0 1 2 3 4" PUPPYBOT_CHASE_SHARDS=8 PUPPYBOT_CHASE_EPISODES=16 nice -n 10 bash "$S/collect.sh" "$P" exfix 950000 --action-noise 3 --camera-pitch 82 --record-map
PUPPYBOT_LEVELS=5 PUPPYBOT_CHASE_SHARDS=8 PUPPYBOT_CHASE_EPISODES=32 nice -n 10 bash "$S/collect.sh" "$P" exfix 950000 --action-noise 3 --camera-pitch 82 --record-map
for L in 0 1 2 3 4 5; do echo "teacher training L$L: $(python3 -I "$S/pingpong.py" "$P"/exfix-L$L/shard-*/expert-*)"; done
[[ -f "$D/map.bin" ]] || "$R/map-aggregate" "$D" 300 0 $(ls "$P"/exfix-L[0-5]/shard-?/data.bin) > /dev/null
echo "== students $(date +%T)"
for kind in fmap fdrop frev ftrw; do
    out=$P/$kind-s0; extra=()
    [[ $kind != fdrop ]] || extra=(--drop-drive-feedback-milli 250)
    [[ $kind != frev ]] || extra=(--reversal-penalty-milli 1000)
    [[ $kind != ftrw ]] || extra=(--transition-weight-one)
    [[ -f "$out/receipt.json" ]] || nice -n 10 build/flex/control/control train --output "$out" --seed 7 --data "$D/data.bin" --memory-map "$D/map.bin" "${extra[@]}" --policy build/flex/sim/chase-v1/train-d5-agg --categorical --mirror-augment --carry-cue --epochs 30 --batch 2 --checkpoint-every 10 > "$out.log" 2>&1
    [[ ! -f "$out/data.bin" ]] || { cmp -s "$out/data.bin" "$D/data.bin" && rm "$out/data.bin"; }
    [[ -f "$P/eval/score-$kind-s0.json" ]] || bash "$H/evaluate.sh" "$P/eval" "$kind-s0" "$out" --fetch --camera-pitch 82 > "$out.eval.log" 2>&1
    PUPPYBOT_LEVELS="1 2 3 4 5" bash "$S/score.sh" "$P" "$kind-s0" "$out" --camera-pitch 82 > /dev/null
    echo "$kind-s0 standard $(jq -c '{d:.meanDeliveriesPerMinute,p:.meanPingPongShare}' "$P/eval/score-$kind-s0.json") last $(tail -1 "$out/curves.jsonl" | jq -c '{validationLoss,mapValidationLoss}')"
    for L in 1 2 3 4 5; do echo "  L$L $(jq -c '{d:.meanDeliveriesPerMinute,p:.meanPingPongShare,g:.gamesMostlyPingPong}' "$P/eval-L$L/score-$kind-s0.json")"; done
    echo "  L5 $(python3 -I "$S/l5cross.py" "$P"/eval-L5/$kind-s0/*/99*)"
done
echo "== done $(date +%T)"
