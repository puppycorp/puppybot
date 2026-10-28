#!/usr/bin/env bash
set -euo pipefail

project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$project/build/flex/sim/expanded-rooms-v1"
original="$root/cohort-v1"
retry="$root/cohort-retry-v1"
timeout="$root/timeout-worker-repair-v1"
timeout_original="$root/timeout-retry-v1"
timeout_pilot1="$root/timeout-consumption-pilot-v1"
timeout_pilot3="$root/timeout-consumption-pilot-3-v1"
repair="$root/fitting-repair-v1"
pilot="$root/consumption-match-v1"
out="$root/admission-v3"
base="$project/build/flex/sim/late-search-v1/artifacts-v2/data172"
[[ -f "$original/run.exit" && ! -e "$out/finalize.exit" && ! -e "$out/merged202" ]]
trap 'status=$?; printf "%s\n" "$status" > "$out/finalize.exit"' EXIT
cd "$project"
/usr/bin/sha256sum -c "$out/recipe.sha256" > "$out/recipe-before.log"
/usr/bin/sha256sum -c "$original/inputs.sha256" > "$out/inputs-before.log"
[[ "$(/usr/bin/sha256sum "$base/data.bin" | /usr/bin/cut -d' ' -f1)" == 05032e0eb2a4a98a7f0146db66195792b2c22fe3bda3138039e9c721bc69b284 ]]
/usr/bin/jq -e '.fittingScenes==24 and .validationScenes==6 and (.records|length)==30 and all(.records[]; .layout!=10 and .layout!=11 and .fit==(.episode<4))' "$original/catalog/report.json" > /dev/null

declare -A seen
for index in {0..171};do
    hash="$(/usr/bin/sha256sum "$base/expert-$index/scene/case.json" | /usr/bin/cut -d' ' -f1)"
    seen["$hash"]=1
done
sources=()
for worker in {0..5};do
    source="$original"
    [[ -f "$original/worker-$worker.exit" ]]
    if [[ "$(< "$original/worker-$worker.exit")" != 0 ]];then
        [[ -f "$retry/worker-$worker.exit" ]]
        if [[ "$(< "$retry/worker-$worker.exit")" == 0 ]];then
            source="$retry"
            /usr/bin/sha256sum -c "$retry/recipe.sha256" > "$out/retry-recipe.log"
        elif (( worker==0 ));then
            source="$timeout"
            [[ -f "$timeout/run.exit" && "$(< "$timeout/run.exit")" == 0 ]]
            /usr/bin/sha256sum -c "$timeout/inputs.sha256" > "$out/timeout-inputs.log"
        elif (( worker==4 ));then
            source="$repair"
            [[ -f "$repair/run.exit" && "$(< "$repair/run.exit")" == 0 ]]
            /usr/bin/sha256sum -c "$repair/inputs.sha256" > "$out/repair-inputs.log"
        else
            echo "No audited source for worker $worker" >&2;exit 1
        fi
    fi
    sources+=("$source")
    sha="$(/usr/bin/sha256sum "$source/packed-$worker/data.bin" | /usr/bin/cut -d' ' -f1)"
    /usr/bin/jq -e --arg sha "$sha" '.passed and .episodes==5 and .datasetEpisodes==5 and .firstEpisode==0 and .dataSHA256==$sha and .commands==.supervisedSteps and .studentRollinCommandsReplayed>=1 and .studentRollinCommandsReplayed<=600 and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .executedCommandsMatchRecordings and .denseOracleLabels and .preActionAlignmentChecked and .zeroPaddingChecked and .taskEventHintAbsent' "$source/verified-$worker/result.json" > /dev/null
    shape="$(/usr/bin/od -An -v -tu8 -w24 -j8 -N24 "$source/packed-$worker/data.bin")"
    /usr/bin/jq -ne --arg shape "$shape" '$shape|split(" ")|map(select(length>0)|tonumber)|.[0]==5 and .[1]==4 and .[2]>=120 and .[2]<=354' > /dev/null
    student=0
    for episode in {0..4};do
        run="$source/runs/$worker/expert-$episode"
        scene="$original/catalog/$worker/$episode"
        teacher_scene="$scene"
        if [[ "$source" == "$timeout" ]];then
            teacher_scene="$timeout_original/catalog/$worker/$episode"
            if (( episode==1 ));then teacher_scene="$timeout_pilot1/catalog/0";fi
            if (( episode==3 ));then teacher_scene="$timeout_pilot3/catalog/0";fi
        fi
        if [[ "$source" == "$repair" && "$episode" == 2 ]];then teacher_scene="$pilot/catalog/0";fi
        /usr/bin/jq -e --argjson seed "$((9740000+worker*1000+episode))" '.success and .maximumBrickDistanceM==0.35 and .seed==$seed' "$run/result.json" > /dev/null
        /usr/bin/jq -e --arg scene "$teacher_scene" '.studentActions>=1 and .studentActions<=120 and .minimumRollinActions==120 and .scheduledRollinActions==120 and .studentStartAction==0 and .burninActions==0 and .denseOracleLabels and .teacherReturnViaHome and .teacherApproachSide==1 and .sourceScene==$scene and .studentWeightsSHA256=="c71a7588ad40b5e41cef15e6789f663844aa3711ca604fa89e4c10e5ba5f3560"' "$run/supervision.json" > /dev/null
        student=$((student+$(/usr/bin/jq '.studentActions' "$run/supervision.json")))
        for file in case.json environment.bin;do /usr/bin/cmp "$scene/$file" "$run/scene/$file";done
        hash="$(/usr/bin/sha256sum "$scene/case.json" | /usr/bin/cut -d' ' -f1)"
        /usr/bin/jq -e --argjson worker "$worker" --argjson episode "$episode" --arg hash "$hash" '[.records[]|select(.worker==$worker and .episode==$episode and .caseSHA256==$hash)]|length==1' "$original/catalog/report.json" > /dev/null
        [[ ! "${seen[$hash]+present}" ]]
        seen["$hash"]=1
    done
    /usr/bin/jq -e --argjson student "$student" '.studentRollinCommandsReplayed==$student' "$source/verified-$worker/result.json" > /dev/null
    /usr/bin/jq --argjson worker "$worker" --arg source "$source" '.+{worker:$worker,source:$source,studentCommands:.studentRollinCommandsReplayed}' "$source/verified-$worker/result.json" > "$out/source-$worker.json"
done
/usr/bin/jq -s '.' "$out/source-"{0,1,2,3,4,5}.json > "$out/workers.json"
[[ -x "$out/merge" ]]
current="${sources[0]}/packed-0";run="${sources[0]}/runs/0"
for worker in {1..5};do
    target="$out/new-$((5*(worker+1)))"
    "$out/merge" "$current/data.bin" "$run" "${sources[$worker]}/packed-$worker/data.bin" "${sources[$worker]}/runs/$worker" "$target"
    current="$target";run="$target"
done
"$out/merge" "$base/data.bin" "$base" "$current/data.bin" "$current" "$out/merged202"
/usr/bin/jq -e '.episodes==202 and .fitTrajectories==160 and .sequenceLength==354 and .preservesFitValidationSplits and (.records|length)==202 and all(.records[]; .fit==(.index<160)) and ([.records[0:136][]|select(.source==0 and .sourceIndex==.index)]|length)==136 and ([.records[136:160][]|select(.source==1 and .sourceIndex==(.index-136))]|length)==24 and ([.records[160:196][]|select(.source==0 and .sourceIndex==(.index-24))]|length)==36 and ([.records[196:202][]|select(.source==1 and .sourceIndex==(.index-172))]|length)==6' "$out/merged202/report.json" > /dev/null
"$original/runtime/build/flex/control/control" pack-data --data "$out/merged202/data.bin" --output "$out/repacked202" > "$out/repacked202.log" 2>&1
/usr/bin/cmp "$out/merged202/data.bin" "$out/repacked202/data.bin"
/usr/bin/sha256sum -c "$original/inputs.sha256" > "$out/inputs-after.log"
/usr/bin/sha256sum -c "$out/recipe.sha256" > "$out/recipe-after.log"
/usr/bin/jq -n --slurpfile merged "$out/merged202/report.json" --slurpfile workers "$out/workers.json" '{passed:true,episodes:202,fittingHistories:160,validationHistories:42,previousHistoriesRetained:172,newHistories:30,allNewTripsIndependentlyAudited:true,allNewScenesDistinctFromPreviousAndEachOther:true,reservedLayoutsExcluded:true,actorInputsUnchanged:true,teacherCompletionIsNotStudentSuccess:true,dataSHA256:$merged[0].dataSHA256,workers:$workers[0]}' > "$out/coverage.json"
mv "$out/merged202" "$out/data202"
printf '0\n' > "$out/dataset.exit"
echo '202 complete histories admitted: 160 fitting and 42 validation; autonomous success remains unproven.'
