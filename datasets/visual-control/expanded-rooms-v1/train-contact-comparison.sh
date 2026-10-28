#!/usr/bin/env bash
set -euo pipefail

project="${PUPPYBOT_PROJECT:?Project root is required}"
base="$project/build/flex/sim/expanded-rooms-v1"
root="$base/contact-training-v1"
admission="$base/contact-admission-v1"
labels="$base/contact-labels-v1"
diagnostic="$base/contact-cohort-diagnostic-v1"
matched="$base/matched-training-v3"
unseen="$base/unseen-benchmark-v2"
old="$base/admission-v3/data202/data.bin"
oldlabels="$base/labels-v3/targets"
[[ ! -e "$root/run.exit" && ! -e "$root/old" && ! -e "$root/expanded" ]]
trap 'status=$?; printf "%s\n" "$status" > "$root/run.exit"' EXIT
printf '%s\n' "$BASHPID" > "$root/run.pid"
for job in "$matched/run" "$labels/run" "$diagnostic/run";do
    while [[ ! -f "$job.exit" ]];do
        [[ -f "$job.pid" ]] && kill -0 "$(< "$job.pid")" || { echo "Process exited without status: $job" >&2;exit 1; }
        /usr/bin/sleep 10
    done
done
[[ "$(< "$labels/run.exit")" == 0 && "$(< "$diagnostic/run.exit")" == 0 ]] || { echo 'New data or contact diagnostic did not pass; no training started.' >&2;exit 1; }
cd "$project"
/usr/bin/sha256sum -c "$root/inputs.sha256" > "$root/integrity-before.log"
/usr/bin/sha256sum -c "$unseen/inputs.sha256" > "$root/benchmark-integrity-before.log"
data="$admission/merged-6/data.bin"
sha="$(/usr/bin/sha256sum "$data" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$sha" '.passed and .episodes==222 and .fittingHistories==174 and .validationHistories==48 and .dataSHA256==$sha and .allNewTripsIndependentlyAudited and .existingDataBytePreserved' "$admission/coverage.json" > /dev/null
/usr/bin/jq -e --arg sha "$sha" '.passed and .episodes==222 and .sourceDataSHA256==$sha and .actorInputsUnchanged' "$labels/preflight.json" > /dev/null
/usr/bin/jq -e '.passed and .existingHistoriesPreserved==202 and .expandedHistories==222' "$labels/preserved.json" > /dev/null
/usr/bin/jq -e '.audited and .episodes==16 and ([.fitting[].afterBlocked]|add)>0 and ([.validation[].afterBlocked]|add)>0 and .notStudentTaskPerformance' "$diagnostic/result.json" > /dev/null
initial_sha="$(/usr/bin/sha256sum "$root/initial/weights.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$initial_sha" '.weightsSHA256==$sha and (.taskFeedback|not) and .heatmapActorFeatures' "$root/initial/receipt.json" > /dev/null
export PATH="$root/native-path"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1
cd "$root/runtime"
for arm in old expanded;do
    training="$old";targets="$oldlabels";epochs=24;steps=1920
    if [[ "$arm" == expanded ]];then training="$data";targets="$labels/targets";epochs=22;steps=1914;fi
    ./build/flex/control/control train --initial-policy "$root/initial" --data "$training" --output "$root/$arm" --epochs "$epochs" --batch 2 --learning-rate-micros 100 --seed 197 --checkpoint-every 1 --event-aux --target-heatmap "$targets" --heat-actor --heat-stop-gradient > "$root/$arm.log" 2>&1
    /usr/bin/cmp "$root/initial/weights.bin" "$root/$arm/seed.bin"
    /usr/bin/jq -e --argjson epochs "$epochs" '.heatmapActorGradientDetached and .heatmapActorFeatures and .targetHeatmapAuxiliary and .cameraEventAuxiliary and (.taskFeedback|not) and .epochs==$epochs' "$root/$arm/receipt.json" > /dev/null
    /usr/bin/jq -s --argjson epochs "$epochs" --argjson steps "$steps" 'length==($epochs+1) and .[-1].epoch==$epochs and .[-1].optimizerSteps==$steps' "$root/$arm/curves.jsonl" > /dev/null
done
/usr/bin/cmp "$root/old/initial.bin" "$root/expanded/initial.bin"
/usr/bin/jq -n --slurpfile old "$root/old/curves.jsonl" --slurpfile expanded "$root/expanded/curves.jsonl" '{method:"same exploratory starting policy and nearly equal optimizer steps; training sets, validation sets and shuffle orders differ",oldOptimizerSteps:1920,expandedOptimizerSteps:1914,oldEpochs:24,expandedEpochs:22,oldSelectedEpoch:([$old[]|select(.selected)|.epoch]|last),expandedSelectedEpoch:([$expanded[]|select(.selected)|.epoch]|last),runtimeInputs:["TCP RGB","own feedback","recurrent state"],teacherLabelsTrainingOnly:true}' > "$root/training-comparison.json"
cd "$project"
/usr/bin/bash "$unseen/benchmark.sh" "$root/initial" contact-start
/usr/bin/bash "$unseen/benchmark.sh" "$root/old" contact-continued-202
/usr/bin/bash "$unseen/benchmark.sh" "$root/expanded" contact-continued-222
/usr/bin/sha256sum -c "$root/inputs.sha256" > "$root/integrity-after.log"
/usr/bin/sha256sum -c "$unseen/inputs.sha256" > "$root/benchmark-integrity-after.log"
[[ "$(/usr/bin/sha256sum "$data" | /usr/bin/cut -d' ' -f1)" == "$sha" ]]
/usr/bin/jq -s '{selection:"minimum demonstration validation loss, initial checkpoint included",start:.[0],old:.[1],expanded:.[2],allEpisodeAuditsPassed:all(.[]; .completedRecordings==32 and .auditedEpisodes==32 and .auditFailures==0),finalLayoutsStillRequired:true,retainedPolicyOverwritten:false}' "$unseen/score-contact-start.json" "$unseen/score-contact-continued-202.json" "$unseen/score-contact-continued-222.json" > "$root/comparison.json"
echo 'Contact-data continuation and 32-case episode comparisons complete; final holdout remains separate.'
