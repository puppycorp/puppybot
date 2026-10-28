#!/usr/bin/env bash
# Same data, initialization and sampling; emphasize contact-recovery actions.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
base="$project/build/flex/sim/expanded-rooms-v1"
root="$base/large-model-v1"
admission="$root/coverage-v2-student-admission-v1"
baseline="$root/coverage-v2-student-training-v1"
initial="$root/expanded-236-mirrored"
runtime="$root/contact-weight-tests-v1/runtime"
source="$root/source/phase-screen-v1"
tests="$root/contact-weight-tests-v1"
gradients="$root/contact-weight-gradient-result-v1"
out="${PUPPYBOT_CONTACT_WEIGHT_SCREEN_OUT:?New output directory required}"
[[ ! -e "$out" ]]
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
for job in "$admission/run" "$baseline/run";do
    while [[ ! -f "$job.exit" ]];do [[ -f "$job.pid" ]] && kill -0 "$(< "$job.pid")" || { echo "$job ended without a status." >&2;exit 1; }; /usr/bin/sleep 20;done
    [[ "$(< "$job.exit")" == 0 ]] || { echo "$job failed; consistency screen not started." >&2;exit 1; }
done
# Wait for the longer training graphs to release GPU capacity.
for job in "$root/return-reversal-screen-v1/run";do
    while [[ ! -f "$job.exit" ]];do [[ -f "$job.pid" ]] && kill -0 "$(< "$job.pid")" || { echo "$job ended without a status." >&2;exit 1; }; /usr/bin/sleep 20;done
    printf '%s %s\n' "$job" "$(< "$job.exit")" >> "$out/prior-training-status.txt"
done
data="$admission/expanded/data.bin";targets="$admission/targets"
data_sha="$(/usr/bin/sha256sum "$data" | /usr/bin/cut -d' ' -f1)"
target_sha="$(/usr/bin/sha256sum "$targets/targets.bin" | /usr/bin/cut -d' ' -f1)"
initial_sha="$(/usr/bin/sha256sum "$initial/weights.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$data_sha" '.passed and .episodes==316 and .dataSHA256==$sha and .newHistoriesIndependentlyAudited and .teacherLabelsTrainingOnly and .actorInputsUnchanged' "$admission/coverage.json" > /dev/null
/usr/bin/jq -e --arg data "$data_sha" --arg target "$target_sha" --arg initial "$initial_sha" '.dataSHA256==$data and .targetPositionTargetsSHA256==$target and .initialWeightsSHA256==$initial and .memoryWidth==256 and .epochs==1 and .batch==2 and .learningRateMicros==100 and .seed==202 and .maxOptimizerSteps==98 and .phaseGatedNavigation and .sequenceMirrorAugmentation and .heatmapActorGradientDetached and (.taskFeedback|not) and (has("contactControlWeightMilli")|not)' "$baseline/policy/receipt.json" > /dev/null
/usr/bin/jq -e '.passed and .numericGradientAndMaskTests and .gpuDeterministic and .contactWeightedGradientChanged and .defaultBitIdenticalToPreviousRuntime and .validationUsesOriginalLoss and .inferenceParity and .invalidWeightRejected and .nonbinaryContactRejected and .actorInputsUnchanged' "$tests/validation.json" > /dev/null
/usr/bin/jq -e '.passed and .contactControlWeightChecked and .fullCNNAndGRU and .tensorsChecked>=24 and .maxGradientAbsError<0.001 and .maxAdamAbsError<0.000001' "$gradients/result.json" > /dev/null
/usr/bin/jq -e 'length==196 and index(217)!=null' "$baseline/training-indices.json" > /dev/null
/usr/bin/jq -e '.passed and .episodes==8 and .firstActionPerEpisodeExcluded and .rows[0].episode==0 and .rows[0].contactFeedbackActions>0' "$root/coverage-contact-analysis-v3/summary.json" > /dev/null
/usr/bin/jq -n --slurpfile report "$admission/expanded/report.json" --slurpfile analysis "$root/coverage-contact-analysis-v3/summary.json" '$report[0].sourceSHA256[1]==$analysis[0].dataSHA256 and any($report[0].records[]; .index==217 and .source==1 and .sourceIndex==0 and .fit)' | /usr/bin/jq -e . > /dev/null
/usr/bin/sha256sum "$data" "$targets/targets.bin" "$targets/receipt.json" "$admission/coverage.json" "$admission/expanded/report.json" "$root/coverage-contact-analysis-v3/summary.json" "$initial/weights.bin" "$baseline/training-indices.json" "$baseline/policy/initial.bin" "$baseline/policy/first-order.bin" "$baseline/policy/first-mirror-mask.bin" "$baseline/policy/first-gradients.bin" "$baseline/policy/last.bin" "$baseline/policy/receipt.json" "$baseline/screen/summary.json" "$tests/validation.json" "$gradients/result.json" "$runtime/build/flex/control/control" "$runtime/build/flex/control/trainer" "$runtime/build/flex/control/large-forward-tests" "$source/screen-large-model.sh" "$source/fixture/data/data.bin" > "$out/inputs.sha256"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
export PATH="$base/unseen-benchmark-v2/native-path:$PATH" XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1 PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
cd "$runtime"
./build/flex/control/control train --initial-policy "$initial" --data "$data" --output "$out/policy" --epochs 1 --batch 2 --learning-rate-micros 100 --seed 202 --checkpoint-every 1 --event-aux --target-heatmap "$targets" --heat-actor --heat-stop-gradient --mirror-augment --large-model --phase-gated --max-optimizer-steps 98 --contact-weight-milli 2000 > "$out/training.log" 2>&1
for file in initial.bin first-order.bin first-mirror-mask.bin;do /usr/bin/cmp "$baseline/policy/$file" "$out/policy/$file";done
# The first batch may contain no contact; compare the final optimizer state.
if /usr/bin/cmp -s "$baseline/policy/last.bin" "$out/policy/last.bin";then echo 'Contact weighting did not change the trained parameters.' >&2;exit 1;fi
/usr/bin/jq -e --arg data "$data_sha" --arg target "$target_sha" --arg initial "$initial_sha" '.dataSHA256==$data and .targetPositionTargetsSHA256==$target and .initialWeightsSHA256==$initial and .contactControlWeightMilli==2000 and .contactControlWeightTrainingOnly and .phaseGatedNavigation and .memoryWidth==256 and .maxOptimizerSteps==98 and (.taskFeedback|not)' "$out/policy/receipt.json" > /dev/null
/usr/bin/jq -se 'last | .epoch==1 and .optimizerSteps==98' "$out/policy/curves.jsonl" > /dev/null
./build/flex/control/large-forward-tests "$out/policy" "$source/fixture/data/data.bin" "$out/forward" > "$out/forward.log" 2>&1
/usr/bin/jq -e '.passed and .logitMaxAbsError<0.00001 and .memoryMaxAbsError<0.00001 and .resetBitIdentical' "$out/forward/result.json" > /dev/null
PUPPYBOT_POLICY="$out/policy" PUPPYBOT_SCREEN_OUTPUT="$out/screen" PUPPYBOT_SCREEN_CASES=observed /usr/bin/bash "$source/screen-large-model.sh" > "$out/screen.log" 2>&1
for index in 2 15 16 17;do seed=$((9960000+index));for file in case.json environment.bin;do /usr/bin/cmp "$baseline/screen/$index/$seed/scene/$file" "$out/screen/$index/$seed/scene/$file";done;done
/usr/bin/jq -n --slurpfile baseline "$baseline/screen/summary.json" --slurpfile candidate "$out/screen/summary.json" '{exploratory:true,episodesPerModel:4,optimizerStepsPerModel:98,sameTrainingData:true,initialWeightsIdentical:true,trainingOrdersIdentical:true,mirrorMasksIdentical:true,contactControlWeightMilli:2000,baseline:$baseline[0],candidate:$candidate[0],reservedFinalStillRequired:true,automaticPromotion:false}' > "$out/comparison.json"
/usr/bin/jq -e '.baseline.episodes==4 and .candidate.episodes==4 and .initialWeightsIdentical and .trainingOrdersIdentical and .mirrorMasksIdentical' "$out/comparison.json" > /dev/null
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
echo 'Contact control weighting and baseline evaluated on four matching development cases.'
