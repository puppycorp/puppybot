#!/usr/bin/env bash
# Rebalanced door-early DAgger set: data-edag with 64 more noisy pitch-82 teacher games on normal placement (dartb-L0
# shards 0-3) in place of half the level-5 door-early games (shards 4-7), 960 games from 64 shards (the aggregator
# limit); three fresh students edagb-s*.
set -euo pipefail
cd /home/teppo/Work/my/puppybot
export PUPPYBOT_PROJECT=$PWD LD_LIBRARY_PATH=$PWD/build/flex/rocm-runtime
R=$PWD/build/flex/sim/levels-v1; H=$PWD/datasets/visual-control/chase-v1; P=$R/pitch82; S=$H/levels
echo "== normal-placement teacher games $(date +%T)"
nice -n 10 env PUPPYBOT_LEVELS=0 PUPPYBOT_LEVELS_TEACHER=--sweep-teacher PUPPYBOT_CHASE_SHARDS=8 PUPPYBOT_CHASE_EPISODES=16 bash "$H/levels/collect.sh" "$P" dartb 930000 --action-noise 3 --camera-pitch 82
[[ -f "$P/data-edagb/data.bin" ]] || "$R/sweep-L4/aggregate" "$P/data-edagb" 300 0 $(ls "$P"/dart-L[0-3]/shard-?/data.bin "$P"/dartb-L0/shard-[0-3]/data.bin "$P"/early-L4/shard-?/data.bin "$P"/early-L5/shard-[0-3]/data.bin "$P"/edag-L[45]/shard-?/data.bin) > /dev/null
echo "== students $(date +%T)"
for s in 0 1 2; do
    out=$P/edagb-s$s
    [[ -f "$out/receipt.json" ]] || nice -n 10 build/flex/control/control train --output "$out" --seed $((7 + s)) --data "$P/data-edagb/data.bin" --policy build/flex/sim/chase-v1/train-d5-agg --categorical --mirror-augment --carry-cue --epochs 30 --batch 2 --checkpoint-every 10 > "$out.log" 2>&1
    [[ ! -f "$out/data.bin" ]] || { cmp -s "$out/data.bin" "$P/data-edagb/data.bin" && rm "$out/data.bin"; }
    [[ -f "$P/eval/score-edagb-s$s.json" ]] || bash "$H/evaluate.sh" "$P/eval" "edagb-s$s" "$out" --fetch --camera-pitch 82 > "$out.eval.log" 2>&1
    echo "edagb-s$s standard $(jq .meanDeliveriesPerMinute "$P/eval/score-edagb-s$s.json")"
done
for s in 0 1 2; do PUPPYBOT_LEVELS="1 2 3 4 5" bash "$H/levels/score.sh" "$P" "edagb-s$s" "$P/edagb-s$s" --camera-pitch 82 > /dev/null; done
for L in 1 2 3 4 5; do echo "edagb L$L $(jq -s -c 'map(.meanDeliveriesPerMinute) | {runs:., mean:(add/length)}' "$P/eval-L$L/score-edagb-s0.json" "$P/eval-L$L/score-edagb-s1.json" "$P/eval-L$L/score-edagb-s2.json")"; done
for s in 0 1 2; do echo "edagb-s$s L5: $(python3 -I "$S/l5cross.py" "$P"/eval-L5/edagb-s$s/*/99*)"; done
echo "== done $(date +%T)"
