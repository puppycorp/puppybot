#!/usr/bin/env bash
set -euo pipefail

project="${PUPPYBOT_PROJECT:?Project root is required}"
base="$project/build/flex/sim/expanded-rooms-v1"
root="$base/large-model-v1"
cohort="$root/return-correction-cohort-v1"
old="$root/return-admission-v1"
out="$root/return-cohort-admission-v2"
runtime="$root/pvdata04-tests-v1/runtime"
bin="$root/source/admission-cohort-v2/bin"
survey="$base/return-labels-v1/survey"
prepare="$base/return-labels-v1/prepare"
[[ ! -e "$out" ]]
/usr/bin/mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
cd "$project"
while [[ ! -f "$cohort/run.exit" ]]; do
    [[ -f "$cohort/run.pid" ]] && kill -0 "$(< "$cohort/run.pid")" || { echo 'Collection ended without a terminal status.' >&2; exit 1; }
    /usr/bin/sleep 20
done
[[ "$(< "$cohort/run.exit")" == 0 && "$(< "$old/run.exit")" == 0 ]]
/usr/bin/jq -e '.complete and .attemptedWorkers==4 and .successfulWorkers==4 and .auditedHistories==8 and .studentCommandsReplayed==480 and .failedWorkers==0 and (.automaticMerge|not) and (.studentAutonomousSuccessClaimed|not)' "$cohort/summary.json" > /dev/null
old_data="$old/expanded/data.bin"
old_sha="$(/usr/bin/sha256sum "$old_data" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$old_sha" '.passed and .episodes==256 and .fittingHistories==191 and .validationHistories==65 and .dataSHA256==$sha and .existingDataBytePreserved and .existingTargetsBytePreserved and .newHistoriesIndependentlyAudited and .teacherLabelsTrainingOnly and .actorInputsUnchanged' "$old/coverage.json" > /dev/null
/usr/bin/sha256sum -c "$cohort/inputs.sha256" > "$out/cohort-integrity.log"
/usr/bin/sha256sum "$bin"/* "$survey" "$prepare" "$runtime/build/flex/control/control" "$runtime/build/flex/control/simulator" "$old_data" "$old/targets/targets.bin" "$old/targets/receipt.json" "$old/coverage.json" "$cohort/summary.json" > "$out/inputs.sha256"
for worker in {0..3}; do
    work="$cohort/worker-$worker"
    /usr/bin/sha256sum "$work/packed/data.bin" "$work/verified/result.json" "$cohort/worker-$worker.json" >> "$out/inputs.sha256"
done
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
for worker in {0..3}; do
    work="$cohort/worker-$worker"; data="$work/packed/data.bin"; labels="$out/labels-$worker"
    sha="$(/usr/bin/sha256sum "$data" | /usr/bin/cut -d' ' -f1)"
    /usr/bin/jq -e --arg sha "$sha" '.passed and .episodes==2 and .studentCommandsReplayed==120 and .dataSHA256==$sha and .teacherAssisted and (.studentAutonomousSuccessClaimed|not)' "$cohort/worker-$worker.json" > /dev/null
    /usr/bin/jq -e --arg sha "$sha" '.passed and .episodes==2 and .studentPolicies256==2 and .studentRollinCommandsReplayed==120 and .studentRollinMaxAbsError==0 and .denseOracleLabels and .taskEventHintAbsent and .dataSHA256==$sha' "$work/verified/result.json" > /dev/null
    /usr/bin/mkdir "$labels"
    "$survey" "$data" "$work/runs" "$labels/survey.json" 2 "$sha" "$labels/candidates.jsonl" > "$labels/survey.log" 2>&1
    candidates="$(/usr/bin/sha256sum "$labels/candidates.jsonl" | /usr/bin/cut -d' ' -f1)"
    "$prepare" "$data" "$work/runs" "$labels/candidates.jsonl" "$labels/survey.json" "$sha" "$candidates" "$labels/targets" > "$labels/prepare.log" 2>&1
done
for pair in 0 1; do
    first=$((pair*2)); second=$((first+1)); a="$cohort/worker-$first"; b="$cohort/worker-$second"
    "$bin/merge-dense-many" "$out/pair-$pair" "$a/packed/data.bin" "$a/runs" "$b/packed/data.bin" "$b/runs" > "$out/pair-$pair.log"
    "$bin/merge-targets-two" "$a/packed/data.bin" "$out/labels-$first/targets" "$b/packed/data.bin" "$out/labels-$second/targets" "$out/pair-$pair" "$out/pair-$pair-targets" > "$out/pair-$pair-targets.log"
done
"$bin/merge-dense-many" "$out/new" "$out/pair-0/data.bin" "$out/pair-0" "$out/pair-1/data.bin" "$out/pair-1" > "$out/new.log"
"$bin/merge-targets-two" "$out/pair-0/data.bin" "$out/pair-0-targets" "$out/pair-1/data.bin" "$out/pair-1-targets" "$out/new" "$out/new-targets" > "$out/new-targets.log"
"$bin/merge-dense-many" "$out/expanded" "$old_data" "$old/expanded" "$out/new/data.bin" "$out/new" > "$out/expanded.log"
"$bin/merge-targets-two" "$old_data" "$old/targets" "$out/new/data.bin" "$out/new-targets" "$out/expanded" "$out/targets" > "$out/targets.log"
[[ "$(/usr/bin/head -c 8 "$out/expanded/data.bin")" == PVDATA04 ]]
"$bin/data-preserve-added" "$old_data" "$out/expanded/data.bin" "$out/data-preserved.json"
"$bin/target-preserve-added" "$old/targets/targets.bin" "$out/targets/targets.bin" "$out/targets-preserved.json"
"$bin/preflight-expanded-targets" "$out/expanded/data.bin" "$out/targets" "$out/preflight.json"
for report in "$out/data-preserved.json" "$out/targets-preserved.json"; do
    /usr/bin/jq -e '.passed and .existingHistoriesPreserved==256 and .expandedHistories==264 and .expandedFittingHistories==195' "$report" > /dev/null
done
/usr/bin/jq -e '.passed and .episodes==264 and .fittingHistories==195 and .validationHistories==69 and .actorInputsUnchanged' "$out/preflight.json" > /dev/null
export PATH="$base/unseen-benchmark-v2/native-path"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1 PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
cd "$runtime"
./build/flex/control/control verify-data --run "$out/expanded" --data "$out/expanded/data.bin" --output "$out/audit-fit" --audit-start 191 --audit-count 4 > "$out/audit-fit.log" 2>&1
./build/flex/control/control verify-data --run "$out/expanded" --data "$out/expanded/data.bin" --output "$out/audit-validation" --audit-start 260 --audit-count 4 > "$out/audit-validation.log" 2>&1
for audit in "$out/audit-fit/result.json" "$out/audit-validation/result.json"; do
    /usr/bin/jq -e '.passed and .episodes==4 and .studentPolicies256==4 and .studentRollinCommandsReplayed==240 and .studentRollinMaxAbsError==0 and .taskEventHintAbsent and .denseOracleLabels' "$audit" > /dev/null
done
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
new_sha="$(/usr/bin/sha256sum "$out/expanded/data.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -n --arg old "$old_sha" --arg sha "$new_sha" '{passed:true,episodes:264,fittingHistories:195,validationHistories:69,addedReturnHistories:8,studentReturnActionsReplayed:480,oldDataSHA256:$old,dataSHA256:$sha,existingDataBytePreserved:true,existingTargetsBytePreserved:true,newHistoriesIndependentlyAudited:true,teacherLabelsTrainingOnly:true,actorInputsUnchanged:true,studentAutonomousSuccessClaimed:false,automaticPromotion:false}' > "$out/coverage.json"
