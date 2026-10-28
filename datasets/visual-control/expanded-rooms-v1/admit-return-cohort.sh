#!/usr/bin/env bash
set -euo pipefail

project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$project/build/flex/sim/expanded-rooms-v1"
out="$root/return-admission-v1"
cohort="$root/return-cohort-v1"
pilot="$root/return-pilot-v1"
old="$root/contact-admission-v1/merged-6"
[[ ! -e "$out/run.exit" && ! -e "$out/merged-1" ]]
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
printf '%s\n' "$BASHPID" > "$out/run.pid"
while [[ ! -f "$cohort/run.exit" ]];do
    [[ -f "$cohort/run.pid" ]] && kill -0 "$(< "$cohort/run.pid")" || { echo 'Return collection disappeared without a terminal status.' >&2;exit 1; }
    /usr/bin/sleep 10
done
[[ "$(< "$cohort/run.exit")" == 0 && "$(< "$pilot/run.exit")" == 0 ]] || { echo 'Return collection did not pass; no histories admitted.' >&2;exit 1; }
cd "$project"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
/usr/bin/sha256sum -c "$cohort/inputs.sha256" > "$out/collection-integrity.log"
old_sha="$(/usr/bin/sha256sum "$old/data.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$old_sha" '.passed and .episodes==222 and .fittingHistories==174 and .validationHistories==48 and .dataSHA256==$sha and .existingDataBytePreserved' "$root/contact-admission-v1/coverage.json" > /dev/null
/usr/bin/jq -e '.passed and (.records|length)==12 and .reservedFinalLayoutsExcluded and .validationEnvironmentExcludedFromFitting' "$cohort/catalog/report.json" > /dev/null
student_sha="$(/usr/bin/sha256sum "$cohort/student/weights.bin" | /usr/bin/cut -d' ' -f1)"
declare -A seen heldout_env heldout_cases
for ((i=0;i<222;i++));do hash="$(/usr/bin/sha256sum "$old/expert-$i/scene/case.json" | /usr/bin/cut -d' ' -f1)";seen["$hash"]=1;done
for layout in 18 19;do
    scene_root="$root/development-scenes-v1/$layout"
    hash="$(/usr/bin/sha256sum "$scene_root/environment.bin" | /usr/bin/cut -d' ' -f1)";heldout_env["$hash"]=1
    for scene in {0..15};do hash="$(/usr/bin/sha256sum "$scene_root/$scene/case.json" | /usr/bin/cut -d' ' -f1)";heldout_cases["$hash"]=1;done
done
for layout in 20 21 22 23;do
    scene_root="$root/generalization-scenes-v1/$layout"
    hash="$(/usr/bin/sha256sum "$scene_root/environment.bin" | /usr/bin/cut -d' ' -f1)";heldout_env["$hash"]=1
    for scene in {0..15};do hash="$(/usr/bin/sha256sum "$scene_root/$scene/case.json" | /usr/bin/cut -d' ' -f1)";heldout_cases["$hash"]=1;done
done
data_sources=("$pilot/packed/data.bin")
run_sources=("$pilot/runs")
verify_sources=("$pilot/verified/result.json")
catalog_sources=("$pilot/catalog")
for worker in {0..5};do
    [[ "$(< "$cohort/worker-$worker.exit")" == 0 ]]
    data_sources+=("$cohort/packed-$worker/data.bin")
    run_sources+=("$cohort/runs/$worker")
    verify_sources+=("$cohort/verified-$worker/result.json")
    catalog_sources+=("$cohort/catalog/$worker")
done
for index in {0..6};do
    seed=$((9800000+(index-1)*1000));if (( index==0 ));then seed=9790000;fi
    sha="$(/usr/bin/sha256sum "${data_sources[$index]}" | /usr/bin/cut -d' ' -f1)"
    /usr/bin/jq -e --arg sha "$sha" '.passed and .episodes==2 and .datasetEpisodes==2 and .dataSHA256==$sha and .studentRollinCommandsReplayed>=2 and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .executedCommandsMatchRecordings and .denseOracleLabels and .preActionAlignmentChecked and .zeroPaddingChecked and .taskEventHintAbsent' "${verify_sources[$index]}" > /dev/null
    read -r count fit length < <(/usr/bin/od -An -tu8 -w24 -j8 -N24 "${data_sources[$index]}")
    [[ "$count" == 2 && "$fit" == 1 && "$length" -ge 90 && "$length" -le 354 ]]
    student=0
    for episode in 0 1;do
        run="${run_sources[$index]}/expert-$episode";scene="${catalog_sources[$index]}/$episode"
        /usr/bin/jq -e --argjson seed "$((seed+episode))" '.success and .maximumBrickDistanceM==0.35 and .seed==$seed' "$run/result.json" > /dev/null
        /usr/bin/jq -e --arg sha "$student_sha" '.studentWeightsSHA256==$sha and .denseOracleLabels and .studentBeginsAfterConsumption and .studentStartAction>0 and .scheduledRollinActions==90 and .studentActions>=1 and .studentActions<=90' "$run/supervision.json" > /dev/null
        student=$((student+$(/usr/bin/jq '.studentActions' "$run/supervision.json")))
        for file in case.json environment.bin;do /usr/bin/cmp "$scene/$file" "$run/scene/$file";done
        hash="$(/usr/bin/sha256sum "$scene/case.json" | /usr/bin/cut -d' ' -f1)"
        env="$(/usr/bin/sha256sum "$scene/environment.bin" | /usr/bin/cut -d' ' -f1)"
        [[ ! "${seen[$hash]+yes}" && ! "${heldout_cases[$hash]+yes}" && ! "${heldout_env[$env]+yes}" ]]
        seen["$hash"]=1
    done
    /usr/bin/jq -e --argjson student "$student" '.studentRollinCommandsReplayed==$student' "${verify_sources[$index]}" > /dev/null
done
current_data="$old/data.bin";current_runs="$old"
for index in {0..6};do
    target="$out/merged-$((index+1))"
    "$out/merge" "$current_data" "$current_runs" "${data_sources[$index]}" "${run_sources[$index]}" "$target" > "$out/merge-$index.log" 2>&1
    current_data="$target/data.bin";current_runs="$target"
done
/usr/bin/jq -e '.episodes==236 and .fitTrajectories==181 and .sequenceLength==354 and .preservesFitValidationSplits and (.records|length)==236 and all(.records[];.fit==(.index<181))' "$current_runs/report.json" > /dev/null
"$out/preserve" "$old/data.bin" "$current_data" "$out/preserved.json" > "$out/preserve.log" 2>&1
new_sha="$(/usr/bin/sha256sum "$current_data" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg old "$old_sha" --arg new "$new_sha" '.passed and .existingHistoriesPreserved==222 and .expandedHistories==236 and .fittingHistories==174 and .expandedFittingHistories==181 and .oldDataSHA256==$old and .expandedDataSHA256==$new' "$out/preserved.json" > /dev/null
"$cohort/runtime/build/flex/control/control" pack-data --data "$current_data" --output "$out/repacked" > "$out/repacked.log" 2>&1
/usr/bin/cmp "$current_data" "$out/repacked/data.bin"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
/usr/bin/sha256sum -c "$cohort/inputs.sha256" > "$out/collection-integrity-after.log"
/usr/bin/jq -n --arg sha "$new_sha" --arg old "$old_sha" '{passed:true,episodes:236,fittingHistories:181,validationHistories:55,previousHistoriesRetained:222,newReturnHistories:14,dataSHA256:$sha,oldDataSHA256:$old,allNewTripsIndependentlyAudited:true,existingDataBytePreserved:true,actorInputsUnchanged:true,teacherCompletionIsNotStudentSuccess:true,targetLabelsNotYetPrepared:true}' > "$out/coverage.json"
echo 'Fourteen audited return histories admitted with the existing corpus preserved; target-label preparation and training remain separate.'
