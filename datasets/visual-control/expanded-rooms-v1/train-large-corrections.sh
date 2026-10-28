#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
base="$project/build/flex/sim/expanded-rooms-v1"
root="$base/large-model-v1"
admission="$root/correction-admission-v1"
initial="$root/expanded-236"
runtime="$root/correction-v3/runtime"
out="$root/correction-training-v1"
[[ ! -e "$out" ]]
/usr/bin/mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
for job in "$admission/run" "$root/expanded-236-mirrored"; do
    while [[ ! -f "$job.exit" ]]; do
        [[ -f "$job.pid" ]] && kill -0 "$(< "$job.pid")" || { echo "$job ended without a status." >&2; exit 1; }
        /usr/bin/sleep 20
    done
    [[ "$(< "$job.exit")" == 0 ]] || { echo "$job failed; correction training not started." >&2; exit 1; }
done
data="$admission/expanded/data.bin"
targets="$admission/targets"
data_sha="$(/usr/bin/sha256sum "$data" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$data_sha" '.passed and .episodes>236 and .episodes<=256 and .dataSHA256==$sha and .existingDataBytePreserved and .existingTargetsBytePreserved and .newHistoriesIndependentlyAudited and .teacherLabelsTrainingOnly and .actorInputsUnchanged and (.studentAutonomousSuccessClaimed|not)' "$admission/coverage.json" > /dev/null
/usr/bin/jq -e --arg sha "$data_sha" '.passed and .sourceDataSHA256==$sha and .projectionAndPixelsIndependentlyRechecked and .visibilityHeuristicNotProvenSegmentation and .actorInputsUnchanged' "$targets/receipt.json" > /dev/null
/usr/bin/sha256sum "$data" "$targets/targets.bin" "$targets/receipt.json" "$admission/coverage.json" "$initial/weights.bin" "$initial/receipt.json" "$runtime/build/flex/control/control" "$runtime/build/flex/control/trainer" > "$out/inputs.sha256"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
export PATH="$base/unseen-benchmark-v2/native-path"
cd "$runtime"
./build/flex/control/control train --initial-policy "$initial" --data "$data" --output "$out/policy" --epochs 10 --batch 2 --learning-rate-micros 100 --seed 197 --checkpoint-every 1 --event-aux --target-heatmap "$targets" --heat-actor --heat-stop-gradient --large-model > "$out/training.log" 2>&1
/usr/bin/cmp "$initial/weights.bin" "$out/policy/seed.bin"
/usr/bin/jq -e --arg sha "$data_sha" '.memoryWidth==256 and .dataSHA256==$sha and .epochs==10 and .heatmapActorFeatures and .heatmapActorGradientDetached and (.taskFeedback|not)' "$out/policy/receipt.json" > /dev/null
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
