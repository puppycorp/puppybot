#!/usr/bin/env bash
# Collect 32 privileged teacher demonstrations after one student action each.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
base="$project/build/flex/sim/expanded-rooms-v1";root="$base/large-model-v1"
catalog="$root/coverage-scale-catalog-v1";runtime="$root/coverage-teacher-v2-runtime-v1/runtime"
policy="$root/student-only-training-v1/policy";pilot="$root/coverage-v2-teacher-cohort-v1"
audit="${PUPPYBOT_SCALE_TEACHER_AUDIT:?Frozen teacher goal audit required}"
capacity="${PUPPYBOT_SCALE_COLLECT_WAIT_RUN:?Previous benchmark required}"
out="${PUPPYBOT_SCALE_COLLECT_OUT:?New output directory required}"
[[ ! -e "$out" ]];mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
for job in "$catalog/run" "$pilot/run";do
    while [[ ! -f "$job.exit" ]];do [[ -f "$job.pid" ]] && kill -0 "$(< "$job.pid")" || { echo "$job ended without a status." >&2;exit 1; };sleep 20;done
    [[ "$(< "$job.exit")" == 0 ]] || { echo "$job failed; collection not started." >&2;exit 1; }
done
while [[ ! -f "$capacity.exit" ]];do [[ -f "$capacity.pid" ]] && kill -0 "$(< "$capacity.pid")" || { echo 'Previous benchmark ended without a status.' >&2;exit 1; };sleep 20;done
printf '%s\n' "$(< "$capacity.exit")" > "$out/prior-benchmark-status.txt"
jq -e '.passed and .episodes==32 and .fittingLayouts==16 and .validationLayouts==16 and .openLayouts==16 and .twoRoomLayouts==16 and .uniqueStartingPoses==32 and .geometryChecked and .exactCaseAndEnvironmentFilesDisjointFrom310And316CorporaAndDevelopment and .reservedFinalUntouched and .teacherEpisodesNotYetCollected' "$catalog/summary.json" > /dev/null
jq -e '.passed and .episodes==8 and .teacherAssistedCompleted>=1 and .teacherControlledAfterFirstAction and .teacherSearchGoalsReconstructed and .teacherLabelsTrainingOnly and (.studentAutonomousSuccessClaimed|not)' "$pilot/summary.json" > /dev/null
sha="$(sha256sum "$policy/weights.bin" | cut -d' ' -f1)"
jq -e --arg sha "$sha" '.weightsSHA256==$sha and .memoryWidth==256 and (.taskFeedback|not)' "$policy/receipt.json" > /dev/null
cmp "$runtime/build/flex/control/simulator" "$root/workspace/build/flex/control/simulator"
sha256sum -c "$catalog/inputs.sha256" > "$out/catalog-integrity-before.log"
sha256sum -c "$catalog/prior-inputs.sha256" > "$out/catalog-prior-integrity-before.log"
audit_jq="$(dirname "$audit")/audit-coverage-teacher-v2.jq"
sha256sum "$audit" "$audit_jq" "$runtime/build/flex/control/control" "$runtime/build/flex/control/simulator" "$runtime/build/flex/sim/puppybot.bin" "$policy/weights.bin" "$policy/policy" "$policy/receipt.json" "$catalog/summary.json" "$pilot/summary.json" > "$out/inputs.sha256"
find "$runtime/build/flex/control/kernels" -type f -print0 | sort -z | xargs -0 -r sha256sum >> "$out/inputs.sha256"
export PATH="$base/unseen-benchmark-v2/native-path:$PATH" XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1 PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
cd "$runtime"
./build/flex/control/control correct --policy "$policy" --output "$out/runs" --scene-catalog "$catalog/catalog" --episodes 32 --validation 16 --rollin 1 --rollin-min 1 --horizon 300 --label-rollin --allow-incomplete --coverage-teacher --seed 1995000 --large-model > "$out/collect.log" 2>&1
./build/flex/control/control pack-data --data "$out/runs/data.bin" --output "$out/packed" > "$out/pack.log" 2>&1
./build/flex/control/control verify-data --run "$out/runs" --data "$out/packed/data.bin" --output "$out/verified" --allow-incomplete --large-model > "$out/verify.log" 2>&1
data_sha="$(sha256sum "$out/packed/data.bin" | cut -d' ' -f1)"
jq -e --arg sha "$data_sha" '.passed and .episodes==32 and .datasetEpisodes==32 and .studentPolicies256==32 and .studentRollinCommandsReplayed==32 and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .executedCommandsMatchRecordings and .denseOracleLabels and .preActionAlignmentChecked and .zeroPaddingChecked and .taskEventHintAbsent and .dataSHA256==$sha and (.incompleteEpisodesClaimedSuccessful|not)' "$out/verified/result.json" > /dev/null
for ((episode=0;episode<32;episode++));do
    run="$out/runs/expert-$episode";scene="$catalog/catalog/$episode"
    jq -e --arg sha "$sha" '.studentMemoryWidth==256 and .studentWeightsSHA256==$sha and (.studentBeginsAfterConsumption|not) and .studentStartAction==0 and .denseOracleLabels and .allowIncomplete and .scheduledRollinActions==1 and .studentActions==1 and .searchTeacher=="coverage-camera-v2" and .teacherPlannerUsesPrivilegedGeometry and (.searchGoalsUseUnseenBrickPosition|not) and (.terminationReason=="horizon" or .terminationReason=="oracle-unavailable" or .terminationReason=="success")' "$run/supervision.json" > /dev/null
    for file in case.json environment.bin;do cmp "$scene/$file" "$run/scene/$file";done
    bash "$audit" "$run" "$out/goal-audit-$episode"
    jq -e '.passed and .brickPositionNotReadBySearchReconstruction and .oracleLabelsMatched' "$out/goal-audit-$episode/result.json" > /dev/null
done
sha256sum -c "$catalog/inputs.sha256" > "$out/catalog-integrity-after.log"
sha256sum -c "$catalog/prior-inputs.sha256" > "$out/catalog-prior-integrity-after.log"
sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
jq -n --arg sha "$data_sha" --slurpfile verified "$out/verified/result.json" --slurpfile report "$out/runs/report.json" '{passed:true,episodes:32,openEpisodes:16,twoRoomEpisodes:16,fittingEpisodes:16,validationEpisodes:16,studentRollinActionsReplayed:32,incompleteEpisodes:$verified[0].incompleteEpisodes,teacherAssistedCompleted:$report[0].teacherCompleted,dataSHA256:$sha,denseOracleLabels:true,teacherControlledAfterFirstAction:true,teacherSearchGoalsReconstructed:true,teacherPlannerUsesPrivilegedGeometry:true,teacherLabelsTrainingOnly:true,actorTaskEventHint:false,studentAutonomousSuccessClaimed:false,automaticMerge:false}' > "$out/summary.json"
jq -e '.passed and .episodes==32 and .studentRollinActionsReplayed==32 and .teacherSearchGoalsReconstructed and (.automaticMerge|not)' "$out/summary.json" > /dev/null
echo 'Thirty-two teacher demonstrations collected and audited; dataset admission remains separate.'
