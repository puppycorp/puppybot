#!/usr/bin/env bash
# Doorway specialist for the handoff ensemble: a second door-early DAgger round, edag-s2 driving 64 level-4 and 64
# level-5 games at pitch 82 (edag2-L4, edag2-L5), in place of half the dart-L1 and dart-L2 games (shards 4-7) in
# data-edag: 1024 games from 64 shards; three students edag2-s*, scored alone and as the main policy of the
# --ensemble-until 35 mix with dart-s1 and dart-s2.
set -euo pipefail
cd /home/teppo/Work/my/puppybot
export PUPPYBOT_PROJECT=$PWD LD_LIBRARY_PATH=$PWD/build/flex/rocm-runtime
R=$PWD/build/flex/sim/levels-v1; H=$PWD/datasets/visual-control/chase-v1; P=$R/pitch82; S=$H/levels; E=$P/ensemble
echo "== edag-s2 drives, door-early teacher labels $(date +%T)"
PUPPYBOT_LEVELS="4 5" PUPPYBOT_LEVELS_TEACHER=--sweep-teacher PUPPYBOT_CHASE_SHARDS=4 PUPPYBOT_CHASE_EPISODES=16 PUPPYBOT_CHASE_POLICY=$P/edag-s2 \
    nice -n 10 bash "$H/levels/collect.sh" "$P" edag2 2400000 --camera-pitch 82 --door-pass --door-early
echo "student-driven L5: $(python3 -I "$S/l5cross.py" "$P"/edag2-L5/shard-*/expert-*)"
[[ -f "$P/data-edag2/data.bin" ]] || "$R/sweep-L4/aggregate" "$P/data-edag2" 300 0 $(ls "$P"/dart-L[03]/shard-?/data.bin "$P"/dart-L[12]/shard-[0-3]/data.bin "$P"/early-L[45]/shard-?/data.bin "$P"/edag-L[45]/shard-?/data.bin "$P"/edag2-L[45]/shard-?/data.bin) > /dev/null
echo "== students $(date +%T)"
for s in 0 1 2; do
    out=$P/edag2-s$s
    [[ -f "$out/receipt.json" ]] || nice -n 10 build/flex/control/control train --output "$out" --seed $((7 + s)) --data "$P/data-edag2/data.bin" --policy build/flex/sim/chase-v1/train-d5-agg --categorical --mirror-augment --carry-cue --epochs 30 --batch 2 --checkpoint-every 10 > "$out.log" 2>&1
    [[ ! -f "$out/data.bin" ]] || { cmp -s "$out/data.bin" "$P/data-edag2/data.bin" && rm "$out/data.bin"; }
    [[ -f "$P/eval/score-edag2-s$s.json" ]] || bash "$H/evaluate.sh" "$P/eval" "edag2-s$s" "$out" --fetch --camera-pitch 82 > "$out.eval.log" 2>&1
    echo "edag2-s$s standard $(jq .meanDeliveriesPerMinute "$P/eval/score-edag2-s$s.json")"
done
for s in 0 1 2; do PUPPYBOT_LEVELS="1 2 3 4 5" bash "$H/levels/score.sh" "$P" "edag2-s$s" "$P/edag2-s$s" --camera-pitch 82 > /dev/null; done
for L in 1 2 3 4 5; do echo "edag2 L$L $(jq -s -c 'map(.meanDeliveriesPerMinute) | {runs:., mean:(add/length)}' "$P/eval-L$L/score-edag2-s0.json" "$P/eval-L$L/score-edag2-s1.json" "$P/eval-L$L/score-edag2-s2.json")"; done
for s in 0 1 2; do echo "edag2-s$s L5: $(python3 -I "$S/l5cross.py" "$P"/eval-L5/edag2-s$s/*/99*)"; done
best=$(for s in 0 1 2; do echo "$(jq -s 'map(.meanDeliveriesPerMinute)|add' "$P"/eval-L[45]/score-edag2-s$s.json) $s"; done | sort -rn | head -1 | cut -d' ' -f2)
echo "== mix35 with edag2-s$best (best levels 4+5) $(date +%T)"
c=mix35e2; flags=(--camera-pitch 82 --ensemble "$P/dart-s1" --ensemble "$P/dart-s2" --ensemble-until 35)
export PUPPYBOT_CHASE_PARTS=2
[[ -f "$E/eval/score-$c.json" ]] || bash "$H/evaluate.sh" "$E/eval" "$c" "$P/edag2-s$best" --fetch "${flags[@]}" > "$E/$c.eval.log" 2>&1
PUPPYBOT_LEVELS="1 2 3 4 5" bash "$H/levels/score.sh" "$E" "$c" "$P/edag2-s$best" "${flags[@]}" > /dev/null
echo "$c standard $(jq .meanDeliveriesPerMinute "$E/eval/score-$c.json") $(for L in 1 2 3 4 5; do printf 'L%s %s ' $L "$(jq .meanDeliveriesPerMinute "$E/eval-L$L/score-$c.json")"; done)| $(python3 -I "$S/l5cross.py" "$E"/eval-L5/$c/*/99*)"
echo "== done $(date +%T)"
