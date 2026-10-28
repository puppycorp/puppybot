#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
base="$project/build/flex/sim/expanded-rooms-v1"
root="$base/large-model-v1"
admission="$root/return-cohort-admission-v2"
initial="$root/expanded-236-mirrored"
baseline="$root/return-cohort-equal-training-v1"
screen="$root/phase-screen-v1"
runtime="$root/phase-large-tests-v1/runtime"
source="$root/source/phase-screen-v1"
out="$root/phase-cohort-training-v1"
[[ ! -e "$out" ]]
/usr/bin/mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
for job in "$admission/run" "$baseline/run" "$screen/run"; do
    while [[ ! -f "$job.exit" ]]; do
        [[ -f "$job.pid" ]] && kill -0 "$(< "$job.pid")" || { echo "$job ended without a status." >&2; exit 1; }
        /usr/bin/sleep 20
    done
    [[ "$(< "$job.exit")" == 0 ]] || { echo "$job failed; gated training not started." >&2; exit 1; }
done
data="$admission/expanded/data.bin"; targets="$admission/targets"
data_sha="$(/usr/bin/sha256sum "$data" | /usr/bin/cut -d' ' -f1)"
initial_sha="$(/usr/bin/sha256sum "$initial/weights.bin" | /usr/bin/cut -d' ' -f1)"
target_sha="$(/usr/bin/sha256sum "$targets/targets.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$data_sha" '.passed and .episodes==264 and .fittingHistories==195 and .validationHistories==69 and .dataSHA256==$sha and .newHistoriesIndependentlyAudited and .teacherLabelsTrainingOnly and .actorInputsUnchanged' "$admission/coverage.json" > /dev/null
/usr/bin/jq -e --arg data "$data_sha" --arg initial "$initial_sha" --arg target "$target_sha" '.memoryWidth==256 and .dataSHA256==$data and .initialWeightsSHA256==$initial and .targetPositionTargetsSHA256==$target and .epochs==10 and .batch==2 and .learningRateMicros==100 and .seed==197 and .maxOptimizerSteps==960 and .sequenceMirrorAugmentation and .heatmapActorFeatures and .heatmapActorGradientDetached and (.phaseGatedNavigation|not) and (.taskFeedback|not) and (has("reversalPenaltyMilli")|not)' "$baseline/policy/receipt.json" > /dev/null
/usr/bin/jq -e '.passed and .maximumLogitDifference<0.00001 and .maximumMemoryDifference==0 and .actionsIdentical and .actorInputsUnchanged' "$screen/initial-parity/result.json" > /dev/null
/usr/bin/jq -se 'last | .epoch==10 and .optimizerSteps==960' "$baseline/policy/curves.jsonl" > /dev/null
/usr/bin/sha256sum "$data" "$targets/targets.bin" "$targets/receipt.json" "$initial/weights.bin" "$baseline/policy/receipt.json" "$baseline/policy/curves.jsonl" "$screen/gated-initial/weights.bin" "$screen/initial-parity/result.json" "$runtime/build/flex/control/control" "$runtime/build/flex/control/trainer" "$runtime/build/flex/control/policy-categorical-heat-phase-large" "$runtime/build/flex/control/large-forward-tests" > "$out/inputs.sha256"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
export PATH="$base/unseen-benchmark-v2/native-path"
cd "$runtime"
./build/flex/control/control train --initial-policy "$initial" --data "$data" --output "$out/policy" --epochs 10 --batch 2 --learning-rate-micros 100 --seed 197 --checkpoint-every 1 --event-aux --target-heatmap "$targets" --heat-actor --heat-stop-gradient --mirror-augment --large-model --max-optimizer-steps 960 --phase-gated > "$out/training.log" 2>&1
/usr/bin/cmp "$initial/weights.bin" "$out/policy/seed.bin"
/usr/bin/cmp "$screen/gated-initial/weights.bin" "$out/policy/initial.bin"
/usr/bin/cmp "$baseline/policy/first-order.bin" "$out/policy/first-order.bin"
/usr/bin/cmp "$baseline/policy/first-mirror-mask.bin" "$out/policy/first-mirror-mask.bin"
/usr/bin/jq -e --arg data "$data_sha" --arg initial "$initial_sha" --arg target "$target_sha" '.memoryWidth==256 and .dataSHA256==$data and .initialWeightsSHA256==$initial and .targetPositionTargetsSHA256==$target and .maxOptimizerSteps==960 and .phaseGatedNavigation and .sequenceMirrorAugmentation and .heatmapActorFeatures and .heatmapActorGradientDetached and (.taskFeedback|not)' "$out/policy/receipt.json" > /dev/null
/usr/bin/jq -se 'last | .epoch==10 and .optimizerSteps==960' "$out/policy/curves.jsonl" > /dev/null
./build/flex/control/large-forward-tests "$out/policy" "$source/fixture/data/data.bin" "$out/forward" > "$out/forward.log" 2>&1
/usr/bin/jq -e '.passed and .logitMaxAbsError<0.00001 and .memoryMaxAbsError<0.00001 and .resetBitIdentical' "$out/forward/result.json" > /dev/null
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
