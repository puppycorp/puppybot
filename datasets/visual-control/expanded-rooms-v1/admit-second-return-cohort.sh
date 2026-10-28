#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
base="$project/build/flex/sim/expanded-rooms-v1"
root="$base/large-model-v1"
cohort="$root/return-correction-cohort-v2"
old="$root/return-cohort-admission-v2"
out="$root/return-cohort-admission-v3"
runtime="$root/pvdata04-tests-v1/runtime"
bin="$root/source/admission-cohort-v3/bin"
survey="$base/return-labels-v1/survey"
prepare="$base/return-labels-v1/prepare"
[[ ! -e "$out" ]]
/usr/bin/mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
cd "$project"
for job in "$cohort/run" "$old/run"; do
    while [[ ! -f "$job.exit" ]]; do
        [[ -f "$job.pid" ]] && kill -0 "$(< "$job.pid")" || { echo "$job ended without a status." >&2; exit 1; }
        /usr/bin/sleep 20
    done
    [[ "$(< "$job.exit")" == 0 ]] || { echo "$job failed; no new histories admitted." >&2; exit 1; }
done
/usr/bin/jq -e '.complete and .attemptedWorkers==8 and .successfulWorkers==8 and .auditedHistories==16 and .studentCommandsReplayed>=16 and .studentCommandsReplayed<=960 and .failedWorkers==0 and (.automaticMerge|not) and (.studentAutonomousSuccessClaimed|not)' "$cohort/summary.json" > /dev/null
old_data="$old/expanded/data.bin"; old_sha="$(/usr/bin/sha256sum "$old_data" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$old_sha" '.passed and .episodes==264 and .fittingHistories==195 and .validationHistories==69 and .dataSHA256==$sha and .existingDataBytePreserved and .existingTargetsBytePreserved and .newHistoriesIndependentlyAudited and .teacherLabelsTrainingOnly and .actorInputsUnchanged' "$old/coverage.json" > /dev/null
/usr/bin/sha256sum -c "$cohort/inputs.sha256" > "$out/cohort-integrity.log"
/usr/bin/sha256sum "$bin"/* "$survey" "$prepare" "$runtime/build/flex/control/control" "$runtime/build/flex/control/simulator" "$old_data" "$old/targets/targets.bin" "$old/targets/receipt.json" "$old/coverage.json" "$cohort/summary.json" > "$out/inputs.sha256"
for worker in {0..7}; do
    work="$cohort/worker-$worker"
    /usr/bin/sha256sum "$work/packed/data.bin" "$work/verified/result.json" "$cohort/worker-$worker.json" >> "$out/inputs.sha256"
done
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
data_args=("$old_data" "$old/expanded"); target_args=("$old_data" "$old/targets"); fit_actions=0; validation_actions=0
for worker in {0..7}; do
    work="$cohort/worker-$worker"; data="$work/packed/data.bin"; labels="$out/labels-$worker"
    sha="$(/usr/bin/sha256sum "$data" | /usr/bin/cut -d' ' -f1)"; student="$(/usr/bin/jq -r .studentCommandsReplayed "$cohort/worker-$worker.json")"
    /usr/bin/jq -e --arg sha "$sha" --argjson student "$student" '.passed and .episodes==2 and .studentCommandsReplayed==$student and .dataSHA256==$sha and .teacherAssisted and (.studentAutonomousSuccessClaimed|not)' "$cohort/worker-$worker.json" > /dev/null
    /usr/bin/jq -e --arg sha "$sha" --argjson student "$student" '.passed and .episodes==2 and .studentPolicies256==2 and .studentRollinCommandsReplayed==$student and .studentRollinMaxAbsError==0 and .denseOracleLabels and .taskEventHintAbsent and .dataSHA256==$sha' "$work/verified/result.json" > /dev/null
    a="$(/usr/bin/jq -r .studentActions "$work/runs/expert-0/supervision.json")"; b="$(/usr/bin/jq -r .studentActions "$work/runs/expert-1/supervision.json")"
    (( a>=1 && a<=60 && b>=1 && b<=60 && a+b==student )); fit_actions=$((fit_actions+a)); validation_actions=$((validation_actions+b))
    /usr/bin/mkdir "$labels"
    "$survey" "$data" "$work/runs" "$labels/survey.json" 2 "$sha" "$labels/candidates.jsonl" > "$labels/survey.log" 2>&1
    candidates="$(/usr/bin/sha256sum "$labels/candidates.jsonl" | /usr/bin/cut -d' ' -f1)"
    "$prepare" "$data" "$work/runs" "$labels/candidates.jsonl" "$labels/survey.json" "$sha" "$candidates" "$labels/targets" > "$labels/prepare.log" 2>&1
    data_args+=("$data" "$work/runs"); target_args+=("$data" "$labels/targets")
done
/usr/bin/jq -e --argjson total "$((fit_actions+validation_actions))" '.studentCommandsReplayed==$total' "$cohort/summary.json" > /dev/null
"$bin/merge-dense-many" "$out/expanded" "${data_args[@]}" > "$out/expanded.log"
"$bin/merge-targets-many" "$out/expanded" "$out/targets" "${target_args[@]}" > "$out/targets.log"
[[ "$(/usr/bin/head -c 8 "$out/expanded/data.bin")" == PVDATA04 ]]
"$bin/data-preserve-added" "$old_data" "$out/expanded/data.bin" "$out/data-preserved.json"
"$bin/target-preserve-added" "$old/targets/targets.bin" "$out/targets/targets.bin" "$out/targets-preserved.json"
"$bin/preflight-expanded-targets" "$out/expanded/data.bin" "$out/targets" "$out/preflight.json"
for report in "$out/data-preserved.json" "$out/targets-preserved.json"; do
    /usr/bin/jq -e '.passed and .existingHistoriesPreserved==264 and .expandedHistories==280 and .expandedFittingHistories==203' "$report" > /dev/null
done
/usr/bin/jq -e '.passed and .episodes==280 and .fittingHistories==203 and .validationHistories==77 and .actorInputsUnchanged' "$out/preflight.json" > /dev/null
export PATH="$base/unseen-benchmark-v2/native-path"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1 PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
cd "$runtime"
./build/flex/control/control verify-data --run "$out/expanded" --data "$out/expanded/data.bin" --output "$out/audit-fit" --audit-start 195 --audit-count 8 > "$out/audit-fit.log" 2>&1
./build/flex/control/control verify-data --run "$out/expanded" --data "$out/expanded/data.bin" --output "$out/audit-validation" --audit-start 272 --audit-count 8 > "$out/audit-validation.log" 2>&1
for role in fit validation; do
    expected="$fit_actions"; if [[ "$role" == validation ]]; then expected="$validation_actions"; fi
    /usr/bin/jq -e --argjson expected "$expected" '.passed and .episodes==8 and .studentPolicies256==8 and .studentRollinCommandsReplayed==$expected and .studentRollinMaxAbsError==0 and .taskEventHintAbsent and .denseOracleLabels' "$out/audit-$role/result.json" > /dev/null
done
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
new_sha="$(/usr/bin/sha256sum "$out/expanded/data.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -n --arg old "$old_sha" --arg sha "$new_sha" --argjson actions "$((fit_actions+validation_actions))" '{passed:true,episodes:280,fittingHistories:203,validationHistories:77,addedReturnHistories:16,studentReturnActionsReplayed:$actions,oldDataSHA256:$old,dataSHA256:$sha,existingDataBytePreserved:true,existingTargetsBytePreserved:true,newHistoriesIndependentlyAudited:true,teacherLabelsTrainingOnly:true,actorInputsUnchanged:true,studentAutonomousSuccessClaimed:false,automaticPromotion:false}' > "$out/coverage.json"
