#!/usr/bin/env bash
# Add independently replayed student roll-ins, preserving the existing split.
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
old="$root/gated-search-admission-v1"
cohort="$root/gated-search-cohort-v1"
bin="$root/source/admission-cohort-v3/bin"
runtime="$root/phase-large-tests-v1/runtime"
survey="$base/return-labels-v1/survey"
prepare="$base/return-labels-v1/prepare"
summarize="${PUPPYBOT_SEARCH_SUMMARIZER:?Frozen search summarizer required}"
out="${PUPPYBOT_SEARCH_COHORT_ADMISSION_OUT:?New output directory required}"
[[ ! -e "$out" ]]
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
for job in "$old/run" "$cohort/run";do
    while [[ ! -f "$job.exit" ]];do [[ -f "$job.pid" ]] && kill -0 "$(< "$job.pid")" || { echo "$job ended without a status." >&2;exit 1; }; /usr/bin/sleep 20;done
    [[ "$(< "$job.exit")" == 0 ]] || { echo "$job failed; no histories admitted." >&2;exit 1; }
done
/usr/bin/jq -e '.complete and .attemptedWorkers==4 and .successfulWorkers>=1 and .successfulWorkers<=4 and .auditedHistories==(.successfulWorkers*2) and .failedWorkers==(4-.successfulWorkers) and .partialArtifactsRetained and (.automaticMerge|not) and (.studentAutonomousSuccessClaimed|not)' "$cohort/summary.json" > /dev/null
old_data="$old/expanded/data.bin"
old_sha="$(/usr/bin/sha256sum "$old_data" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$old_sha" '.passed and .episodes==282 and .fittingHistories==204 and .validationHistories==78 and .dataSHA256==$sha and .existingDataBytePreserved and .existingTargetsBytePreserved and .newHistoriesIndependentlyAudited and .teacherLabelsTrainingOnly and .actorInputsUnchanged' "$old/coverage.json" > /dev/null
/usr/bin/sha256sum -c "$cohort/inputs.sha256" > "$out/cohort-integrity.log"
/usr/bin/sha256sum -c "$cohort/prior-inputs.sha256" > "$out/prior-integrity.log"
for ((index=0;index<282;index++));do
    for file in case.json environment.bin;do /usr/bin/sha256sum "$old/expanded/expert-$index/scene/$file" | /usr/bin/cut -d' ' -f1;done
done > "$out/prior-hashes.txt"
for layout in 18 19 20 21 22 23;do
    parent=generalization-benchmark-v1; if (( layout<20 ));then parent=unseen-benchmark-v2;fi
    for scene in {0..15};do for file in case.json environment.bin;do /usr/bin/sha256sum "$base/$parent/scenes/$layout/$scene/$file" | /usr/bin/cut -d' ' -f1;done;done
done >> "$out/prior-hashes.txt"
/usr/bin/sha256sum "$bin"/* "$runtime/build/flex/control/control" "$runtime/build/flex/control/simulator" "$survey" "$prepare" "$summarize" "$old_data" "$old/targets/targets.bin" "$old/targets/receipt.json" "$old/coverage.json" "$cohort/summary.json" > "$out/inputs.sha256"
new_data_args=();fit_actions=0;validation_actions=0;workers=0
for ((worker=0;worker<4;worker++));do
    record="$cohort/worker-$worker.json"
    if ! /usr/bin/jq -e '.passed' "$record" > /dev/null;then continue;fi
    work="$cohort/worker-$worker";data="$work/packed/data.bin";labels="$out/labels-$worker"
    sha="$(/usr/bin/sha256sum "$data" | /usr/bin/cut -d' ' -f1)";student="$(/usr/bin/jq -r '.studentCommandsReplayed' "$record")"
    /usr/bin/jq -e --arg sha "$sha" --argjson student "$student" '.passed and .episodes==2 and .studentCommandsReplayed==$student and .dataSHA256==$sha and .teacherAssisted and (.studentAutonomousSuccessClaimed|not)' "$record" > /dev/null
    /usr/bin/jq -e --arg sha "$sha" --argjson student "$student" '.passed and .episodes==2 and .studentPolicies256==2 and .studentRollinCommandsReplayed==$student and .studentRollinMaxAbsError==0 and .denseOracleLabels and .taskEventHintAbsent and .dataSHA256==$sha' "$work/verified/result.json" > /dev/null
    for episode in 0 1;do
        scene="$cohort/catalog/$worker/$episode";run="$work/runs/expert-$episode";layout=$((50+worker));role=true
        if (( episode ));then layout=$((150+worker));role=false;fi
        /usr/bin/jq -e --argjson layout "$layout" --argjson role "$role" '.layoutId==$layout and .fit==$role' "$scene/layout.json" > /dev/null
        for file in case.json environment.bin;do
            /usr/bin/cmp "$scene/$file" "$run/scene/$file"
            digest="$(/usr/bin/sha256sum "$scene/$file" | /usr/bin/cut -d' ' -f1)"
            reject_known_hash "$digest" "$out/prior-hashes.txt"
            printf '%s\n' "$digest" >> "$out/prior-hashes.txt"
            /usr/bin/sha256sum "$scene/$file" >> "$out/inputs.sha256"
        done
    done
    a="$(/usr/bin/jq -r '.studentActions' "$work/runs/expert-0/supervision.json")";b="$(/usr/bin/jq -r '.studentActions' "$work/runs/expert-1/supervision.json")"
    (( a>=1 && a<=120 && b>=1 && b<=120 && a+b==student ));fit_actions=$((fit_actions+a));validation_actions=$((validation_actions+b));workers=$((workers+1))
    /usr/bin/sha256sum "$data" "$work/verified/result.json" "$record" >> "$out/inputs.sha256"
    mkdir "$labels"
    "$summarize" "$data" "$work/runs" "$work/verified/result.json" > "$labels/interventions.json"
    /usr/bin/jq -e --argjson student "$student" '.passed and .studentActions==$student and .oracleTrainingOnly and .actorInputsUnchanged and .offlineAnalysisOnly' "$labels/interventions.json" > /dev/null
    new_data_args+=("$data" "$work/runs")
done
(( workers>=1 && workers<=4 ))
/usr/bin/jq -e --argjson workers "$workers" --argjson total "$((fit_actions+validation_actions))" '.successfulWorkers==$workers and .studentCommandsReplayed==$total' "$cohort/summary.json" > /dev/null
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
if (( workers==1 ));then
    mkdir "$out/new"
    ln -s "${new_data_args[0]}" "$out/new/data.bin"
    for episode in 0 1;do ln -s "${new_data_args[1]}/expert-$episode" "$out/new/expert-$episode";done
else
    "$bin/merge-dense-many" "$out/new" "${new_data_args[@]}" > "$out/new.log"
fi
new_data="$out/new/data.bin";new_sha="$(/usr/bin/sha256sum "$new_data" | /usr/bin/cut -d' ' -f1)"
mkdir "$out/new-labels"
"$survey" "$new_data" "$out/new" "$out/new-labels/survey.json" "$((workers*2))" "$new_sha" "$out/new-labels/candidates.jsonl" > "$out/new-labels/survey.log" 2>&1
candidates="$(/usr/bin/sha256sum "$out/new-labels/candidates.jsonl" | /usr/bin/cut -d' ' -f1)"
"$prepare" "$new_data" "$out/new" "$out/new-labels/candidates.jsonl" "$out/new-labels/survey.json" "$new_sha" "$candidates" "$out/new-labels/targets" > "$out/new-labels/prepare.log" 2>&1
"$bin/merge-dense-many" "$out/expanded" "$old_data" "$old/expanded" "$new_data" "$out/new" > "$out/expanded.log"
"$bin/merge-targets-many" "$out/expanded" "$out/targets" "$old_data" "$old/targets" "$new_data" "$out/new-labels/targets" > "$out/targets.log"
"$bin/data-preserve-added" "$old_data" "$out/expanded/data.bin" "$out/data-preserved.json"
"$bin/target-preserve-added" "$old/targets/targets.bin" "$out/targets/targets.bin" "$out/targets-preserved.json"
"$bin/preflight-expanded-targets" "$out/expanded/data.bin" "$out/targets" "$out/preflight.json"
total=$((282+workers*2));fit=$((204+workers));validation=$((78+workers));validation_start=$((fit+78))
for report in "$out/data-preserved.json" "$out/targets-preserved.json";do /usr/bin/jq -e --argjson n "$total" --argjson fit "$fit" '.passed and .existingHistoriesPreserved==282 and .expandedHistories==$n and .expandedFittingHistories==$fit' "$report" > /dev/null;done
/usr/bin/jq -e --argjson n "$total" --argjson fit "$fit" --argjson val "$validation" '.passed and .episodes==$n and .fittingHistories==$fit and .validationHistories==$val and .actorInputsUnchanged' "$out/preflight.json" > /dev/null
new_sha="$(/usr/bin/sha256sum "$out/expanded/data.bin" | /usr/bin/cut -d' ' -f1)"
export PATH="$base/unseen-benchmark-v2/native-path:$PATH" XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1 PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
cd "$runtime"
./build/flex/control/control verify-data --run "$out/expanded" --data "$out/expanded/data.bin" --output "$out/audit-fit" --audit-start 204 --audit-count "$workers" > "$out/audit-fit.log" 2>&1
./build/flex/control/control verify-data --run "$out/expanded" --data "$out/expanded/data.bin" --output "$out/audit-validation" --audit-start "$validation_start" --audit-count "$workers" > "$out/audit-validation.log" 2>&1
for role in fit validation;do expected="$fit_actions";if [[ "$role" == validation ]];then expected="$validation_actions";fi
    /usr/bin/jq -e --argjson n "$workers" --argjson total "$total" --argjson expected "$expected" --arg sha "$new_sha" '.passed and .episodes==$n and .datasetEpisodes==$total and .dataSHA256==$sha and .studentPolicies256==$n and .studentRollinCommandsReplayed==$expected and .studentRollinMaxAbsError==0 and .taskEventHintAbsent and .denseOracleLabels' "$out/audit-$role/result.json" > /dev/null
done
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
[[ "$(/usr/bin/sha256sum "$out/expanded/data.bin" | /usr/bin/cut -d' ' -f1)" == "$new_sha" ]]
/usr/bin/jq -n --arg old "$old_sha" --arg sha "$new_sha" --argjson n "$total" --argjson fit "$fit" --argjson val "$validation" --argjson added "$((workers*2))" --argjson actions "$((fit_actions+validation_actions))" '{passed:true,episodes:$n,fittingHistories:$fit,validationHistories:$val,addedSearchHistories:$added,studentRollinActionsReplayed:$actions,oldDataSHA256:$old,dataSHA256:$sha,existingDataBytePreserved:true,existingTargetsBytePreserved:true,newHistoriesIndependentlyAudited:true,teacherLabelsTrainingOnly:true,actorInputsUnchanged:true,studentAutonomousSuccessClaimed:false,automaticPromotion:false}' > "$out/coverage.json"
echo 'Successful search roll-ins were added and independently re-audited; no policy was promoted.'
