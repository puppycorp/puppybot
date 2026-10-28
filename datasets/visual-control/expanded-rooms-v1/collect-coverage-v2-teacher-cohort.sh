#!/usr/bin/env bash
# Eight revised coverage-teacher demonstrations after one student action each.
set -euo pipefail
reject_known_hash() {
    local status=0
    /usr/bin/rg -Fxq "$1" "$2" || status=$?
    if (( status==0 ));then echo "Duplicate file hash: $1" >&2;exit 1;fi
    if (( status!=1 ));then echo "Could not check prior hashes: $2" >&2;exit "$status";fi
}
project="${PUPPYBOT_PROJECT:?Project root required}"
base="$project/build/flex/sim/expanded-rooms-v1"
root="$base/large-model-v1"
corpus="$root/student-only-admission-v1"
pilot="$root/coverage-teacher-v2-pair-v1"
runtime="$root/coverage-teacher-v2-runtime-v1/runtime"
generator="$root/correction-v1/generate-diverse"
policy="$root/gated-search-pair-v1/augmented-policy"
goal_audit="$project/datasets/visual-control/expanded-rooms-v1/audit-coverage-teacher-v2.sh"
goal_audit_jq="$project/datasets/visual-control/expanded-rooms-v1/audit-coverage-teacher-v2.jq"
out="${PUPPYBOT_COVERAGE_V2_TEACHER_OUT:?New output directory required}"
[[ ! -e "$out" ]]
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
for job in "$corpus/run" "$pilot/run";do
    while [[ ! -f "$job.exit" ]];do [[ -f "$job.pid" ]] && kill -0 "$(< "$job.pid")" || { echo "$job ended without a status." >&2;exit 1; }; /usr/bin/sleep 20;done
    [[ "$(< "$job.exit")" == 0 ]] || { echo "$job failed; collection not started." >&2;exit 1; }
done
data="$corpus/expanded/data.bin";data_sha="$(/usr/bin/sha256sum "$data" | /usr/bin/cut -d' ' -f1)";policy_sha="$(/usr/bin/sha256sum "$policy/weights.bin" | /usr/bin/cut -d' ' -f1)"
n="$(/usr/bin/jq -r '.episodes' "$corpus/coverage.json")"
[[ "$n" == 292 ]]
/usr/bin/jq -e --arg sha "$data_sha" '.passed and .dataSHA256==$sha and .newHistoriesIndependentlyAudited and .actorInputsUnchanged' "$corpus/coverage.json" > /dev/null
/usr/bin/jq -e '.passed and .episodes==4 and .identicalScenesAndInitialActorInputs and .identicalFirstStudentAction and .teacherControlledAfterFirstAction and ([.rows[]|select(.candidateReturn)]|length)>=3 and ([.rows[]|select(.layout=="two-room" and .candidateReturn)]|length)>=1 and (.studentAutonomousSuccessClaimed|not)' "$pilot/comparison.json" > /dev/null
/usr/bin/jq -e --arg sha "$policy_sha" '.weightsSHA256==$sha and .memoryWidth==256 and (.taskFeedback|not)' "$policy/receipt.json" > /dev/null
"$generator" "$out/fit" 59 63 fit > "$out/generate-fit.log"
"$generator" "$out/validation" 159 163 validation > "$out/generate-validation.log"
mkdir "$out/catalog";layouts=(60 59 62 61 160 159 162 161)
for episode in {0..7};do role=fit;if (( episode>=4 ));then role=validation;fi;cp -a "$out/$role/${layouts[$episode]}/4" "$out/catalog/$episode";done
for ((index=0;index<n;index++));do for file in case.json environment.bin;do /usr/bin/sha256sum "$corpus/expanded/expert-$index/scene/$file" | /usr/bin/tee -a "$out/prior-inputs.sha256" | /usr/bin/cut -d' ' -f1;done;done > "$out/prior-hashes.txt"
for layout in 18 19 20 21 22 23;do
    parent=generalization-benchmark-v1;if (( layout<20 ));then parent=unseen-benchmark-v2;fi
    for scene in {0..15};do for file in case.json environment.bin;do /usr/bin/sha256sum "$base/$parent/scenes/$layout/$scene/$file" | /usr/bin/tee -a "$out/prior-inputs.sha256" | /usr/bin/cut -d' ' -f1;done;done
done >> "$out/prior-hashes.txt"
for cohort in coverage-student-cohort-v1 coverage-teacher-cohort-v1;do for episode in 0 1 2 3;do for file in case.json environment.bin;do /usr/bin/sha256sum "$root/$cohort/catalog/$episode/$file" | /usr/bin/tee -a "$out/prior-inputs.sha256" | /usr/bin/cut -d' ' -f1;done;done;done >> "$out/prior-hashes.txt"
for episode in {0..7};do
    scene="$out/catalog/$episode";layout="${layouts[$episode]}";fit=true;rooms=1;if (( episode>=4 ));then fit=false;fi;if (( layout%2 ));then rooms=2;fi
    /usr/bin/jq -e --argjson layout "$layout" --argjson fit "$fit" --argjson rooms "$rooms" '.layoutId==$layout and .fit==$fit and (.rooms|length)==$rooms' "$scene/layout.json" > /dev/null
    for file in case.json environment.bin;do digest="$(/usr/bin/sha256sum "$scene/$file" | /usr/bin/cut -d' ' -f1)";reject_known_hash "$digest" "$out/prior-hashes.txt";printf '%s\n' "$digest" >> "$out/prior-hashes.txt";done
done
/usr/bin/sha256sum "$generator" "$runtime/build/flex/control/control" "$runtime/build/flex/control/simulator" "$runtime/build/flex/sim/puppybot.bin" "$data" "$corpus/coverage.json" "$pilot/comparison.json" "$goal_audit" "$goal_audit_jq" "$policy/weights.bin" "$policy/policy" "$policy/receipt.json" "$out"/catalog/{0..7}/{case.json,environment.bin,layout.json} > "$out/inputs.sha256"
find "$runtime/build/flex/control/kernels" -type f -print0 | /usr/bin/sort -z | /usr/bin/xargs -0 /usr/bin/sha256sum >> "$out/inputs.sha256"
export PATH="$base/unseen-benchmark-v2/native-path:$PATH" XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1 PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
cd "$runtime"
./build/flex/control/control correct --policy "$policy" --output "$out/runs" --scene-catalog "$out/catalog" --episodes 8 --validation 4 --rollin 1 --rollin-min 1 --horizon 300 --label-rollin --allow-incomplete --coverage-teacher --seed 1993000 --large-model > "$out/collect.log" 2>&1
./build/flex/control/control pack-data --data "$out/runs/data.bin" --output "$out/packed" > "$out/pack.log" 2>&1
./build/flex/control/control verify-data --run "$out/runs" --data "$out/packed/data.bin" --output "$out/verified" --allow-incomplete --large-model > "$out/verify.log" 2>&1
sha="$(/usr/bin/sha256sum "$out/packed/data.bin" | /usr/bin/cut -d' ' -f1)";actions="$(/usr/bin/jq -r '.studentRollinActions' "$out/runs/report.json")"
/usr/bin/jq -e --arg sha "$sha" --argjson actions "$actions" '.passed and .episodes==8 and .studentPolicies256==8 and .studentRollinCommandsReplayed==$actions and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .executedCommandsMatchRecordings and .denseOracleLabels and .preActionAlignmentChecked and .zeroPaddingChecked and .taskEventHintAbsent and .dataSHA256==$sha and (.incompleteEpisodesClaimedSuccessful|not)' "$out/verified/result.json" > /dev/null
for episode in {0..7};do
    run="$out/runs/expert-$episode"
    /usr/bin/jq -e --arg sha "$policy_sha" '.studentMemoryWidth==256 and .studentWeightsSHA256==$sha and (.studentBeginsAfterConsumption|not) and .studentStartAction==0 and .denseOracleLabels and .allowIncomplete and .scheduledRollinActions==1 and .studentActions==1 and .searchTeacher=="coverage-camera-v2" and .teacherPlannerUsesPrivilegedGeometry and (.searchGoalsUseUnseenBrickPosition|not) and (.terminationReason=="horizon" or .terminationReason=="oracle-unavailable" or .terminationReason=="success")' "$run/supervision.json" > /dev/null
    for file in case.json environment.bin;do /usr/bin/cmp "$out/catalog/$episode/$file" "$run/scene/$file";done
    /usr/bin/bash "$goal_audit" "$run" "$out/goal-audit-$episode"
    /usr/bin/jq -e '.passed and .brickPositionNotReadBySearchReconstruction and .oracleLabelsMatched' "$out/goal-audit-$episode/result.json" > /dev/null
done
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
/usr/bin/sha256sum -c "$out/prior-inputs.sha256" > "$out/prior-integrity-after.log"
/usr/bin/jq -n --arg sha "$sha" --argjson actions "$actions" --slurpfile audit "$out/verified/result.json" --slurpfile report "$out/runs/report.json" '{passed:true,episodes:8,openEpisodes:4,hiddenEpisodes:4,studentRollinActionsReplayed:$actions,incompleteEpisodes:$audit[0].incompleteEpisodes,teacherAssistedCompleted:$report[0].teacherCompleted,dataSHA256:$sha,denseOracleLabels:true,teacherControlledAfterFirstAction:true,teacherSearchGoalsReconstructed:true,teacherPlannerUsesPrivilegedGeometry:true,teacherLabelsTrainingOnly:true,actorTaskEventHint:false,studentAutonomousSuccessClaimed:false,automaticMerge:false}' > "$out/summary.json"
echo 'Coverage-teacher demonstrations passed replay and search-goal reconstruction.'
