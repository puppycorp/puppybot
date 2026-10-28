#!/usr/bin/env bash
# Add audited coverage-labeled student histories with masked target labels.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
base="$project/build/flex/sim/expanded-rooms-v1"
root="$base/large-model-v1"
old="$root/student-only-admission-v1"
pilot="$root/coverage-student-cohort-v1"
runtime="$root/coverage-student-runtime-v1/runtime"
bin="$root/source/admission-cohort-v3/bin"
survey="$base/return-labels-v1/survey"
prepare="$root/empty-target-build-v2/prepare"
merge_targets="$root/empty-target-build-v2/merge-targets"
out="${PUPPYBOT_COVERAGE_STUDENT_ADMISSION_OUT:?New output directory required}"
[[ ! -e "$out" ]]
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
for job in "$old/run" "$pilot/run";do
    while [[ ! -f "$job.exit" ]];do [[ -f "$job.pid" ]] && kill -0 "$(< "$job.pid")" || { echo "$job ended without a status." >&2;exit 1; }; /usr/bin/sleep 20;done
    [[ "$(< "$job.exit")" == 0 ]] || { echo "$job failed; no histories admitted." >&2;exit 1; }
done
old_data="$old/expanded/data.bin";new_data="$pilot/packed/data.bin"
old_sha="$(/usr/bin/sha256sum "$old_data" | /usr/bin/cut -d' ' -f1)";new_sha="$(/usr/bin/sha256sum "$new_data" | /usr/bin/cut -d' ' -f1)"
n="$(/usr/bin/jq -r '.episodes' "$old/coverage.json")";fit="$(/usr/bin/jq -r '.fittingHistories' "$old/coverage.json")";validation="$(/usr/bin/jq -r '.validationHistories' "$old/coverage.json")"
[[ "$n" == 292 && "$fit" == 209 && "$validation" == 83 ]]
/usr/bin/jq -e --arg sha "$old_sha" '.passed and .dataSHA256==$sha and .newHistoriesIndependentlyAudited and .existingDataBytePreserved and .existingTargetsBytePreserved and .teacherLabelsTrainingOnly and .actorInputsUnchanged' "$old/coverage.json" > /dev/null
/usr/bin/jq -e --arg sha "$new_sha" '.passed and .episodes==4 and .openEpisodes==2 and .hiddenEpisodes==2 and .dataSHA256==$sha and .denseOracleLabels and .teacherSearchGoalsReconstructed and .teacherPlannerUsesPrivilegedGeometry and .teacherLabelsTrainingOnly and (.actorTaskEventHint|not) and (.studentAutonomousSuccessClaimed|not) and (.automaticMerge|not)' "$pilot/summary.json" > /dev/null
/usr/bin/jq -e --arg sha "$new_sha" '.passed and .episodes==4 and .datasetEpisodes==4 and .dataSHA256==$sha and .studentRollinMaxAbsError==0 and .denseOracleLabels and .datasetInputsMatchActualRGBAndOwnFeedback and .executedCommandsMatchRecordings and .preActionAlignmentChecked and .zeroPaddingChecked and .taskEventHintAbsent and (.incompleteEpisodesClaimedSuccessful|not)' "$pilot/verified/result.json" > /dev/null
for i in 0 1 2 3;do /usr/bin/jq -e '.passed and .brickPositionNotReadBySearchReconstruction and .oracleLabelsMatched' "$pilot/goal-audit-$i/result.json" > /dev/null;done
/usr/bin/sha256sum -c "$pilot/inputs.sha256" > "$out/pilot-integrity.log"
/usr/bin/sha256sum -c "$pilot/prior-inputs.sha256" > "$out/prior-integrity.log"
/usr/bin/sha256sum "$bin"/* "$runtime/build/flex/control/control" "$runtime/build/flex/control/simulator" "$survey" "$prepare" "$merge_targets" "$old_data" "$old/targets/targets.bin" "$old/targets/receipt.json" "$old/coverage.json" "$new_data" "$pilot/summary.json" "$pilot/verified/result.json" "$pilot"/goal-audit-{0,1,2,3}/result.json "$pilot"/runs/expert-{0,1,2,3}/supervision.json > "$out/inputs.sha256"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
mkdir "$out/labels"
"$survey" "$new_data" "$pilot/runs" "$out/labels/survey.json" 4 "$new_sha" "$out/labels/candidates.jsonl" > "$out/labels/survey.log" 2>&1
candidates="$(/usr/bin/sha256sum "$out/labels/candidates.jsonl" | /usr/bin/cut -d' ' -f1)"
"$prepare" "$new_data" "$pilot/runs" "$out/labels/candidates.jsonl" "$out/labels/survey.json" "$new_sha" "$candidates" "$out/labels/targets" --allow-empty-splits > "$out/labels/prepare.log" 2>&1
/usr/bin/jq -e --arg sha "$new_sha" '.passed and .sourceDataSHA256==$sha and .allowEmptyCandidateSplits and .projectionAndPixelsIndependentlyRechecked and .actorInputsUnchanged' "$out/labels/targets/receipt.json" > /dev/null
"$bin/merge-dense-many" "$out/expanded" "$old_data" "$old/expanded" "$new_data" "$pilot/runs" > "$out/expanded.log"
"$merge_targets" "$out/expanded" "$out/targets" "$old_data" "$old/targets" "$new_data" "$out/labels/targets" > "$out/targets.log"
"$bin/data-preserve-added" "$old_data" "$out/expanded/data.bin" "$out/data-preserved.json"
"$bin/target-preserve-added" "$old/targets/targets.bin" "$out/targets/targets.bin" "$out/targets-preserved.json"
"$bin/preflight-expanded-targets" "$out/expanded/data.bin" "$out/targets" "$out/preflight.json"
total=$((n+4));new_fit=$((fit+2));new_validation=$((validation+2));validation_start=$((new_fit+validation))
for report in "$out/data-preserved.json" "$out/targets-preserved.json";do /usr/bin/jq -e --argjson old "$n" --argjson n "$total" --argjson fit "$new_fit" '.passed and .existingHistoriesPreserved==$old and .expandedHistories==$n and .expandedFittingHistories==$fit' "$report" > /dev/null;done
/usr/bin/jq -e --argjson n "$total" --argjson fit "$new_fit" --argjson val "$new_validation" '.passed and .episodes==$n and .fittingHistories==$fit and .validationHistories==$val and .actorInputsUnchanged' "$out/preflight.json" > /dev/null
expanded_sha="$(/usr/bin/sha256sum "$out/expanded/data.bin" | /usr/bin/cut -d' ' -f1)"
fit_actions="$(/usr/bin/jq -s '[.[].studentActions]|add' "$pilot"/runs/expert-{0,1}/supervision.json)";validation_actions="$(/usr/bin/jq -s '[.[].studentActions]|add' "$pilot"/runs/expert-{2,3}/supervision.json)"
export PATH="$base/unseen-benchmark-v2/native-path:$PATH" XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1 PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
cd "$runtime"
./build/flex/control/control verify-data --run "$out/expanded" --data "$out/expanded/data.bin" --output "$out/audit-fit" --audit-start "$fit" --audit-count 2 --allow-incomplete --large-model > "$out/audit-fit.log" 2>&1
./build/flex/control/control verify-data --run "$out/expanded" --data "$out/expanded/data.bin" --output "$out/audit-validation" --audit-start "$validation_start" --audit-count 2 --allow-incomplete --large-model > "$out/audit-validation.log" 2>&1
for role in fit validation;do expected="$fit_actions";if [[ "$role" == validation ]];then expected="$validation_actions";fi
    /usr/bin/jq -e --arg sha "$expanded_sha" --argjson n "$total" --argjson expected "$expected" '.passed and .datasetEpisodes==$n and .episodes==2 and .dataSHA256==$sha and .studentPolicies256==2 and .studentRollinCommandsReplayed==$expected and .studentRollinMaxAbsError==0 and .denseOracleLabels and .taskEventHintAbsent and (.incompleteEpisodesClaimedSuccessful|not)' "$out/audit-$role/result.json" > /dev/null
done
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
[[ "$(/usr/bin/sha256sum "$out/expanded/data.bin" | /usr/bin/cut -d' ' -f1)" == "$expanded_sha" ]]
/usr/bin/jq -n --arg old "$old_sha" --arg sha "$expanded_sha" --argjson n "$total" --argjson fit "$new_fit" --argjson val "$new_validation" --argjson actions "$((fit_actions+validation_actions))" --slurpfile a "$out/audit-fit/result.json" --slurpfile b "$out/audit-validation/result.json" '{passed:true,episodes:$n,fittingHistories:$fit,validationHistories:$val,addedCoverageStudentHistories:4,studentRollinActionsReplayed:$actions,incompleteAddedEpisodes:($a[0].incompleteEpisodes+$b[0].incompleteEpisodes),oldDataSHA256:$old,dataSHA256:$sha,existingDataBytePreserved:true,existingTargetsBytePreserved:true,newHistoriesIndependentlyAudited:true,teacherSearchGoalsReconstructed:true,teacherLabelsTrainingOnly:true,actorInputsUnchanged:true,incompleteEpisodesClaimedSuccessful:false,automaticPromotion:false}' > "$out/coverage.json"
echo 'Coverage-labeled student histories were audited and merged with unobserved target frames masked.'
