#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
base="$project/build/flex/sim/expanded-rooms-v1"
root="$base/large-model-v1"
cohort="$root/correction-cohort-v1"
pilot="$root/correction-v1"
out="$root/correction-admission-v1"
old="$base/return-admission-v1/merged-7"
old_targets="$base/return-labels-v1/targets"
merger="$root/correction-v3/merge-dense-many"
target_merger="$root/correction-v3/merge-targets-two"
control="$root/correction-v3/runtime/build/flex/control/control"
survey="$base/return-labels-v1/survey"
prepare="$base/return-labels-v1/prepare"
preflight="$base/return-labels-v1/preflight"
data_preserve="$base/return-admission-v1/preserve"
target_preserve="$base/return-labels-v1/preserve"
[[ ! -e "$out" ]]
/usr/bin/mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
while [[ ! -f "$cohort/run.exit" ]]; do
    [[ -f "$cohort/run.pid" ]] && kill -0 "$(< "$cohort/run.pid")" || { echo 'Correction collection ended without a status.' >&2; exit 1; }
    /usr/bin/sleep 20
done
[[ "$(< "$cohort/run.exit")" == 0 ]]
/usr/bin/jq -e '.complete and .attemptedWorkers==8 and .successfulWorkers>=4 and .auditedHistories==(.successfulWorkers*2) and .partialArtifactsRetained and (.automaticMerge|not) and (.studentAutonomousSuccessClaimed|not) and (any(.rows[]; .passed and (.worker%2)==0)) and (any(.rows[]; .passed and (.worker%2)==1))' "$cohort/summary.json" > /dev/null
/usr/bin/sha256sum -c "$cohort/inputs.sha256" > "$out/cohort-integrity.log"
old_sha="$(/usr/bin/sha256sum "$old/data.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$old_sha" '.passed and .episodes==236 and .fittingHistories==181 and .validationHistories==55 and .dataSHA256==$sha and .allNewTripsIndependentlyAudited and .existingDataBytePreserved' "$base/return-admission-v1/coverage.json" > /dev/null
pilot_sha="$(/usr/bin/sha256sum "$pilot/packed/data.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$pilot_sha" '.passed and .episodes==2 and .dataSHA256==$sha and .studentRollinCommandsReplayed==20 and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .denseOracleLabels and .taskEventHintAbsent' "$pilot/verified/result.json" > /dev/null
args=("$pilot/packed/data.bin" "$pilot/runs")
replayed=20
for ((worker=0;worker<8;worker++)); do
    record="$cohort/worker-$worker.json"
    if /usr/bin/jq -e '.passed' "$record" > /dev/null; then
        work="$cohort/worker-$worker"; data="$work/packed/data.bin"
        data_sha="$(/usr/bin/sha256sum "$data" | /usr/bin/cut -d' ' -f1)"
        student="$(/usr/bin/jq -r '.studentCommandsReplayed' "$record")"
        /usr/bin/jq -e --arg sha "$data_sha" --arg path "$data" --argjson student "$student" '.passed and .episodes==2 and .studentCommandsReplayed==$student and .dataSHA256==$sha and .dataFile==$path and .teacherAssisted and (.studentAutonomousSuccessClaimed|not)' "$record" > /dev/null
        /usr/bin/jq -e --arg sha "$data_sha" --argjson student "$student" '.passed and .episodes==2 and .dataSHA256==$sha and .studentRollinCommandsReplayed==$student and .studentRollinMaxAbsError==0 and .denseOracleLabels and .taskEventHintAbsent' "$work/verified/result.json" > /dev/null
        args+=("$data" "$work/runs"); replayed=$((replayed+student))
    fi
done
/usr/bin/sha256sum "$merger" "$target_merger" "$control" "$survey" "$prepare" "$preflight" "$data_preserve" "$target_preserve" "$old/data.bin" "$old_targets/targets.bin" "$old_targets/receipt.json" "$cohort/summary.json" "$pilot/packed/data.bin" "$pilot/verified/result.json" > "$out/inputs.sha256"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
"$merger" "$out/new" "${args[@]}" > "$out/new-merge.log"
new_n="$(/usr/bin/jq -r '.episodes' "$out/new/report.json")"
new_fit="$(/usr/bin/jq -r '.fitTrajectories' "$out/new/report.json")"
/usr/bin/jq -e '.preservesFitValidationSplits and .episodes>=10 and .fitTrajectories*2==.episodes and ([.records[].fit]|all(.==true or .==false))' "$out/new/report.json" > /dev/null
export PATH="$base/unseen-benchmark-v2/native-path"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1
cd "$root/correction-v3/runtime"
"$control" verify-data --run "$out/new" --data "$out/new/data.bin" --output "$out/new-audit" > "$out/new-audit.log" 2>&1
new_sha="$(/usr/bin/sha256sum "$out/new/data.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$new_sha" --argjson n "$new_n" --argjson replayed "$replayed" '.passed and .episodes==$n and .datasetEpisodes==$n and .studentPolicies128==0 and .studentPolicies256==$n and .studentRollinCommandsReplayed==$replayed and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .denseOracleLabels and .taskEventHintAbsent and .dataSHA256==$sha' "$out/new-audit/result.json" > /dev/null
"$survey" "$out/new/data.bin" "$out/new" "$out/survey.json" "$new_n" "$new_sha" "$out/candidates.jsonl" > "$out/survey.log" 2>&1
candidate_sha="$(/usr/bin/sha256sum "$out/candidates.jsonl" | /usr/bin/cut -d' ' -f1)"
"$prepare" "$out/new/data.bin" "$out/new" "$out/candidates.jsonl" "$out/survey.json" "$new_sha" "$candidate_sha" "$out/new-targets" > "$out/prepare.log" 2>&1
"$merger" "$out/expanded" "$old/data.bin" "$old" "$out/new/data.bin" "$out/new" > "$out/expanded-merge.log"
"$target_merger" "$old/data.bin" "$old_targets" "$out/new/data.bin" "$out/new-targets" "$out/expanded" "$out/targets" > "$out/target-merge.log"
"$data_preserve" "$old/data.bin" "$out/expanded/data.bin" "$out/data-preserved.json" > "$out/data-preserved.log"
"$target_preserve" "$old_targets/targets.bin" "$out/targets/targets.bin" "$out/targets-preserved.json" > "$out/targets-preserved.log"
"$preflight" "$out/expanded/data.bin" "$out/targets" "$out/preflight.json" > "$out/preflight.log"
expanded_n=$((236+new_n)); expanded_fit=$((181+new_fit)); val_start=$((expanded_fit+55))
/usr/bin/jq -e --argjson n "$expanded_n" --argjson fit "$expanded_fit" '.passed and .existingHistoriesPreserved==236 and .expandedHistories==$n and .expandedFittingHistories==$fit' "$out/data-preserved.json" > /dev/null
/usr/bin/jq -e --argjson n "$expanded_n" --argjson fit "$expanded_fit" '.passed and .existingHistoriesPreserved==236 and .expandedHistories==$n and .expandedFittingHistories==$fit' "$out/targets-preserved.json" > /dev/null
"$control" verify-data --run "$out/expanded" --data "$out/expanded/data.bin" --output "$out/audit-fit" --audit-start 181 --audit-count "$new_fit" > "$out/audit-fit.log" 2>&1
"$control" verify-data --run "$out/expanded" --data "$out/expanded/data.bin" --output "$out/audit-validation" --audit-start "$val_start" --audit-count "$((new_n-new_fit))" > "$out/audit-validation.log" 2>&1
/usr/bin/jq -e --argjson n "$new_fit" '.passed and .episodes==$n and .studentPolicies256==$n and .studentRollinMaxAbsError==0 and .taskEventHintAbsent' "$out/audit-fit/result.json" > /dev/null
/usr/bin/jq -e --argjson n "$((new_n-new_fit))" '.passed and .episodes==$n and .studentPolicies256==$n and .studentRollinMaxAbsError==0 and .taskEventHintAbsent' "$out/audit-validation/result.json" > /dev/null
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
/usr/bin/jq -n --argjson n "$expanded_n" --argjson fit "$expanded_fit" --argjson added "$new_n" --argjson replayed "$replayed" --arg old "$old_sha" --arg sha "$(/usr/bin/sha256sum "$out/expanded/data.bin" | /usr/bin/cut -d' ' -f1)" '{passed:true,episodes:$n,fittingHistories:$fit,validationHistories:($n-$fit),addedHistories:$added,studentCommandsReplayed:$replayed,oldDataSHA256:$old,dataSHA256:$sha,existingDataBytePreserved:true,existingTargetsBytePreserved:true,newHistoriesIndependentlyAudited:true,teacherLabelsTrainingOnly:true,actorInputsUnchanged:true,studentAutonomousSuccessClaimed:false}' > "$out/coverage.json"
