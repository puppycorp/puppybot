#!/usr/bin/env bash
set -euo pipefail
project="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$project"
output="${1:?New output directory required}"
mkdir "$output"
output="$(cd "$output" && pwd)"
build/flex/control/pose-fixtures "$output/data"
build/flex/control/target-fixtures "$output/data/data.bin" "$output/data/mirrored-data.bin" "$output/targets"
build/flex/control/control train --data "$output/data/data.bin" --output "$output/policy" --epochs 1 --batch 1 --learning-rate-micros 100 --seed 7 --from-scratch --categorical --event-aux --target-heatmap "$output/targets/target-0" --heat-actor --large-model > "$output/train.log" 2>&1
rg -Fq 'Parameters: 3063626' "$output/policy/training.log"
jq -e '.memoryWidth==256 and .imageSide==84 and .heatmapActorFeatures and .cameraEventAuxiliary and (.taskFeedback|not)' "$output/policy/receipt.json" > /dev/null
if cmp -s "$output/policy/initial.bin" "$output/policy/first-after.bin"; then echo 'Large policy optimizer did not change its weights.' >&2; exit 1; fi
sha="$(/usr/bin/sha256sum "$output/policy/weights.bin" | /usr/bin/cut -d' ' -f1)"
build/flex/control/large-shape-tests "$output/policy/weights.bin" "$sha"
build/flex/control/large-forward-tests "$output/policy" "$output/data/data.bin" "$output/forward" > "$output/forward.log" 2>&1
jq -e '.passed and .logitMaxAbsError==0 and .memoryMaxAbsError==0 and .resetBitIdentical' "$output/forward/result.json" > /dev/null
if build/flex/control/control run --policy "$output/policy" --output "$output/wrong-shape" --large-model --image-128 > "$output/wrong-shape.log" 2>&1; then echo 'Incompatible image and memory dimensions were accepted.' >&2; exit 1; fi
rg -Fq 'large model requires an 84x84' "$output/wrong-shape.log"
if build/flex/control/control run --policy "$output/policy" --output "$output/wrong-width" > "$output/wrong-width.log" 2>&1; then echo 'Large policy was accepted with the old memory width.' >&2; exit 1; fi
rg -Fq 'policy memory width mismatch' "$output/wrong-width.log"
echo 'Large policy training, inference parity and dimension guards passed.'
