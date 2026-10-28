#!/usr/bin/env bash
# Add two previously audited teacher-search/student-return histories to 348.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
base="$project/build/flex/sim/expanded-rooms-v1";root="$base/large-model-v1"
old="$root/coverage-scale-admission-v1";cohort="$root/coverage-return-cohort-v1";worker="$cohort/worker-0";prior="$root/wide-student-catalog-v2"
runtime="$root/coverage-return-tests-v1/runtime";bin="$root/source/admission-cohort-v3/bin";merge_targets="$root/empty-target-build-v2/merge-targets"
labels="$root/coverage-return-admission-v1/labels-0/targets"
old_audit="$project/datasets/visual-control/expanded-rooms-v1/audit-coverage-teacher-v2.sh"
frozen_audit="$root/coverage-scale-source-v1/audit-resources/datasets/visual-control/expanded-rooms-v1/audit-coverage-teacher-v2.sh"
audit="${PUPPYBOT_RETURN_REUSE_AUDIT:?Frozen current teacher audit required}"
capacity="${PUPPYBOT_RETURN_REUSE_WAIT_RUN:?Previous GPU job required}"
out="${PUPPYBOT_RETURN_REUSE_OUT:?New output directory required}"
[[ ! -e "$out" ]];mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
for job in "$old/run" "$cohort/run" "$prior/run";do [[ "$(< "$job.exit")" == 0 ]];done
while [[ ! -f "$capacity.exit" ]];do [[ -f "$capacity.pid" ]] && kill -0 "$(< "$capacity.pid")" || { echo 'Previous GPU job ended without a status.' >&2;exit 1; };sleep 20;done
printf '%s\n' "$(< "$capacity.exit")" > "$out/prior-gpu-status.txt"
old_data="$old/expanded/data.bin";new_data="$worker/packed/data.bin";old_sha="$(sha256sum "$old_data" | cut -d' ' -f1)";new_sha="$(sha256sum "$new_data" | cut -d' ' -f1)"
jq -e --arg sha "$old_sha" '.passed and .episodes==348 and .fittingHistories==237 and .validationHistories==111 and .dataSHA256==$sha and .existingDataBytePreserved and .existingTargetsBytePreserved and .newHistoriesIndependentlyAudited and .actorInputsUnchanged' "$old/coverage.json" > /dev/null
jq -e '.complete and .successfulWorkers>=1 and .teacherAssisted and (.autonomousWholeEpisodeSuccessClaimed|not)' "$cohort/summary.json" > /dev/null
jq -e '.passed and .studentReturnActionsReplayed==120 and .studentReturnCompletions==0 and .teacherAssisted and (.automaticMerge|not)' "$cohort/worker-0.json" > /dev/null
jq -e --arg sha "$new_sha" '.passed and .episodes==2 and .datasetEpisodes==2 and .dataSHA256==$sha and .studentPolicies256==2 and .studentRollinCommandsReplayed==120 and .studentRollinMaxAbsError==0 and .denseOracleLabels and .datasetInputsMatchActualRGBAndOwnFeedback and .executedCommandsMatchRecordings and .taskEventHintAbsent' "$worker/verified/result.json" > /dev/null
jq -e --arg sha "$new_sha" '.passed and .sourceDataSHA256==$sha and .allowEmptyCandidateSplits and .projectionAndPixelsIndependentlyRechecked and .actorInputsUnchanged' "$labels/receipt.json" > /dev/null
# The old audit script was moved to a frozen snapshot after its source changed.
# Replace only that manifest path; its recorded digest must match the snapshot.
[[ "$(awk -v old="$old_audit" '$2==old {n++} END {print n+0}' "$cohort/inputs.sha256")" == 1 ]]
awk -v old="$old_audit" -v frozen="$frozen_audit" '$2==old {$2=frozen} {print $1"  "$2}' "$cohort/inputs.sha256" > "$out/resolved-cohort-inputs.sha256"
sha256sum -c "$out/resolved-cohort-inputs.sha256" > "$out/cohort-integrity.log"
sha256sum -c "$cohort/prior-inputs.sha256" > "$out/cohort-prior-integrity.log"
sha256sum -c "$prior/inputs.sha256" > "$out/prior-catalog-integrity.log"
sha256sum -c "$prior/prior-inputs.sha256" > "$out/prior-scenes-integrity.log"
cut -d' ' -f1 "$prior/prior-inputs.sha256" > "$out/prior-hashes.txt"
for ((i=0;i<8;i++));do for file in case.json environment.bin;do sha256sum "$prior/catalog/$i/$file" | cut -d' ' -f1 >> "$out/prior-hashes.txt";done;done
for i in 0 1;do
    run="$worker/runs/expert-$i";jq -e '.studentBeginsAfterConsumption and .studentStartAction>=1 and .studentActions==60 and (.studentCompletedBeforeHandoff|not) and .denseOracleLabels and .teacherPlannerUsesPrivilegedGeometry' "$run/supervision.json" > /dev/null
    for file in case.json environment.bin;do digest="$(sha256sum "$run/scene/$file" | cut -d' ' -f1)";status=0;rg -Fxq "$digest" "$out/prior-hashes.txt" || status=$?;if (( status==0 ));then echo 'Return scene duplicates current corpus or development.' >&2;exit 1;fi;if (( status!=1 ));then exit "$status";fi;printf '%s\n' "$digest" >> "$out/prior-hashes.txt";done
    bash "$audit" "$run" "$out/goal-audit-$i" > "$out/goal-audit-$i.log" 2>&1
    cmp "$worker/goal-audit-$i/result.json" "$out/goal-audit-$i/result.json"
done
sha256sum "$bin"/* "$runtime/build/flex/control/control" "$runtime/build/flex/control/simulator" "$merge_targets" "$old_data" "$old/targets/targets.bin" "$old/targets/receipt.json" "$old/coverage.json" "$new_data" "$labels/targets.bin" "$labels/receipt.json" "$worker/verified/result.json" "$audit" "$(dirname "$audit")/audit-coverage-teacher-v2.jq" "$out"/goal-audit-{0,1}/{result.json,inputs.sha256} > "$out/inputs.sha256"
sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
"$bin/merge-dense-many" "$out/expanded" "$old_data" "$old/expanded" "$new_data" "$worker/runs" > "$out/expanded.log"
"$merge_targets" "$out/expanded" "$out/targets" "$old_data" "$old/targets" "$new_data" "$labels" > "$out/targets.log"
"$bin/data-preserve-added" "$old_data" "$out/expanded/data.bin" "$out/data-preserved.json"
"$bin/target-preserve-added" "$old/targets/targets.bin" "$out/targets/targets.bin" "$out/targets-preserved.json"
"$bin/preflight-expanded-targets" "$out/expanded/data.bin" "$out/targets" "$out/preflight.json"
for report in "$out/data-preserved.json" "$out/targets-preserved.json";do jq -e '.passed and .existingHistoriesPreserved==348 and .expandedHistories==350 and .expandedFittingHistories==238' "$report" > /dev/null;done
jq -e '.passed and .episodes==350 and .fittingHistories==238 and .validationHistories==112 and .actorInputsUnchanged' "$out/preflight.json" > /dev/null
expanded_sha="$(sha256sum "$out/expanded/data.bin" | cut -d' ' -f1)"
export PATH="$base/unseen-benchmark-v2/native-path:$PATH" XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1 PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
cd "$runtime"
./build/flex/control/control verify-data --run "$out/expanded" --data "$out/expanded/data.bin" --output "$out/audit-fit" --audit-start 237 --audit-count 1 --large-model > "$out/audit-fit.log" 2>&1
./build/flex/control/control verify-data --run "$out/expanded" --data "$out/expanded/data.bin" --output "$out/audit-validation" --audit-start 349 --audit-count 1 --large-model > "$out/audit-validation.log" 2>&1
for role in fit validation;do jq -e --arg sha "$expanded_sha" '.passed and .datasetEpisodes==350 and .episodes==1 and .dataSHA256==$sha and .studentPolicies256==1 and .studentRollinCommandsReplayed==60 and .studentRollinMaxAbsError==0 and .denseOracleLabels and .datasetInputsMatchActualRGBAndOwnFeedback and .executedCommandsMatchRecordings and .taskEventHintAbsent' "$out/audit-$role/result.json" > /dev/null;done
sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
sha256sum -c "$out/resolved-cohort-inputs.sha256" > "$out/cohort-integrity-after.log"
sha256sum -c "$prior/prior-inputs.sha256" > "$out/prior-scenes-integrity-after.log"
jq -n --arg old "$old_sha" --arg sha "$expanded_sha" '{passed:true,episodes:350,fittingHistories:238,validationHistories:112,addedReturnHistories:2,studentReturnActionsReplayed:120,oldDataSHA256:$old,dataSHA256:$sha,existingDataBytePreserved:true,existingTargetsBytePreserved:true,newHistoriesIndependentlyAudited:true,teacherSearchGoalsReconstructed:true,teacherLabelsTrainingOnly:true,actorInputsUnchanged:true,teacherAssisted:true,autonomousWholeEpisodeSuccessClaimed:false,automaticPromotion:false}' > "$out/coverage.json"
echo 'Two teacher-assisted return histories admitted; no student full-episode success is claimed.'
