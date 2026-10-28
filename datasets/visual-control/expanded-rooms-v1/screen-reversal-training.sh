#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
base="$project/build/flex/sim/expanded-rooms-v1"
root="$base/large-model-v1"
admission="$root/return-cohort-admission-v2"
initial="$root/expanded-236-mirrored"
runtime="$root/reversal-tests-v2/runtime"
source="$root/source/reversal-screen-v1"
out="$root/reversal-screen-v1"
[[ ! -e "$out" ]]
/usr/bin/mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
[[ "$(< "$admission/run.exit")" == 0 && "$(< "$root/expanded-236-mirrored.exit")" == 0 ]]
data="$admission/expanded/data.bin"; targets="$admission/targets"
data_sha="$(/usr/bin/sha256sum "$data" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$data_sha" '.passed and .episodes==264 and .fittingHistories==195 and .validationHistories==69 and .studentReturnActionsReplayed==480 and .dataSHA256==$sha and .existingDataBytePreserved and .existingTargetsBytePreserved and .newHistoriesIndependentlyAudited and .actorInputsUnchanged' "$admission/coverage.json" > /dev/null
/usr/bin/sha256sum "$data" "$targets/targets.bin" "$targets/receipt.json" "$admission/coverage.json" "$initial/weights.bin" "$initial/receipt.json" "$runtime/build/flex/control/control" "$runtime/build/flex/control/trainer" "$source/screen-large-model.sh" "$source/diagnose-return-progress.sh" > "$out/inputs.sha256"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
export PATH="$base/unseen-benchmark-v2/native-path"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1 PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
cd "$runtime"
for arm in plain penalty; do
    extra=(); if [[ "$arm" == penalty ]]; then extra+=(--reversal-penalty-milli 1000); fi
    ./build/flex/control/control train --initial-policy "$initial" --data "$data" --output "$out/$arm-policy" --epochs 1 --batch 2 --learning-rate-micros 100 --seed 197 --checkpoint-every 1 --event-aux --target-heatmap "$targets" --heat-actor --heat-stop-gradient --mirror-augment --large-model "${extra[@]}" > "$out/$arm-training.log" 2>&1
    /usr/bin/cmp "$initial/weights.bin" "$out/$arm-policy/seed.bin"
    /usr/bin/jq -e --arg sha "$data_sha" '.memoryWidth==256 and .dataSHA256==$sha and .epochs==1 and .sequenceMirrorAugmentation and .heatmapActorFeatures and .heatmapActorGradientDetached and (.taskFeedback|not)' "$out/$arm-policy/receipt.json" > /dev/null
    /usr/bin/jq -se 'last | .epoch==1 and .optimizerSteps==98' "$out/$arm-policy/curves.jsonl" > /dev/null
done
/usr/bin/cmp "$out/plain-policy/initial.bin" "$out/penalty-policy/initial.bin"
/usr/bin/cmp "$out/plain-policy/first-order.bin" "$out/penalty-policy/first-order.bin"
/usr/bin/cmp "$out/plain-policy/first-mirror-mask.bin" "$out/penalty-policy/first-mirror-mask.bin"
/usr/bin/jq -e 'has("reversalPenaltyMilli")|not' "$out/plain-policy/receipt.json" > /dev/null
/usr/bin/jq -e '.reversalPenaltyMilli==1000' "$out/penalty-policy/receipt.json" > /dev/null
/usr/bin/jq -n --slurpfile a "$out/plain-policy/curves.jsonl" --slurpfile b "$out/penalty-policy/curves.jsonl" '$a[0].trainingLoss==$b[0].trainingLoss and $a[0].validationLoss==$b[0].validationLoss' | /usr/bin/jq -e . > /dev/null
for arm in plain penalty; do
    PUPPYBOT_POLICY="$out/$arm-policy" PUPPYBOT_SCREEN_OUTPUT="$out/$arm-screen" PUPPYBOT_SCREEN_CASES=observed /usr/bin/bash "$source/screen-large-model.sh" > "$out/$arm-screen.log" 2>&1
    for index in 2 15 16 17; do
        run="$out/$arm-screen/$index"; seed=$((9960000+index))
        if /usr/bin/jq -e '.rows[0].found' "$run/summary.json" > /dev/null; then
            /usr/bin/bash "$source/diagnose-return-progress.sh" "$run/$seed" "$run/verified/result.json" "$run/return-diagnostic.json"
        fi
    done
done
/usr/bin/jq -n --slurpfile plain "$out/plain-screen/summary.json" --slurpfile penalty "$out/penalty-screen/summary.json" '{exploratory:true,selectionNote:"Two cases were selected because an earlier model reached the brick; these are development cases.",episodesPerModel:4,optimizerStepsPerModel:98,baseline:$plain[0],penalty:$penalty[0],independentFinalHoldout:false,automaticPromotion:false}' > "$out/comparison.json"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
