#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$project/build/flex/sim/target-detach-v1"
out="$root/models"
old="$project/build/flex/sim/target-actor-v1"
labels="$project/build/flex/sim/memory-pose-v1/target-candidates-v1/targets"
[[ ! -e "$out" ]]
trap 'status=$?; printf "%s\n" "$status" > "$root/train.exit"' EXIT
printf '%s\n' "$BASHPID" > "$root/train.pid"
[[ -f "$old/models/target/first-after.bin" && "$(< "$project/build/flex/sim/memory-pose-v1/target-candidates-v1/run.exit")" == 0 ]]
cd "$project"
data="$project/build/flex/sim/late-search-v1/artifacts-v2/data172/data.bin"
[[ "$(/usr/bin/sha256sum "$data" | /usr/bin/cut -d' ' -f1)" == 05032e0eb2a4a98a7f0146db66195792b2c22fe3bda3138039e9c721bc69b284 ]]
[[ "$(/usr/bin/sha256sum "$labels/targets.bin" | /usr/bin/cut -d' ' -f1)" == 9846229a1a28aa77c7e8653d1bbe14dbe6185c27d90a46b77d68b5e1bf0e5294 ]]
/usr/bin/jq -e '.passed and .episodes==172 and .actorInputsUnchanged' "$root/preflight.json" >/dev/null
/usr/bin/jq -e '.passed and .parameters==375658' "$root/gradient-contracts/result.json" >/dev/null
/usr/bin/jq -e '.passed and .actionGradientIntoHeatHead==0 and .actionGradientIntoMerge>0 and .labelGradientIntoHeatHead>0' "$root/detach-gradient-contracts/result.json" >/dev/null
/usr/bin/jq -e '.passed and .zeroMergeAndInitialRawParity and .emptyCandidateBatchHasZeroTargetGradients and .continuationRequiresActorConnection and .exportedActorInputsUnchangedAndNativeForwardExact' "$root/data-contracts/result.json" >/dev/null
/usr/bin/sha256sum -c "$root/runtime.sha256" > "$root/runtime-checked.log"
/usr/bin/sha256sum -c "$root/recipes.sha256" > "$root/recipes-checked.log"
mkdir "$out"
cp -a "$root/runtime" "$out/runtime"
cp -a "$old/models/initial-policy" "$out/initial-policy"
cp -a "$old/models/native-path" "$out/native-path"
cp -a "$root/recipes" "$out/recipes"
cp "$root/publish" "$root/core-match" "$root/initial-parity" "$root/target-zero" "$out/"
export PATH="$out/native-path"
cd "$out/runtime"
./build/flex/control/control train --initial-policy "$out/initial-policy" --data "$data" --output "$out/target" --epochs 40 --batch 2 --learning-rate-micros 100 --seed 197 --checkpoint-every 1 --event-aux --target-heatmap "$labels" --heat-actor --heat-stop-gradient > "$out/target.log" 2>&1
"$out/core-match" "$old/models/target/initial.bin" "$out/target/initial.bin" "$out/initial-match.json"
/usr/bin/jq -e '.passed and .originalParameters==375658 and .extraTrainingParameters==0' "$out/initial-match.json" >/dev/null
/usr/bin/cmp "$old/models/target/initial.bin" "$out/target/initial.bin"
"$out/target-zero" "$out/target/initial.bin" --merge
/usr/bin/cmp "$old/models/target/first-order.bin" "$out/target/first-order.bin"
while [[ ! -f "$old/train.exit" ]];do kill -0 "$(< "$old/train.pid")" || { echo 'Heatmap control disappeared before completion';exit 1; };/usr/bin/sleep 5;done
[[ "$(< "$old/train.exit")" == 0 ]]
/usr/bin/cmp "$old/models/target/final-order.bin" "$out/target/final-order.bin"
cd "$project"
/usr/bin/sha256sum -c "$root/recipes.sha256" > "$root/recipes-after-training.log"
/usr/bin/sha256sum -c "$root/runtime.sha256" > "$root/runtime-after-training.log"
echo 'Gradient-separated heatmap actor trained; autonomous results are evaluated separately.'
