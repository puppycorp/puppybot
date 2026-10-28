#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
base="$project/build/flex/sim/expanded-rooms-v1"
root="$base/large-model-v1"
admission="$root/return-admission-v1"
baseline="$root/return-training-v1"
initial="$root/expanded-236-mirrored"
runtime="$root/focus-sampling-v1/runtime"
out="$root/focused-return-training-v1"
[[ ! -e "$out" ]]
/usr/bin/mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
while [[ ! -f "$baseline/run.exit" ]]; do
    [[ -f "$baseline/run.pid" ]] && kill -0 "$(< "$baseline/run.pid")" || { echo 'Baseline training ended without a status.' >&2; exit 1; }
    /usr/bin/sleep 20
done
[[ "$(< "$baseline/run.exit")" == 0 && "$(< "$admission/run.exit")" == 0 ]]
data="$admission/expanded/data.bin"
targets="$admission/targets"
data_sha="$(/usr/bin/sha256sum "$data" | /usr/bin/cut -d' ' -f1)"
initial_sha="$(/usr/bin/sha256sum "$initial/weights.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$data_sha" '.passed and .episodes==256 and .fittingHistories==191 and .validationHistories==65 and .dataSHA256==$sha and .existingDataBytePreserved and .existingTargetsBytePreserved and .newHistoriesIndependentlyAudited and .actorInputsUnchanged' "$admission/coverage.json" > /dev/null
/usr/bin/jq -e '.records[190].source==1 and .records[190].sourceIndex==0 and .records[190].fit and .records[255].source==1 and .records[255].sourceIndex==1 and (.records[255].fit|not)' "$admission/expanded/report.json" > /dev/null
/usr/bin/jq -e --arg sha "$initial_sha" '.studentWeightsSHA256==$sha and .studentMemoryWidth==256 and .studentBeginsAfterConsumption and .denseOracleLabels and .studentActions==30' "$root/return-correction-pilot-v1/runs/expert-0/supervision.json" > /dev/null
/usr/bin/jq -e --arg sha "$data_sha" --arg initial "$initial_sha" '.memoryWidth==256 and .dataSHA256==$sha and .initialWeightsSHA256==$initial and .epochs==10 and .batch==2 and .learningRateMicros==100 and .seed==197 and .sequenceMirrorAugmentation and .heatmapActorGradientDetached and (.taskFeedback|not)' "$baseline/policy/receipt.json" > /dev/null
/usr/bin/jq -se '.[-1].epoch==10 and .[-1].optimizerSteps==960' "$baseline/policy/curves.jsonl" > /dev/null
/usr/bin/sha256sum "$data" "$targets/targets.bin" "$targets/receipt.json" "$admission/coverage.json" "$admission/expanded/report.json" "$initial/weights.bin" "$baseline/policy/seed.bin" "$runtime/build/flex/control/control" "$runtime/build/flex/control/trainer" > "$out/inputs.sha256"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
export PATH="$base/unseen-benchmark-v2/native-path"
cd "$runtime"
./build/flex/control/control train --initial-policy "$initial" --data "$data" --output "$out/policy" --epochs 10 --batch 2 --learning-rate-micros 100 --seed 197 --checkpoint-every 1 --event-aux --target-heatmap "$targets" --heat-actor --heat-stop-gradient --mirror-augment --large-model --focus-history 190 --focus-copies 20 > "$out/training.log" 2>&1
/usr/bin/cmp "$baseline/policy/initial.bin" "$out/policy/initial.bin"
/usr/bin/jq -e --arg sha "$data_sha" '.memoryWidth==256 and .dataSHA256==$sha and .epochs==10 and .sequenceMirrorAugmentation and .focusHistory==190 and .focusCopiesPerEpoch==20 and (.taskFeedback|not)' "$out/policy/receipt.json" > /dev/null
/usr/bin/jq -se '.[-1].epoch==10 and .[-1].optimizerSteps==960' "$out/policy/curves.jsonl" > /dev/null
/usr/bin/od -An -v -t u8 "$out/policy/first-order.bin" | /usr/bin/awk '{for(i=1;i<=NF;i++){if(n<191){if($i==190)focus++}else if($i!=n)bad=1;n++}}END{exit !(n==256 && focus==20 && !bad)}'
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
