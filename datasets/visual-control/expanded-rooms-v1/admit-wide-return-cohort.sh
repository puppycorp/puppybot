#!/usr/bin/env bash
# Admit only complete, replay-verified teacher-search/student-return pairs.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
base="$project/build/flex/sim/expanded-rooms-v1";root="$base/large-model-v1"
old="$root/return-reuse-admission-v1";cohort="$root/wide-return-cohort-v1";catalog="$root/wide-return-catalog-v1"
runtime="$root/coverage-return-tests-v1/runtime";bin="$root/source/admission-cohort-v3/bin"
survey="$base/return-labels-v1/survey";prepare="$root/empty-target-build-v2/prepare";merge_targets="$root/empty-target-build-v2/merge-targets"
out="${PUPPYBOT_WIDE_RETURN_ADMISSION_OUT:?New output directory required}"
[[ ! -e "$out" ]];mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
for job in "$old/run" "$cohort/run";do
    while [[ ! -f "$job.exit" ]];do [[ -f "$job.pid" ]] && kill -0 "$(< "$job.pid")" || { echo "$job ended without a status." >&2;exit 1; };sleep 20;done
    [[ "$(< "$job.exit")" == 0 ]] || { echo "$job failed; no histories admitted." >&2;exit 1; }
done
old_data="$old/expanded/data.bin";old_sha="$(sha256sum "$old_data" | cut -d' ' -f1)"
jq -e --arg sha "$old_sha" '.passed and .episodes==350 and .fittingHistories==238 and .validationHistories==112 and .dataSHA256==$sha and .newHistoriesIndependentlyAudited and .existingDataBytePreserved and .existingTargetsBytePreserved and .actorInputsUnchanged' "$old/coverage.json" > /dev/null
jq -e '.complete and .workers==2 and .successfulWorkers>=1 and .teacherAssisted and (.autonomousWholeEpisodeSuccessClaimed|not) and (.automaticMerge|not)' "$cohort/summary.json" > /dev/null
sha256sum -c "$cohort/inputs.sha256" > "$out/cohort-integrity.log"
sha256sum -c "$catalog/inputs.sha256" > "$out/catalog-integrity.log"
sha256sum -c "$catalog/prior-inputs.sha256" > "$out/prior-integrity.log"
sources=("$old_data" "$old/expanded");target_sources=("$old_data" "$old/targets");workers=();actions_fit=0;actions_validation=0
sha256sum "$bin"/* "$runtime/build/flex/control/control" "$runtime/build/flex/control/simulator" "$survey" "$prepare" "$merge_targets" "$old_data" "$old/targets/targets.bin" "$old/targets/receipt.json" "$old/coverage.json" "$cohort/summary.json" > "$out/inputs.sha256"
for worker in 0 1;do
    work="$cohort/worker-$worker"
    if ! jq -e '.passed and .teacherAssisted and .initialPhysicalPosesChecked and (.automaticMerge|not)' "$cohort/worker-$worker.json" > /dev/null;then continue;fi
    data="$work/packed/data.bin";sha="$(sha256sum "$data" | cut -d' ' -f1)"
    jq -e --arg sha "$sha" '.passed and .episodes==2 and .datasetEpisodes==2 and .dataSHA256==$sha and .studentPolicies256==2 and .studentRollinCommandsReplayed>=2 and .studentRollinMaxAbsError==0 and .denseOracleLabels and .datasetInputsMatchActualRGBAndOwnFeedback and .executedCommandsMatchRecordings and .taskEventHintAbsent' "$work/verified/result.json" > /dev/null
    for i in 0 1;do
        jq -e '.searchTeacher=="coverage-camera-v2" and .studentBeginsAfterConsumption and .studentStartAction>=1 and .studentActions>=1 and .studentActions<=60 and .teacherPlannerUsesPrivilegedGeometry and (.searchGoalsUseUnseenBrickPosition|not) and .denseOracleLabels' "$work/runs/expert-$i/supervision.json" > /dev/null
        jq -e '.passed and .brickPositionNotReadBySearchReconstruction and .oracleLabelsMatched and (.actorInputsChecked|not)' "$work/goal-audit-$i/result.json" > /dev/null
        sha256sum -c "$work/goal-audit-$i/inputs.sha256" > "$out/goal-$worker-$i-integrity.log"
        for file in case.json environment.bin;do cmp "$cohort/catalog/$worker/$i/$file" "$work/runs/expert-$i/scene/$file";done
    done
    sha256sum "$data" "$cohort/worker-$worker.json" "$work/verified/result.json" "$work"/goal-audit-{0,1}/result.json "$work"/runs/expert-{0,1}/supervision.json >> "$out/inputs.sha256"
    labels="$out/labels-$worker";mkdir "$labels"
    "$survey" "$data" "$work/runs" "$labels/survey.json" 2 "$sha" "$labels/candidates.jsonl" > "$labels/survey.log" 2>&1
    candidates="$(sha256sum "$labels/candidates.jsonl" | cut -d' ' -f1)"
    "$prepare" "$data" "$work/runs" "$labels/candidates.jsonl" "$labels/survey.json" "$sha" "$candidates" "$labels/targets" --allow-empty-splits > "$labels/prepare.log" 2>&1
    jq -e --arg sha "$sha" '.passed and .sourceDataSHA256==$sha and .allowEmptyCandidateSplits and .projectionAndPixelsIndependentlyRechecked and .actorInputsUnchanged' "$labels/targets/receipt.json" > /dev/null
    sources+=("$data" "$work/runs");target_sources+=("$data" "$labels/targets");workers+=("$worker")
    actions_fit=$((actions_fit+$(jq -r '.studentActions' "$work/runs/expert-0/supervision.json")))
    actions_validation=$((actions_validation+$(jq -r '.studentActions' "$work/runs/expert-1/supervision.json")))
done
count="${#workers[@]}";[[ "$count" -ge 1 && "$count" == "$(jq -r '.successfulWorkers' "$cohort/summary.json")" ]]
sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
"$bin/merge-dense-many" "$out/expanded" "${sources[@]}" > "$out/expanded.log"
"$merge_targets" "$out/expanded" "$out/targets" "${target_sources[@]}" > "$out/targets.log"
"$bin/data-preserve-added" "$old_data" "$out/expanded/data.bin" "$out/data-preserved.json"
"$bin/target-preserve-added" "$old/targets/targets.bin" "$out/targets/targets.bin" "$out/targets-preserved.json"
"$bin/preflight-expanded-targets" "$out/expanded/data.bin" "$out/targets" "$out/preflight.json"
total=$((350+2*count));fit=$((238+count));validation=$((112+count));validation_start=$((fit+112))
for report in "$out/data-preserved.json" "$out/targets-preserved.json";do jq -e --argjson n "$total" --argjson fit "$fit" '.passed and .existingHistoriesPreserved==350 and .expandedHistories==$n and .expandedFittingHistories==$fit' "$report" > /dev/null;done
jq -e --argjson n "$total" --argjson fit "$fit" --argjson val "$validation" '.passed and .episodes==$n and .fittingHistories==$fit and .validationHistories==$val and .actorInputsUnchanged' "$out/preflight.json" > /dev/null
expanded_sha="$(sha256sum "$out/expanded/data.bin" | cut -d' ' -f1)"
export PATH="$base/unseen-benchmark-v2/native-path:$PATH" XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1 PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
cd "$runtime"
./build/flex/control/control verify-data --run "$out/expanded" --data "$out/expanded/data.bin" --output "$out/audit-fit" --audit-start 238 --audit-count "$count" --large-model > "$out/audit-fit.log" 2>&1
./build/flex/control/control verify-data --run "$out/expanded" --data "$out/expanded/data.bin" --output "$out/audit-validation" --audit-start "$validation_start" --audit-count "$count" --large-model > "$out/audit-validation.log" 2>&1
for role in fit validation;do expected="$actions_fit";if [[ "$role" == validation ]];then expected="$actions_validation";fi
    jq -e --arg sha "$expanded_sha" --argjson n "$total" --argjson count "$count" --argjson expected "$expected" '.passed and .datasetEpisodes==$n and .episodes==$count and .dataSHA256==$sha and .studentPolicies256==$count and .studentRollinCommandsReplayed==$expected and .studentRollinMaxAbsError==0 and .denseOracleLabels and .taskEventHintAbsent' "$out/audit-$role/result.json" > /dev/null
done
sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
sha256sum -c "$catalog/inputs.sha256" > "$out/catalog-integrity-after.log"
sha256sum -c "$catalog/prior-inputs.sha256" > "$out/prior-integrity-after.log"
[[ "$(sha256sum "$out/expanded/data.bin" | cut -d' ' -f1)" == "$expanded_sha" ]]
jq -n --arg old "$old_sha" --arg sha "$expanded_sha" --argjson n "$total" --argjson fit "$fit" --argjson val "$validation" --argjson count "$count" --argjson actions "$((actions_fit+actions_validation))" '{passed:true,episodes:$n,fittingHistories:$fit,validationHistories:$val,addedReturnHistories:($count*2),studentReturnActionsReplayed:$actions,oldDataSHA256:$old,dataSHA256:$sha,existingDataBytePreserved:true,existingTargetsBytePreserved:true,newHistoriesIndependentlyAudited:true,teacherSearchGoalsReconstructed:true,teacherLabelsTrainingOnly:true,actorInputsUnchanged:true,teacherAssisted:true,autonomousWholeEpisodeSuccessClaimed:false,automaticPromotion:false}' > "$out/coverage.json"
echo 'Teacher-search and student-return histories were independently audited and merged.'
