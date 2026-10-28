#!/usr/bin/env bash
# Compare matched updates with and without the audited student-only pilot.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
base="$project/build/flex/sim/expanded-rooms-v1"
root="$base/large-model-v1"
admission="$root/student-only-admission-v1"
baseline="$root/gated-search-cohort-training-v2"
old="$root/gated-search-cohort-admission-v2"
initial="$root/expanded-236-mirrored"
runtime="$root/phase-large-tests-v1/runtime"
source="$root/source/phase-screen-v1"
out="${PUPPYBOT_STUDENT_ONLY_TRAINING_OUT:?New output directory required}"
[[ ! -e "$out" ]]
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
for job in "$admission/run" "$baseline/run";do
    while [[ ! -f "$job.exit" ]];do [[ -f "$job.pid" ]] && kill -0 "$(< "$job.pid")" || { echo "$job ended without a status." >&2;exit 1; }; /usr/bin/sleep 20;done
    [[ "$(< "$job.exit")" == 0 ]] || { echo "$job failed; training not started." >&2;exit 1; }
done
# These independent jobs use the same GPU. Wait for their terminal status to
# leave room for this unrolled training graph, regardless of their outcomes.
capacity_jobs=("$root/return-cohort-equal-training-v1/run" "$root/return-cohort-second-training-v1/run" "$root/return-cohort-reversal-training-v1/run" "$root/phase-cohort-training-v1/run" "$root/phase-consistency-screen-v1/run")
if [[ -n "${PUPPYBOT_EXTRA_TRAINING_WAIT_RUN:-}" ]];then capacity_jobs+=("$PUPPYBOT_EXTRA_TRAINING_WAIT_RUN");fi
for job in "${capacity_jobs[@]}";do
    while [[ ! -f "$job.exit" ]];do [[ -f "$job.pid" ]] && kill -0 "$(< "$job.pid")" || { echo "$job ended without a status." >&2;exit 1; }; /usr/bin/sleep 20;done
    printf '%s %s\n' "$job" "$(< "$job.exit")" >> "$out/prior-training-status.txt"
done
data="$admission/expanded/data.bin";targets="$admission/targets"
data_sha="$(/usr/bin/sha256sum "$data" | /usr/bin/cut -d' ' -f1)"
baseline_sha="$(/usr/bin/sha256sum "$old/expanded/data.bin" | /usr/bin/cut -d' ' -f1)"
initial_sha="$(/usr/bin/sha256sum "$initial/weights.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$data_sha" --arg old "$baseline_sha" '.passed and .episodes==292 and .fittingHistories==209 and .validationHistories==83 and .addedStudentOnlyHistories==2 and .studentRollinActionsReplayed==600 and .incompleteAddedEpisodes==2 and .oldDataSHA256==$old and .dataSHA256==$sha and .existingDataBytePreserved and .existingTargetsBytePreserved and .newHistoriesIndependentlyAudited and .teacherLabelsTrainingOnly and .actorInputsUnchanged and (.incompleteEpisodesClaimedSuccessful|not)' "$admission/coverage.json" > /dev/null
/usr/bin/jq -e --arg data "$baseline_sha" --arg initial "$initial_sha" '.dataSHA256==$data and .initialWeightsSHA256==$initial and .memoryWidth==256 and .epochs==1 and .batch==2 and .learningRateMicros==100 and .seed==197 and .maxOptimizerSteps==98 and .phaseGatedNavigation and (.taskFeedback|not)' "$baseline/policy/receipt.json" > /dev/null
/usr/bin/jq -se 'last | .epoch==1 and .optimizerSteps==98' "$baseline/policy/curves.jsonl" > /dev/null
/usr/bin/sha256sum "$data" "$targets/targets.bin" "$targets/receipt.json" "$admission/coverage.json" "$admission/audit-fit/result.json" "$admission/audit-validation/result.json" "$initial/weights.bin" "$initial/receipt.json" "$baseline/policy/weights.bin" "$baseline/policy/receipt.json" "$baseline/screen/summary.json" "$baseline/comparison.json" "$source/screen-large-model.sh" "$runtime/build/flex/control/control" "$runtime/build/flex/control/trainer" "$runtime/build/flex/control/large-forward-tests" "$source/fixture/data/data.bin" > "$out/inputs.sha256"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
export PATH="$base/unseen-benchmark-v2/native-path:$PATH" XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1 PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
cd "$runtime"
./build/flex/control/control train --initial-policy "$initial" --data "$data" --output "$out/policy" --epochs 1 --batch 2 --learning-rate-micros 100 --seed 197 --checkpoint-every 1 --event-aux --target-heatmap "$targets" --heat-actor --heat-stop-gradient --mirror-augment --large-model --phase-gated --max-optimizer-steps 98 > "$out/training.log" 2>&1
/usr/bin/cmp "$initial/weights.bin" "$out/policy/seed.bin"
/usr/bin/cmp "$baseline/policy/initial.bin" "$out/policy/initial.bin"
/usr/bin/jq -e --arg data "$data_sha" --arg initial "$initial_sha" '.dataSHA256==$data and .initialWeightsSHA256==$initial and .memoryWidth==256 and .epochs==1 and .batch==2 and .learningRateMicros==100 and .seed==197 and .maxOptimizerSteps==98 and .phaseGatedNavigation and .sequenceMirrorAugmentation and .heatmapActorFeatures and .heatmapActorGradientDetached and (.taskFeedback|not)' "$out/policy/receipt.json" > /dev/null
/usr/bin/jq -se 'last | .epoch==1 and .optimizerSteps==98' "$out/policy/curves.jsonl" > /dev/null
/usr/bin/od -An -v -tu8 -N $((196*8)) "$out/policy/first-order.bin" | /usr/bin/tr ' ' '\n' | /usr/bin/rg '^[0-9]+$' | /usr/bin/jq -R 'tonumber' | /usr/bin/jq -s '.' > "$out/training-indices.json"
/usr/bin/jq -e 'length==196 and (unique|length)==196 and any(.==208)' "$out/training-indices.json" > /dev/null
./build/flex/control/large-forward-tests "$out/policy" "$source/fixture/data/data.bin" "$out/forward" > "$out/forward.log" 2>&1
/usr/bin/jq -e '.passed and .logitMaxAbsError<0.00001 and .memoryMaxAbsError<0.00001 and .resetBitIdentical' "$out/forward/result.json" > /dev/null
PUPPYBOT_POLICY="$out/policy" PUPPYBOT_SCREEN_OUTPUT="$out/screen" PUPPYBOT_SCREEN_CASES=observed /usr/bin/bash "$source/screen-large-model.sh" > "$out/screen.log" 2>&1
for index in 2 15 16 17;do seed=$((9960000+index));for file in case.json environment.bin;do /usr/bin/cmp "$baseline/screen/$index/$seed/scene/$file" "$out/screen/$index/$seed/scene/$file";done;done
/usr/bin/jq -n --slurpfile baseline "$baseline/screen/summary.json" --slurpfile candidate "$out/screen/summary.json" --slurpfile oldorder "$baseline/training-indices.json" --slurpfile neworder "$out/training-indices.json" '{exploratory:true,episodesPerModel:4,optimizerStepsPerModel:98,initialWeightsIdentical:true,additionalFittingHistorySeen:($neworder[0]|any(.==208)),trainingOrdersIdentical:($oldorder[0]==$neworder[0]),shuffleDifferencesLimitCausalInterpretation:true,baseline:$baseline[0],augmented:$candidate[0],reservedFinalStillRequired:true,automaticPromotion:false}' > "$out/comparison.json"
/usr/bin/jq -e '.additionalFittingHistorySeen and .baseline.episodes==4 and .augmented.episodes==4' "$out/comparison.json" > /dev/null
mkdir "$out/comparison-pair"
ln -s "$baseline/policy" "$out/comparison-pair/baseline-policy"
ln -s "$out/policy" "$out/comparison-pair/augmented-policy"
cp "$out/comparison.json" "$out/comparison-pair/comparison.json"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
printf '0\n' > "$out/comparison-pair/run.exit"
echo 'Student-only pilot model and matched development screen completed.'
