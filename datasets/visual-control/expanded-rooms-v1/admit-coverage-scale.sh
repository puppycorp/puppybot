#!/usr/bin/env bash
# Merge independently audited scaled teacher histories and masked visual labels.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
base="$project/build/flex/sim/expanded-rooms-v1";root="$base/large-model-v1"
old="$root/coverage-v2-student-admission-v1";collection="$root/coverage-scale-collection-v1";catalog="$root/coverage-scale-catalog-v1"
runtime="$root/coverage-teacher-v2-runtime-v1/runtime";bin="$root/source/admission-cohort-v3/bin"
survey="$base/return-labels-v1/survey";prepare="$root/empty-target-build-v2/prepare";merge_targets="$root/empty-target-build-v2/merge-targets"
capacity="${PUPPYBOT_SCALE_ADMISSION_WAIT_RUN:?Previous GPU job required}"
out="${PUPPYBOT_SCALE_ADMISSION_OUT:?New output directory required}"
[[ ! -e "$out" ]];mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
for job in "$old/run" "$collection/run";do
    while [[ ! -f "$job.exit" ]];do [[ -f "$job.pid" ]] && kill -0 "$(< "$job.pid")" || { echo "$job ended without a status." >&2;exit 1; };sleep 20;done
    [[ "$(< "$job.exit")" == 0 ]] || { echo "$job failed; no histories admitted." >&2;exit 1; }
done
while [[ ! -f "$capacity.exit" ]];do [[ -f "$capacity.pid" ]] && kill -0 "$(< "$capacity.pid")" || { echo 'Previous GPU job ended without a status.' >&2;exit 1; };sleep 20;done
printf '%s\n' "$(< "$capacity.exit")" > "$out/prior-gpu-status.txt"
old_data="$old/expanded/data.bin";new_data="$collection/packed/data.bin";old_sha="$(sha256sum "$old_data" | cut -d' ' -f1)";new_sha="$(sha256sum "$new_data" | cut -d' ' -f1)"
jq -e --arg sha "$old_sha" '.passed and .episodes==316 and .fittingHistories==221 and .validationHistories==95 and .dataSHA256==$sha and .existingDataBytePreserved and .existingTargetsBytePreserved and .newHistoriesIndependentlyAudited and .teacherLabelsTrainingOnly and .actorInputsUnchanged' "$old/coverage.json" > /dev/null
jq -e --arg sha "$new_sha" '.passed and .episodes==32 and .openEpisodes==16 and .twoRoomEpisodes==16 and .fittingEpisodes==16 and .validationEpisodes==16 and .studentRollinActionsReplayed==32 and .teacherControlledAfterFirstAction and .dataSHA256==$sha and .denseOracleLabels and .teacherSearchGoalsReconstructed and .teacherPlannerUsesPrivilegedGeometry and .teacherLabelsTrainingOnly and (.actorTaskEventHint|not) and (.studentAutonomousSuccessClaimed|not) and (.automaticMerge|not)' "$collection/summary.json" > /dev/null
jq -e --arg sha "$new_sha" '.passed and .episodes==32 and .datasetEpisodes==32 and .studentPolicies256==32 and .studentRollinCommandsReplayed==32 and .dataSHA256==$sha and .studentRollinMaxAbsError==0 and .denseOracleLabels and .datasetInputsMatchActualRGBAndOwnFeedback and .executedCommandsMatchRecordings and .preActionAlignmentChecked and .zeroPaddingChecked and .taskEventHintAbsent and (.incompleteEpisodesClaimedSuccessful|not)' "$collection/verified/result.json" > /dev/null
sha256sum -c "$catalog/inputs.sha256" > "$out/catalog-integrity.log"
sha256sum -c "$catalog/prior-inputs.sha256" > "$out/catalog-prior-integrity.log"
sha256sum -c "$collection/inputs.sha256" > "$out/collection-integrity.log"
for ((i=0;i<32;i++));do
    audit="$collection/goal-audit-$i";run="$collection/runs/expert-$i"
    jq -e '.passed and .brickPositionNotReadBySearchReconstruction and .oracleLabelsMatched and (.actorInputsChecked|not)' "$audit/result.json" > /dev/null
    sha256sum -c "$audit/inputs.sha256" > "$out/goal-integrity-$i.log"
    jq -e '.studentStartAction==0 and .studentActions==1 and .denseOracleLabels and .allowIncomplete and .searchTeacher=="coverage-camera-v2" and .teacherPlannerUsesPrivilegedGeometry and (.searchGoalsUseUnseenBrickPosition|not)' "$run/supervision.json" > /dev/null
    for file in case.json environment.bin;do cmp "$catalog/catalog/$i/$file" "$run/scene/$file";done
done
sha256sum "$bin"/* "$runtime/build/flex/control/control" "$runtime/build/flex/control/simulator" "$survey" "$prepare" "$merge_targets" "$old_data" "$old/targets/targets.bin" "$old/targets/receipt.json" "$old/coverage.json" "$new_data" "$collection/summary.json" "$collection/verified/result.json" "$collection"/goal-audit-{0..31}/{result.json,inputs.sha256} "$collection"/runs/expert-{0..31}/supervision.json > "$out/inputs.sha256"
sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
mkdir "$out/labels"
"$survey" "$new_data" "$collection/runs" "$out/labels/survey.json" 32 "$new_sha" "$out/labels/candidates.jsonl" > "$out/labels/survey.log" 2>&1
candidates="$(sha256sum "$out/labels/candidates.jsonl" | cut -d' ' -f1)"
"$prepare" "$new_data" "$collection/runs" "$out/labels/candidates.jsonl" "$out/labels/survey.json" "$new_sha" "$candidates" "$out/labels/targets" --allow-empty-splits > "$out/labels/prepare.log" 2>&1
jq -e --arg sha "$new_sha" '.passed and .sourceDataSHA256==$sha and .allowEmptyCandidateSplits and .projectionAndPixelsIndependentlyRechecked and .actorInputsUnchanged' "$out/labels/targets/receipt.json" > /dev/null
"$bin/merge-dense-many" "$out/expanded" "$old_data" "$old/expanded" "$new_data" "$collection/runs" > "$out/expanded.log"
"$merge_targets" "$out/expanded" "$out/targets" "$old_data" "$old/targets" "$new_data" "$out/labels/targets" > "$out/targets.log"
"$bin/data-preserve-added" "$old_data" "$out/expanded/data.bin" "$out/data-preserved.json"
"$bin/target-preserve-added" "$old/targets/targets.bin" "$out/targets/targets.bin" "$out/targets-preserved.json"
"$bin/preflight-expanded-targets" "$out/expanded/data.bin" "$out/targets" "$out/preflight.json"
for report in "$out/data-preserved.json" "$out/targets-preserved.json";do jq -e '.passed and .existingHistoriesPreserved==316 and .expandedHistories==348 and .expandedFittingHistories==237' "$report" > /dev/null;done
jq -e '.passed and .episodes==348 and .fittingHistories==237 and .validationHistories==111 and .actorInputsUnchanged' "$out/preflight.json" > /dev/null
expanded_sha="$(sha256sum "$out/expanded/data.bin" | cut -d' ' -f1)"
export PATH="$base/unseen-benchmark-v2/native-path:$PATH" XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1 PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
cd "$runtime"
./build/flex/control/control verify-data --run "$out/expanded" --data "$out/expanded/data.bin" --output "$out/audit-fit" --audit-start 221 --audit-count 16 --allow-incomplete --large-model > "$out/audit-fit.log" 2>&1
./build/flex/control/control verify-data --run "$out/expanded" --data "$out/expanded/data.bin" --output "$out/audit-validation" --audit-start 332 --audit-count 16 --allow-incomplete --large-model > "$out/audit-validation.log" 2>&1
for role in fit validation;do jq -e --arg sha "$expanded_sha" '.passed and .datasetEpisodes==348 and .episodes==16 and .dataSHA256==$sha and .studentPolicies256==16 and .studentRollinCommandsReplayed==16 and .studentRollinMaxAbsError==0 and .denseOracleLabels and .taskEventHintAbsent and (.incompleteEpisodesClaimedSuccessful|not)' "$out/audit-$role/result.json" > /dev/null;done
sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
for ((i=0;i<32;i++));do sha256sum -c "$collection/goal-audit-$i/inputs.sha256" > "$out/goal-integrity-after-$i.log";done
[[ "$(sha256sum "$out/expanded/data.bin" | cut -d' ' -f1)" == "$expanded_sha" ]]
jq -n --arg old "$old_sha" --arg sha "$expanded_sha" --slurpfile a "$out/audit-fit/result.json" --slurpfile b "$out/audit-validation/result.json" --slurpfile report "$collection/summary.json" '{passed:true,episodes:348,fittingHistories:237,validationHistories:111,addedTeacherHistories:32,studentRollinActionsReplayed:32,incompleteAddedEpisodes:($a[0].incompleteEpisodes+$b[0].incompleteEpisodes),teacherAssistedCompleted:$report[0].teacherAssistedCompleted,oldDataSHA256:$old,dataSHA256:$sha,existingDataBytePreserved:true,existingTargetsBytePreserved:true,newHistoriesIndependentlyAudited:true,teacherSearchGoalsReconstructed:true,teacherLabelsTrainingOnly:true,actorInputsUnchanged:true,incompleteEpisodesClaimedSuccessful:false,automaticPromotion:false}' > "$out/coverage.json"
jq -e '.passed and .episodes==348 and .addedTeacherHistories==32 and .actorInputsUnchanged and (.automaticPromotion|not)' "$out/coverage.json" > /dev/null
echo 'Thirty-two independently audited teacher histories admitted; training and evaluation remain separate.'
