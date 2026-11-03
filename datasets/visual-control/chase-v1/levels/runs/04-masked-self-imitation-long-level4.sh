#!/usr/bin/env bash
# Item 5 retry with noisy steps left unlabelled, then item 8: level 4 with 512-step games.
set -euo pipefail
cd /home/teppo/Work/my/puppybot
export PUPPYBOT_PROJECT=$PWD LD_LIBRARY_PATH=$PWD/build/flex/rocm-runtime
R=$PWD/build/flex/sim/levels-v1; H=$PWD/datasets/visual-control/chase-v1; A=$R/sweep-L4/aggregate; S=$H/levels
mkdir -p "$R/h512"
echo "== level 4 in 512-step games $(date +%T)"
export PUPPYBOT_CHASE_HORIZON=512
PUPPYBOT_LEVELS=4 bash "$H/levels/score.sh" "$R/h512" sweep teacher --sweep-teacher
for m in dart-s2 more-s1; do PUPPYBOT_LEVELS=4 bash "$H/levels/score.sh" "$R/h512" "$m" "$R/$m"; done
for m in sweep dart-s2 more-s1; do jq -c --arg m "$m" '{m:$m,d:.meanDeliveriesPerMinute,g:.gamesWithADelivery}' "$R/h512/eval-L4/score-$m.json"; done
echo "== done $(date +%T)"
