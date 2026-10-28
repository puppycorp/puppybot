#!/usr/bin/env bash
set -euo pipefail

project="${PUPPYBOT_PROJECT:?Project root is required}"
base="$project/build/flex/sim/expanded-rooms-v1"
root="$base/large-model-v1"
out="$root/expanded-236-mirrored"
data="$base/return-admission-v1/merged-7/data.bin"
labels="$base/return-labels-v1/targets"
initial="$root/large"
[[ ! -e "$out" && ! -e "$root/expanded-236-mirrored.exit" ]]
trap 'status=$?; printf "%s\n" "$status" > "$root/expanded-236-mirrored.exit"' EXIT
printf '%s\n' "$BASHPID" > "$root/expanded-236-mirrored.pid"
while [[ ! -f "$root/expanded-236.exit" ]]; do
    [[ -f "$root/expanded-236.pid" ]] && kill -0 "$(< "$root/expanded-236.pid")" || { echo 'Unmirrored training exited without a status.' >&2; exit 1; }
    /usr/bin/sleep 20
done
[[ "$(< "$root/expanded-236.exit")" == 0 ]] || { echo 'Unmirrored training failed; no mirrored comparison started.' >&2; exit 1; }
sha="$(/usr/bin/sha256sum "$data" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$sha" '.passed and .episodes==236 and .fittingHistories==181 and .validationHistories==55 and .dataSHA256==$sha and .allNewTripsIndependentlyAudited' "$base/return-admission-v1/coverage.json" > /dev/null
/usr/bin/jq -e --arg sha "$sha" '.passed and .sourceDataSHA256==$sha and .episodes==236 and .actorInputsUnchanged' "$labels/receipt.json" > /dev/null
cd "$root/workspace"
/usr/bin/sha256sum -c "$root/comparison-inputs.sha256" > "$root/mirrored-integrity-before.log"
export PATH="$base/unseen-benchmark-v2/native-path"
../runtime/control train --initial-policy "$initial" --data "$data" --output "$out" --epochs 20 --batch 2 --learning-rate-micros 100 --seed 197 --checkpoint-every 1 --event-aux --target-heatmap "$labels" --heat-actor --heat-stop-gradient --mirror-augment --large-model > "$root/expanded-236-mirrored.log" 2>&1
/usr/bin/cmp "$initial/weights.bin" "$out/seed.bin"
/usr/bin/jq -e '.memoryWidth==256 and .sequenceMirrorAugmentation and .heatmapActorFeatures and .heatmapActorGradientDetached and .epochs==20 and (.taskFeedback|not)' "$out/receipt.json" > /dev/null
/usr/bin/sha256sum -c "$root/comparison-inputs.sha256" > "$root/mirrored-integrity-after.log"
[[ "$(/usr/bin/sha256sum "$data" | /usr/bin/cut -d' ' -f1)" == "$sha" ]]
