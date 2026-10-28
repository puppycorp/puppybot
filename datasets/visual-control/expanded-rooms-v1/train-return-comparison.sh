#!/usr/bin/env bash
set -euo pipefail

project="${PUPPYBOT_PROJECT:?Project root is required}"
base="$project/build/flex/sim/expanded-rooms-v1"
root="$base/return-training-v1"
admission="$base/return-admission-v1"
labels="$base/return-labels-v1"
diagnostic="$base/return-cohort-diagnostic-v1"
matched="$base/matched-training-v3"
contact="$base/contact-training-v1"
unseen="$base/unseen-benchmark-v2"
old="$base/contact-admission-v1/merged-6/data.bin"
oldlabels="$base/contact-labels-v1/targets"
[[ ! -e "$root/run.exit" && ! -e "$root/old" && ! -e "$root/expanded" ]]
trap 'status=$?; printf "%s\n" "$status" > "$root/run.exit"' EXIT
printf '%s\n' "$BASHPID" > "$root/run.pid"
for job in "$matched/run" "$labels/run" "$diagnostic/run";do
    while [[ ! -f "$job.exit" ]];do
        [[ -f "$job.pid" ]] && kill -0 "$(< "$job.pid")" || { echo "Process exited without status: $job" >&2;exit 1; }
        /usr/bin/sleep 10
    done
done
[[ "$(< "$labels/run.exit")" == 0 && "$(< "$diagnostic/run.exit")" == 0 ]] || { echo 'Return data or diagnostic did not pass; no training started.' >&2;exit 1; }
cd "$project"
/usr/bin/sha256sum -c "$root/inputs.sha256" > "$root/integrity-before.log"
/usr/bin/sha256sum -c "$unseen/inputs.sha256" > "$root/benchmark-integrity-before.log"
data="$admission/merged-7/data.bin"
sha="$(/usr/bin/sha256sum "$data" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$sha" '.passed and .episodes==236 and .fittingHistories==181 and .validationHistories==55 and .dataSHA256==$sha and .allNewTripsIndependentlyAudited and .existingDataBytePreserved' "$admission/coverage.json" > /dev/null
/usr/bin/jq -e --arg sha "$sha" '.passed and .episodes==236 and .sourceDataSHA256==$sha and .actorInputsUnchanged' "$labels/preflight.json" > /dev/null
/usr/bin/jq -e '.passed and .existingHistoriesPreserved==222 and .expandedHistories==236' "$labels/preserved.json" > /dev/null
/usr/bin/jq -e '.audited and .episodes==12 and ([.fitting[].oracleDiffers]|add)>0 and ([.validation[].oracleDiffers]|add)>0 and .notAutonomousWholeEpisodePerformance' "$diagnostic/result.json" > /dev/null
initial_sha="$(/usr/bin/sha256sum "$root/initial/weights.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$initial_sha" '.weightsSHA256==$sha and (.taskFeedback|not) and .heatmapActorFeatures' "$root/initial/receipt.json" > /dev/null
export PATH="$root/native-path"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1
cd "$root/runtime"
for arm in old expanded;do
    training="$old";targets="$oldlabels";epochs=22;steps=1914
    if [[ "$arm" == expanded ]];then training="$data";targets="$labels/targets";epochs=21;steps=1911;fi
    ./build/flex/control/control train --initial-policy "$root/initial" --data "$training" --output "$root/$arm" --epochs "$epochs" --batch 2 --learning-rate-micros 100 --seed 197 --checkpoint-every 1 --event-aux --target-heatmap "$targets" --heat-actor --heat-stop-gradient > "$root/$arm.log" 2>&1
    /usr/bin/cmp "$root/initial/weights.bin" "$root/$arm/seed.bin"
    /usr/bin/jq -e --argjson epochs "$epochs" '.heatmapActorGradientDetached and .heatmapActorFeatures and .targetHeatmapAuxiliary and .cameraEventAuxiliary and (.taskFeedback|not) and .epochs==$epochs' "$root/$arm/receipt.json" > /dev/null
    /usr/bin/jq -s --argjson epochs "$epochs" --argjson steps "$steps" 'length==($epochs+1) and .[-1].epoch==$epochs and .[-1].optimizerSteps==$steps' "$root/$arm/curves.jsonl" > /dev/null
done
/usr/bin/cmp "$root/old/initial.bin" "$root/expanded/initial.bin"
/usr/bin/jq -n --slurpfile old "$root/old/curves.jsonl" --slurpfile expanded "$root/expanded/curves.jsonl" '{method:"same exploratory starting policy and nearly equal optimizer steps; training sets, validation sets and shuffle orders differ",oldOptimizerSteps:1914,expandedOptimizerSteps:1911,oldEpochs:22,expandedEpochs:21,oldSelectedEpoch:([$old[]|select(.selected)|.epoch]|last),expandedSelectedEpoch:([$expanded[]|select(.selected)|.epoch]|last),runtimeInputs:["TCP RGB","own feedback","recurrent state"],teacherLabelsTrainingOnly:true}' > "$root/training-comparison.json"
while [[ ! -f "$contact/run.exit" ]];do
    [[ -f "$contact/run.pid" ]] && kill -0 "$(< "$contact/run.pid")" || { echo 'Contact comparison disappeared without a terminal status.' >&2;exit 1; }
    /usr/bin/sleep 10
done
cd "$project"
/usr/bin/bash "$unseen/benchmark.sh" "$root/initial" return-start
/usr/bin/bash "$unseen/benchmark.sh" "$root/old" return-continued-222
/usr/bin/bash "$unseen/benchmark.sh" "$root/expanded" return-continued-236
/usr/bin/sha256sum -c "$root/inputs.sha256" > "$root/integrity-after.log"
/usr/bin/sha256sum -c "$unseen/inputs.sha256" > "$root/benchmark-integrity-after.log"
[[ "$(/usr/bin/sha256sum "$data" | /usr/bin/cut -d' ' -f1)" == "$sha" ]]
/usr/bin/jq -s '{selection:"minimum demonstration validation loss, initial checkpoint included",start:.[0],old:.[1],expanded:.[2],allEpisodeAuditsPassed:all(.[]; .completedRecordings==32 and .auditedEpisodes==32 and .auditFailures==0),finalLayoutsStillRequired:true,retainedPolicyOverwritten:false}' "$unseen/score-return-start.json" "$unseen/score-return-continued-222.json" "$unseen/score-return-continued-236.json" > "$root/comparison.json"
echo 'Return-data continuation and 32-case episode comparisons complete; final holdout remains separate.'
