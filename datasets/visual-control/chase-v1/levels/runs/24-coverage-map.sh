#!/usr/bin/env bash
# Coverage map: the exploring teacher (--explore-teacher, covers floor the camera has not seen) at pitch 82 with 3%
# DART noise, recording its robot-centred coverage map (--record-map); the data-early mix of 128 games on each of
# levels 0-4 and 256 on level 5. Students expl-s* imitate it as before, emap-s* also learn the map from their memory
# (--memory-map, training only). The teacher itself is scored too.
set -euo pipefail
cd /home/teppo/Work/my/puppybot
export PUPPYBOT_PROJECT=$PWD LD_LIBRARY_PATH=$PWD/build/flex/rocm-runtime
R=$PWD/build/flex/sim/levels-v1; H=$PWD/datasets/visual-control/chase-v1; P=$R/pitch82; S=$H/levels; D=$P/data-expl
echo "== exploring teacher games $(date +%T)"
PUPPYBOT_LEVELS="0 1 2 3 4" PUPPYBOT_CHASE_SHARDS=8 PUPPYBOT_CHASE_EPISODES=16 nice -n 10 bash "$S/collect.sh" "$P" expl 950000 --action-noise 3 --camera-pitch 82 --record-map
PUPPYBOT_LEVELS=5 PUPPYBOT_CHASE_SHARDS=8 PUPPYBOT_CHASE_EPISODES=32 nice -n 10 bash "$S/collect.sh" "$P" expl 950000 --action-noise 3 --camera-pitch 82 --record-map
echo "teacher training layouts L5: $(python3 -I "$S/l5cross.py" "$P"/expl-L5/shard-*/expert-*)"
[[ -f "$D/map.bin" ]] || "$R/map-aggregate" "$D" 300 0 $(ls "$P"/expl-L[0-5]/shard-?/data.bin) > /dev/null
echo "== students $(date +%T)"
for s in 0 1 2; do
    for kind in expl emap; do
        out=$P/$kind-s$s; map=(); [[ $kind == expl ]] || map=(--memory-map "$D/map.bin")
        [[ -f "$out/receipt.json" ]] || nice -n 10 build/flex/control/control train --output "$out" --seed $((7 + s)) --data "$D/data.bin" "${map[@]}" --policy build/flex/sim/chase-v1/train-d5-agg --categorical --mirror-augment --carry-cue --epochs 30 --batch 2 --checkpoint-every 10 > "$out.log" 2>&1
        [[ ! -f "$out/data.bin" ]] || { cmp -s "$out/data.bin" "$D/data.bin" && rm "$out/data.bin"; }
        [[ -f "$P/eval/score-$kind-s$s.json" ]] || bash "$H/evaluate.sh" "$P/eval" "$kind-s$s" "$out" --fetch --camera-pitch 82 > "$out.eval.log" 2>&1
        echo "$kind-s$s standard $(jq .meanDeliveriesPerMinute "$P/eval/score-$kind-s$s.json") last $(tail -1 "$out/curves.jsonl" | jq -c '{validationLoss,mapValidationLoss}')"
    done
done
for s in 0 1 2; do for kind in expl emap; do PUPPYBOT_LEVELS="1 2 3 4 5" bash "$S/score.sh" "$P" "$kind-s$s" "$P/$kind-s$s" --camera-pitch 82 > /dev/null; done; done
for kind in expl emap; do
    for L in 1 2 3 4 5; do echo "$kind L$L $(jq -s -c 'map(.meanDeliveriesPerMinute) | {runs:., mean:(add/length)}' "$P/eval-L$L/score-$kind-s0.json" "$P/eval-L$L/score-$kind-s1.json" "$P/eval-L$L/score-$kind-s2.json")"; done
    for s in 0 1 2; do echo "$kind-s$s L5: $(python3 -I "$S/l5cross.py" "$P"/eval-L5/$kind-s$s/*/99*)"; done
done
echo "== exploring teacher on the test games $(date +%T)"
PUPPYBOT_LEVELS="1 2 3 4 5" bash "$S/score.sh" "$P" explore-teacher teacher --camera-pitch 82 --explore-teacher
echo "explore-teacher L5: $(python3 -I "$S/l5cross.py" "$P"/eval-L5/explore-teacher/*/99*)"
echo "== done $(date +%T)"
