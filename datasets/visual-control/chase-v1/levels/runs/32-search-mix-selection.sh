#!/usr/bin/env bash
# On training-layout selection games, compare the more1 ensemble with one
# member replaced by hmap-s0 (diary 37). Keep the unseen test games for a
# later confirmation. Partial player directories are retained on failure.
set -euo pipefail
cd /home/teppo/Work/my/puppybot
export PUPPYBOT_PROJECT=$PWD LD_LIBRARY_PATH=$PWD/build/flex/rocm-runtime PUPPYBOT_CHASE_PARTS=2 PUPPYBOT_EVAL_SELECTION=1
H=$PWD/datasets/visual-control/chase-v1
P=$PWD/build/flex/sim/levels-v2/pitch82
O=$P/search-mix-selection
mkdir -p "$O"
inputs=(build/flex/control/control build/flex/control/simulator)
for model in more1-s0 more1-s1 more1-s2 hmap-s0; do
  inputs+=("$P/$model/weights.bin" "$P/$model/policy")
done
if [[ -f "$O/inputs.sha256" ]]; then
  sha256sum -c "$O/inputs.sha256"
else
  sha256sum "${inputs[@]}" > "$O/inputs.sha256"
fi
for name in baseline heatmix; do
  member="$P/more1-s2"
  [[ $name != heatmix ]] || member="$P/hmap-s0"
  if [[ ! -f "$O/score-$name.json" ]]; then
    bash "$H/evaluate.sh" "$O" "$name" "$P/more1-s0" --fetch --level 3 --camera-pitch 82 --ensemble "$P/more1-s1" --ensemble "$member" > "$O/$name.log" 2>&1
  fi
  jq -c '{player,games,meanDeliveriesPerMinute,meanBackForthShare,gamesMostlyBackForth}' "$O/score-$name.json"
done
sha256sum -c "$O/inputs.sha256"
