#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
base="$project/build/flex/sim/expanded-rooms-v1"
root="$base/large-model-v1"
pilot="$root/return-correction-pilot-v1"
old="$root/correction-admission-v1"
out="$root/return-admission-v1"
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
for job in "$old/run" "$pilot/run"; do
    while [[ ! -f "$job.exit" ]]; do
        [[ -f "$job.pid" ]] && kill -0 "$(< "$job.pid")" || { echo "$job ended without a status." >&2; exit 1; }
        /usr/bin/sleep 20
    done
    [[ "$(< "$job.exit")" == 0 ]] || { echo "$job failed; return data not admitted." >&2; exit 1; }
done
old_data="$old/expanded/data.bin"
old_sha="$(/usr/bin/sha256sum "$old_data" | /usr/bin/cut -d' ' -f1)"
new_data="$pilot/packed/data.bin"
new_sha="$(/usr/bin/sha256sum "$new_data" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$old_sha" '.passed and .episodes==254 and .fittingHistories==190 and .validationHistories==64 and .dataSHA256==$sha and .existingDataBytePreserved and .existingTargetsBytePreserved and .newHistoriesIndependentlyAudited' "$old/coverage.json" > /dev/null
/usr/bin/jq -e --arg sha "$new_sha" '.passed and .episodes==2 and .fittingHistories==1 and .validationHistories==1 and .dataSHA256==$sha and .teacherReachedBrickBeforeStudentRollin and .teacherLabelsTrainingOnly and (.actorTaskEventHint|not) and (.studentAutonomousSuccessClaimed|not)' "$pilot/summary.json" > /dev/null
/usr/bin/sha256sum -c "$pilot/inputs.sha256" > "$out/pilot-integrity.log"
/usr/bin/sha256sum "$merger" "$target_merger" "$control" "$survey" "$prepare" "$preflight" "$data_preserve" "$target_preserve" "$old_data" "$old/targets/targets.bin" "$old/targets/receipt.json" "$new_data" "$pilot/verified/result.json" "$pilot/summary.json" > "$out/inputs.sha256"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
"$survey" "$new_data" "$pilot/runs" "$out/survey.json" 2 "$new_sha" "$out/candidates.jsonl" > "$out/survey.log" 2>&1
candidate_sha="$(/usr/bin/sha256sum "$out/candidates.jsonl" | /usr/bin/cut -d' ' -f1)"
"$prepare" "$new_data" "$pilot/runs" "$out/candidates.jsonl" "$out/survey.json" "$new_sha" "$candidate_sha" "$out/new-targets" > "$out/prepare.log" 2>&1
"$merger" "$out/expanded" "$old_data" "$old/expanded" "$new_data" "$pilot/runs" > "$out/merge.log"
"$target_merger" "$old_data" "$old/targets" "$new_data" "$out/new-targets" "$out/expanded" "$out/targets" > "$out/target-merge.log"
"$data_preserve" "$old_data" "$out/expanded/data.bin" "$out/data-preserved.json" > "$out/data-preserved.log"
"$target_preserve" "$old/targets/targets.bin" "$out/targets/targets.bin" "$out/targets-preserved.json" > "$out/targets-preserved.log"
"$preflight" "$out/expanded/data.bin" "$out/targets" "$out/preflight.json" > "$out/preflight.log"
for report in "$out/data-preserved.json" "$out/targets-preserved.json"; do
    /usr/bin/jq -e '.passed and .existingHistoriesPreserved==254 and .expandedHistories==256 and .expandedFittingHistories==191' "$report" > /dev/null
done
export PATH="$base/unseen-benchmark-v2/native-path"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1
cd "$root/correction-v3/runtime"
"$control" verify-data --run "$out/expanded" --data "$out/expanded/data.bin" --output "$out/audit-fit" --audit-start 190 --audit-count 1 > "$out/audit-fit.log" 2>&1
"$control" verify-data --run "$out/expanded" --data "$out/expanded/data.bin" --output "$out/audit-validation" --audit-start 255 --audit-count 1 > "$out/audit-validation.log" 2>&1
for audit in "$out/audit-fit/result.json" "$out/audit-validation/result.json"; do
    /usr/bin/jq -e '.passed and .episodes==1 and .studentPolicies256==1 and .studentRollinCommandsReplayed>=1 and .studentRollinMaxAbsError==0 and .taskEventHintAbsent' "$audit" > /dev/null
done
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
/usr/bin/jq -n --arg old "$old_sha" --arg sha "$(/usr/bin/sha256sum "$out/expanded/data.bin" | /usr/bin/cut -d' ' -f1)" '{passed:true,episodes:256,fittingHistories:191,validationHistories:65,addedReturnHistories:2,oldDataSHA256:$old,dataSHA256:$sha,existingDataBytePreserved:true,existingTargetsBytePreserved:true,newHistoriesIndependentlyAudited:true,teacherLabelsTrainingOnly:true,actorInputsUnchanged:true,studentAutonomousSuccessClaimed:false}' > "$out/coverage.json"
