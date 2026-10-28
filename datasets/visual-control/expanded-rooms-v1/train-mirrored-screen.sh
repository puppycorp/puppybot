#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
base="$project/build/flex/sim/expanded-rooms-v1"
root="$base/large-model-v1"
out="$root/mirrored-16"
data="$base/return-quick-v1/merged-16/data.bin"
labels="$base/return-quick-v1/targets"
[[ ! -e "$out" && ! -e "$root/mirrored-16.exit" ]]
trap 'status=$?; printf "%s\n" "$status" > "$root/mirrored-16.exit"' EXIT
cd "$root/workspace"
/usr/bin/sha256sum -c "$root/comparison-inputs.sha256" > "$root/mirrored-16-integrity-before.log"
export PATH="$base/unseen-benchmark-v2/native-path"
../runtime/control train --data "$data" --output "$out" --epochs 20 --batch 2 --learning-rate-micros 100 --seed 197 --checkpoint-every 1 --from-scratch --categorical --event-aux --target-heatmap "$labels" --heat-actor --heat-stop-gradient --mirror-augment --large-model > "$root/mirrored-16.log" 2>&1
/usr/bin/cmp "$root/large/initial.bin" "$out/initial.bin"
/usr/bin/jq -e '.memoryWidth==256 and .sequenceMirrorAugmentation and .heatmapActorFeatures and .fromScratch' "$out/receipt.json" > /dev/null
/usr/bin/sha256sum -c "$root/comparison-inputs.sha256" > "$root/mirrored-16-integrity-after.log"
export PUPPYBOT_POLICY="$out"
export PUPPYBOT_SCREEN_OUTPUT="$root/mirrored-16-screen"
/usr/bin/bash "$root/source/datasets/screen-large-model.sh"
