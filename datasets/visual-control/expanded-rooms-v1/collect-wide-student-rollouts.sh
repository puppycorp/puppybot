#!/usr/bin/env bash
# Collect full student-driven wide-heading trips with privileged teacher labels.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
base="$project/build/flex/sim/expanded-rooms-v1";root="$base/large-model-v1"
catalog="$root/wide-student-catalog-v2";runtime="$root/coverage-teacher-v2-runtime-v1/runtime"
training="$root/coverage-scale-training-v1";policy="$training/policy";evaluation="$root/coverage-scale-diverse-comparison-v1"
audit="${PUPPYBOT_WIDE_STUDENT_AUDIT:?Frozen teacher goal audit required}"
capacity="${PUPPYBOT_WIDE_STUDENT_WAIT_RUN:?Previous GPU job required}"
out="${PUPPYBOT_WIDE_STUDENT_COLLECT_OUT:?New output directory required}"
[[ ! -e "$out" ]];mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
for job in "$catalog/run" "$training/run" "$evaluation/run";do
    while [[ ! -f "$job.exit" ]];do [[ -f "$job.pid" ]] && kill -0 "$(< "$job.pid")" || { echo "$job ended without a status." >&2;exit 1; };sleep 20;done
    [[ "$(< "$job.exit")" == 0 ]] || { echo "$job failed; collection not started." >&2;exit 1; }
done
while [[ ! -f "$capacity.exit" ]];do [[ -f "$capacity.pid" ]] && kill -0 "$(< "$capacity.pid")" || { echo 'Previous GPU job ended without a status.' >&2;exit 1; };sleep 20;done
printf '%s\n' "$(< "$capacity.exit")" > "$out/prior-gpu-status.txt"
jq -e '.passed and .episodes==8 and .fittingLayouts==4 and .validationLayouts==4 and .openLayouts==4 and .twoRoomLayouts==4 and .uniqueStartingPoses==8 and .wideHeading and .geometryChecked and .exactFilesDisjointFrom348CorpusAndDevelopment and .reservedFinalUntouched and .physicalSpawnNotYetChecked' "$catalog/summary.json" > /dev/null
sha="$(sha256sum "$policy/weights.bin" | cut -d' ' -f1)"
jq -e --arg sha "$sha" '.weightsSHA256==$sha and .memoryWidth==256 and (.taskFeedback|not)' "$policy/receipt.json" > /dev/null
jq -e --arg sha "$sha" '.passed and .episodes==8 and .auditedEpisodes==8 and .policyWeightsSHA256==$sha and all(.rows[];.auditPassed and (.suppliedMap|not) and (.taskEventHint|not))' "$evaluation/candidate/score.json" > /dev/null
cmp "$runtime/build/flex/control/simulator" "$root/workspace/build/flex/control/simulator"
sha256sum -c "$catalog/inputs.sha256" > "$out/catalog-integrity-before.log"
sha256sum -c "$catalog/prior-inputs.sha256" > "$out/catalog-prior-integrity-before.log"
audit_jq="$(dirname "$audit")/audit-coverage-teacher-v2.jq"
sha256sum "$audit" "$audit_jq" "$runtime/build/flex/control/control" "$runtime/build/flex/control/simulator" "$runtime/build/flex/sim/puppybot.bin" "$policy/weights.bin" "$policy/policy" "$policy/receipt.json" "$catalog/summary.json" "$evaluation/candidate/score.json" > "$out/inputs.sha256"
find "$runtime/build/flex/control/kernels" -type f -print0 | sort -z | xargs -0 -r sha256sum >> "$out/inputs.sha256"
export PATH="$base/unseen-benchmark-v2/native-path:$PATH" XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1 PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
cd "$runtime"
./build/flex/control/control correct --policy "$policy" --output "$out/runs" --scene-catalog "$catalog/catalog" --episodes 8 --validation 4 --rollin 300 --rollin-min 300 --horizon 300 --label-rollin --allow-incomplete --coverage-teacher --seed 1996000 --large-model > "$out/collect.log" 2>&1
./build/flex/control/control pack-data --data "$out/runs/data.bin" --output "$out/packed" > "$out/pack.log" 2>&1
./build/flex/control/control verify-data --run "$out/runs" --data "$out/packed/data.bin" --output "$out/verified" --allow-incomplete --large-model > "$out/verify.log" 2>&1
data_sha="$(sha256sum "$out/packed/data.bin" | cut -d' ' -f1)";actions="$(jq -er '.studentRollinActions | select(type=="number" and .>=8 and .<=2400 and floor==.)' "$out/runs/report.json")"
jq -e --arg sha "$data_sha" --argjson actions "$actions" '.passed and .episodes==8 and .datasetEpisodes==8 and .studentPolicies256==8 and .studentRollinCommandsReplayed==$actions and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .executedCommandsMatchRecordings and .denseOracleLabels and .preActionAlignmentChecked and .zeroPaddingChecked and .taskEventHintAbsent and .dataSHA256==$sha and (.incompleteEpisodesClaimedSuccessful|not)' "$out/verified/result.json" > /dev/null
for ((episode=0;episode<8;episode++));do
    run="$out/runs/expert-$episode";scene="$catalog/catalog/$episode"
    jq -e --arg sha "$sha" '.studentMemoryWidth==256 and .studentWeightsSHA256==$sha and (.studentBeginsAfterConsumption|not) and .studentStartAction==0 and .denseOracleLabels and .allowIncomplete and .scheduledRollinActions==300 and .studentActions>=1 and .studentActions<=300 and .searchTeacher=="coverage-camera-v2" and .teacherPlannerUsesPrivilegedGeometry and (.searchGoalsUseUnseenBrickPosition|not) and (.terminationReason=="horizon" or .terminationReason=="oracle-unavailable" or .terminationReason=="success")' "$run/supervision.json" > /dev/null
    steps="$(wc -l < "$run/decisions.jsonl")"
    jq -e --argjson steps "$steps" '.studentActions==$steps' "$run/supervision.json" > /dev/null
    jq -e --argjson steps "$steps" '.steps==$steps' "$run/result.json" > /dev/null
    for file in case.json environment.bin;do cmp "$scene/$file" "$run/scene/$file";done
    jq -n --slurpfile scene "$scene/layout.json" --slurpfile initial "$run/initial.json" 'def abs: if .<0 then -. else . end; all(range(0;3); . as $i | (($scene[0].startPose[$i]-$initial[0].pose[$i])|abs)<0.00001)' | jq -e . > /dev/null
    bash "$audit" "$run" "$out/goal-audit-$episode"
    jq -e '.passed and .brickPositionNotReadBySearchReconstruction and .oracleLabelsMatched' "$out/goal-audit-$episode/result.json" > /dev/null
done
sha256sum -c "$catalog/inputs.sha256" > "$out/catalog-integrity-after.log"
sha256sum -c "$catalog/prior-inputs.sha256" > "$out/catalog-prior-integrity-after.log"
sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
jq -s '[.[]|{found,success,steps,pathM,leftStartRoom}]' "$out"/runs/expert-{0..7}/result.json > "$out/outcomes.json"
jq -n --arg sha "$data_sha" --argjson actions "$actions" --slurpfile verified "$out/verified/result.json" --slurpfile outcomes "$out/outcomes.json" '{passed:true,episodes:8,fittingEpisodes:4,validationEpisodes:4,openEpisodes:4,twoRoomEpisodes:4,studentRollinActionsReplayed:$actions,incompleteEpisodes:$verified[0].incompleteEpisodes,studentFound:($outcomes[0]|map(select(.found))|length),studentReturns:($outcomes[0]|map(select(.success))|length),dataSHA256:$sha,denseOracleLabels:true,fullyStudentControlled:true,initialPhysicalPosesChecked:true,teacherSearchGoalsReconstructed:true,teacherPlannerUsesPrivilegedGeometry:true,teacherLabelsTrainingOnly:true,actorTaskEventHint:false,automaticMerge:false}' > "$out/summary.json"
jq -e --argjson actions "$actions" '.passed and .episodes==8 and .studentRollinActionsReplayed==$actions and .fullyStudentControlled and .initialPhysicalPosesChecked and (.automaticMerge|not)' "$out/summary.json" > /dev/null
echo 'Wide-heading student rollouts and teacher labels passed replay and goal checks.'
