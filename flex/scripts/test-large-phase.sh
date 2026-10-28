#!/usr/bin/env bash
set -euo pipefail
project="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$project"
output="${1:?New output directory required}"
mkdir "$output"
output="$(cd "$output" && pwd)"
build/flex/control/pose-fixtures "$output/data"
build/flex/control/target-fixtures "$output/data/data.bin" "$output/data/mirrored-data.bin" "$output/targets"
args=(--data "$output/data/data.bin" --batch 1 --learning-rate-micros 100 --seed 7 --event-aux --target-heatmap "$output/targets/target-0" --heat-actor --large-model)
build/flex/control/control train "${args[@]}" --output "$output/original" --epochs 1 --from-scratch --categorical > "$output/original.log" 2>&1
build/flex/control/control train "${args[@]}" --output "$output/gated-initial" --epochs 0 --initial-policy "$output/original" --phase-gated > "$output/gated-initial.log" 2>&1
jq -e '.memoryWidth==256 and .phaseGatedNavigation and .heatmapActorFeatures and .actionCodec=="joint-seven-phase-v1" and (.taskFeedback|not)' "$output/gated-initial/receipt.json" > /dev/null
build/flex/control/large-phase-initial-tests "$output/original" "$output/gated-initial" "$output/data/data.bin" "$output/initial-parity" > "$output/initial-parity.log"
jq -e '.passed and .framesCompared==8 and .maximumLogitDifference<0.00001 and .maximumMemoryDifference==0 and .actionsIdentical and .actorInputsUnchanged' "$output/initial-parity/result.json" > /dev/null
build/flex/control/control train "${args[@]}" --output "$output/gated-trained" --epochs 1 --initial-policy "$output/gated-initial" > "$output/gated-trained.log" 2>&1
jq -e '.memoryWidth==256 and .phaseGatedNavigation and .heatmapActorFeatures and (.taskFeedback|not)' "$output/gated-trained/receipt.json" > /dev/null
if cmp -s "$output/gated-trained/initial.bin" "$output/gated-trained/first-after.bin"; then echo 'Large gated model did not update.' >&2; exit 1; fi
build/flex/control/large-forward-tests "$output/gated-trained" "$output/data/data.bin" "$output/forward" > "$output/forward.log"
jq -e '.passed and .logitMaxAbsError<0.00001 and .memoryMaxAbsError<0.00001 and .resetBitIdentical' "$output/forward/result.json" > /dev/null
build/flex/control/control run --policy "$output/gated-trained" --output "$output/run" --episodes 1 --seed 110330 --horizon 12 --large-model > "$output/run.log" 2>&1
build/flex/control/control verify --run "$output/run/110330" --policy "$output/run/policy" --output "$output/replay" --large-model > "$output/replay.log" 2>&1
jq -e '.passed and .commandReplayMaxAbsError==0 and .taskEventHintAbsent' "$output/replay/result.json" > /dev/null
echo 'Large learned phase gate preserves its parent, trains, exports and replays.'
