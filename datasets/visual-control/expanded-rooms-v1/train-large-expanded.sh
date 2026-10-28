#!/usr/bin/env bash
set -euo pipefail

project="${PUPPYBOT_PROJECT:?Project root is required}"
base="$project/build/flex/sim/expanded-rooms-v1"
root="$base/large-model-v1"
out="$root/expanded-236"
data="$base/return-admission-v1/merged-7/data.bin"
labels="$base/return-labels-v1/targets"
initial="$root/large"
[[ ! -e "$out" && ! -e "$root/expanded-236.exit" ]]
trap 'status=$?; printf "%s\n" "$status" > "$root/expanded-236.exit"' EXIT
printf '%s\n' "$BASHPID" > "$root/expanded-236.pid"
sha="$(/usr/bin/sha256sum "$data" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$sha" '.passed and .episodes==236 and .fittingHistories==181 and .validationHistories==55 and .dataSHA256==$sha and .allNewTripsIndependentlyAudited' "$base/return-admission-v1/coverage.json" > /dev/null
/usr/bin/jq -e --arg sha "$sha" '.passed and .sourceDataSHA256==$sha and .episodes==236 and .actorInputsUnchanged' "$labels/receipt.json" > /dev/null
/usr/bin/jq -e '.memoryWidth==256 and .heatmapActorFeatures' "$initial/receipt.json" > /dev/null
cd "$root/workspace"
/usr/bin/sha256sum -c "$root/comparison-inputs.sha256" > "$root/expanded-integrity-before.log"
export PATH="$base/unseen-benchmark-v2/native-path"
../runtime/control train --initial-policy "$initial" --data "$data" --output "$out" --epochs 20 --batch 2 --learning-rate-micros 100 --seed 197 --checkpoint-every 1 --event-aux --target-heatmap "$labels" --heat-actor --heat-stop-gradient --large-model > "$root/expanded-236.log" 2>&1
/usr/bin/cmp "$initial/weights.bin" "$out/seed.bin"
/usr/bin/jq -e '.memoryWidth==256 and .heatmapActorFeatures and .heatmapActorGradientDetached and .epochs==20 and (.taskFeedback|not)' "$out/receipt.json" > /dev/null
/usr/bin/sha256sum -c "$root/comparison-inputs.sha256" > "$root/expanded-integrity-after.log"
[[ "$(/usr/bin/sha256sum "$data" | /usr/bin/cut -d' ' -f1)" == "$sha" ]]
