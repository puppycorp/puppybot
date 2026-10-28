#!/usr/bin/env bash
# Recheck admission receipts and the exact dataset used by both replay audits.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
root="$project/build/flex/sim/expanded-rooms-v1/large-model-v1"
admission="${PUPPYBOT_GATED_SEARCH_COHORT_ADMISSION:-$root/gated-search-cohort-admission-v1}"
cohort="$root/gated-search-cohort-v1"
old="$root/gated-search-admission-v1"
out="${PUPPYBOT_COHORT_AUDIT_OUT:?New output directory required}"
[[ ! -e "$out" ]]
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
for job in "$cohort/run" "$admission/run";do
    while [[ ! -f "$job.exit" ]];do [[ -f "$job.pid" ]] && kill -0 "$(< "$job.pid")" || { echo "$job ended without a status." >&2;exit 1; }; /usr/bin/sleep 20;done
    [[ "$(< "$job.exit")" == 0 ]] || { echo "$job failed; audit not published." >&2;exit 1; }
done
workers="$(/usr/bin/jq -r '.successfulWorkers' "$cohort/summary.json")"
[[ "$workers" =~ ^[1-4]$ ]]
total=$((282+2*workers));fit=$((204+workers));validation=$((78+workers));validation_start=$((fit+78))
data="$admission/expanded/data.bin";sha="$(/usr/bin/sha256sum "$data" | /usr/bin/cut -d' ' -f1)"
old_sha="$(/usr/bin/sha256sum "$old/expanded/data.bin" | /usr/bin/cut -d' ' -f1)"
target_sha="$(/usr/bin/sha256sum "$admission/targets/targets.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$sha" --arg old "$old_sha" --argjson n "$total" --argjson fit "$fit" --argjson val "$validation" --argjson added "$((2*workers))" '.passed and .episodes==$n and .fittingHistories==$fit and .validationHistories==$val and .addedSearchHistories==$added and .dataSHA256==$sha and .oldDataSHA256==$old and .existingDataBytePreserved and .existingTargetsBytePreserved and .newHistoriesIndependentlyAudited and .teacherLabelsTrainingOnly and .actorInputsUnchanged and (.studentAutonomousSuccessClaimed|not) and (.automaticPromotion|not)' "$admission/coverage.json" > /dev/null
/usr/bin/jq -e --arg data "$sha" --arg target "$target_sha" --argjson n "$total" --argjson fit "$fit" --argjson val "$validation" '.passed and .episodes==$n and .fittingHistories==$fit and .validationHistories==$val and .sourceDataSHA256==$data and .targetsSHA256==$target and .actorInputsUnchanged' "$admission/targets/receipt.json" > /dev/null
for report in "$admission/data-preserved.json" "$admission/targets-preserved.json";do /usr/bin/jq -e --argjson n "$total" --argjson fit "$fit" '.passed and .existingHistoriesPreserved==282 and .expandedHistories==$n and .expandedFittingHistories==$fit' "$report" > /dev/null;done
fit_actions=0;validation_actions=0
for ((worker=0;worker<4;worker++));do
    record="$cohort/worker-$worker.json"
    if ! /usr/bin/jq -e '.passed' "$record" > /dev/null;then continue;fi
    work="$cohort/worker-$worker"
    a="$(/usr/bin/jq -r '.studentActions' "$work/runs/expert-0/supervision.json")";b="$(/usr/bin/jq -r '.studentActions' "$work/runs/expert-1/supervision.json")"
    [[ "$a" =~ ^[0-9]+$ && "$b" =~ ^[0-9]+$ ]];(( a>=1 && a<=120 && b>=1 && b<=120 ));fit_actions=$((fit_actions+a));validation_actions=$((validation_actions+b))
    data_sha="$(/usr/bin/sha256sum "$work/packed/data.bin" | /usr/bin/cut -d' ' -f1)"
    /usr/bin/jq -e --arg sha "$data_sha" --argjson total "$((a+b))" '.passed and .dataSHA256==$sha and .studentActions==$total and .oracleTrainingOnly and .actorInputsUnchanged and .offlineAnalysisOnly' "$admission/labels-$worker/interventions.json" > /dev/null
done
for role in fit validation;do
    start=204;expected="$fit_actions";if [[ "$role" == validation ]];then start="$validation_start";expected="$validation_actions";fi
    /usr/bin/jq -e --arg sha "$sha" --argjson all "$total" --argjson n "$workers" --argjson start "$start" --argjson expected "$expected" '.passed and .datasetEpisodes==$all and .episodes==$n and .firstEpisode==$start and .dataSHA256==$sha and .studentPolicies256==$n and .studentRollinCommandsReplayed==$expected and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .executedCommandsMatchRecordings and .preActionAlignmentChecked and .zeroPaddingChecked and .denseOracleLabels and .taskEventHintAbsent' "$admission/audit-$role/result.json" > /dev/null
done
/usr/bin/jq -e --argjson actions "$((fit_actions+validation_actions))" '.studentRollinActionsReplayed==$actions' "$admission/coverage.json" > /dev/null
/usr/bin/sha256sum "$data" "$old/expanded/data.bin" "$admission/targets/targets.bin" "$admission/targets/receipt.json" "$admission/coverage.json" "$admission/audit-fit/result.json" "$admission/audit-validation/result.json" "$cohort/summary.json" > "$out/inputs.sha256"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
/usr/bin/jq -n --arg sha "$sha" --argjson n "$total" --argjson fit "$fit" --argjson val "$validation" --argjson actions "$((fit_actions+validation_actions))" '{passed:true,dataSHA256:$sha,episodes:$n,fittingHistories:$fit,validationHistories:$val,studentRollinActionsReplayed:$actions,bothReplayReceiptsMatchDataset:true,actorInputsUnchanged:true,studentAutonomousSuccessClaimed:false}' > "$out/result.json"
echo 'Both replay audits match the admitted corpus and its preserved targets.'
