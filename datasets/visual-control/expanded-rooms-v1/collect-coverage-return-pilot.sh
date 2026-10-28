#!/usr/bin/env bash
# Coverage teacher finds the brick; the student attempts return before recovery.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
root="$project/build/flex/sim/expanded-rooms-v1/large-model-v1"
runtime="$root/coverage-return-tests-v1/runtime"
baseline="$root/coverage-teacher-v2-pair-v1"
policy="$root/return-cohort-reversal-training-v1/policy"
auditor="$project/datasets/visual-control/expanded-rooms-v1/audit-coverage-teacher-v2.sh"
audit_jq="$project/datasets/visual-control/expanded-rooms-v1/audit-coverage-teacher-v2.jq"
out="${PUPPYBOT_COVERAGE_RETURN_PILOT_OUT:?New output directory required}"
[[ ! -e "$out" ]];mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
[[ "$(< "$baseline/run.exit")" == 0 ]]
jq -e '.passed and .episodes==4 and .identicalScenesAndInitialActorInputs and .identicalFirstStudentAction and ([.rows[]|select(.candidateReturn)]|length)==4' "$baseline/comparison.json" > /dev/null
mkdir "$out/catalog";cp -a "$root/coverage-teacher-cohort-v1/catalog/0" "$out/catalog/0";cp -a "$root/coverage-teacher-cohort-v1/catalog/2" "$out/catalog/1"
sha256sum "$runtime/build/flex/control/control" "$runtime/build/flex/control/simulator" "$runtime/build/flex/sim/puppybot.bin" "$policy/weights.bin" "$policy/policy" "$policy/receipt.json" "$auditor" "$audit_jq" "$baseline/comparison.json" "$out"/catalog/{0,1}/{case.json,environment.bin,layout.json} > "$out/inputs.sha256"
sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1 PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
cd "$runtime"
./build/flex/control/control correct --policy "$policy" --scene-catalog "$out/catalog" --output "$out/runs" --episodes 2 --validation 1 --rollin 5 --rollin-min 5 --horizon 300 --label-rollin --return-rollin --coverage-teacher --seed 1992000 --large-model > "$out/collect.log" 2>&1
./build/flex/control/control pack-data --data "$out/runs/data.bin" --output "$out/packed" > "$out/pack.log" 2>&1
./build/flex/control/control verify-data --run "$out/runs" --data "$out/packed/data.bin" --output "$out/verified" --large-model > "$out/verify.log" 2>&1
jq -e '.passed and .episodes==2 and .studentPolicies256==2 and .studentRollinCommandsReplayed>=2 and .studentRollinCommandsReplayed<=10 and .studentRollinMaxAbsError==0 and .denseOracleLabels and .datasetInputsMatchActualRGBAndOwnFeedback and .executedCommandsMatchRecordings and .taskEventHintAbsent' "$out/verified/result.json" > /dev/null
for i in 0 1;do
    run="$out/runs/expert-$i"
    jq -e '.searchTeacher=="coverage-camera-v2" and .studentBeginsAfterConsumption and .studentStartAction>=1 and .studentActions>=1 and .studentActions<=5 and .denseOracleLabels and .teacherPlannerUsesPrivilegedGeometry and (.searchGoalsUseUnseenBrickPosition|not)' "$run/supervision.json" > /dev/null
    bash "$auditor" "$run" "$out/goal-audit-$i"
done
sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
jq -n --slurpfile report "$out/runs/report.json" --slurpfile audit "$out/verified/result.json" --slurpfile a "$out/runs/expert-0/supervision.json" --slurpfile b "$out/runs/expert-1/supervision.json" '{passed:true,episodes:2,teacherSearchesFirst:true,studentReturnActionsReplayed:$audit[0].studentRollinCommandsReplayed,studentReturnWindows:[$a[0].studentActions,$b[0].studentActions],studentCompletedBeforeHandoff:([$a[0],$b[0]]|map(select(.studentCompletedBeforeHandoff))|length),teacherAssistedCompleted:$report[0].teacherCompleted,teacherGoalsReconstructed:true,actorInputsCheckedByReplay:true,autonomousWholeEpisodeSuccessClaimed:false,automaticMerge:false}' > "$out/summary.json"
echo 'Coverage-search and student-return pilot passed replay and search-goal checks.'
