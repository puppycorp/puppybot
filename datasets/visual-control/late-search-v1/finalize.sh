#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
dataset="${PUPPYBOT_RECIPES:-$project/datasets/visual-control/late-search-v1}"
root="$project/build/flex/sim/late-search-v1"
out="${PUPPYBOT_ARTIFACTS:-$root/artifacts}"
base="$project/build/flex/sim/forward-contact-v2/artifacts"
[[ "$(< "$out/collection.exit")" == 0 && ! -e "$out/data172" && ! -e "$out/finalize.exit" ]]
/usr/bin/jq -e '.passed and .fittingLaterDisagreements>=300 and .fittingHistoriesWith20LaterDisagreements>=8' "$out/state-coverage.json" > /dev/null
trap 'status=$?; printf "%s\n" "$status" > "$out/finalize.exit"' EXIT
cd "$project"
[[ "$(/usr/bin/sha256sum "$base/data142/data.bin" | /usr/bin/cut -d' ' -f1)" == 852a80123d19dc45e6ec78587c5ea19c30388d9381c7d634faebb22501f349f9 ]]
build/flex/control/compiler datasets/visual-control/approach35-v1/merge.flex -o "$out/merge"
original_sha="$(/usr/bin/sha256sum "$root/artifacts/packed-2/data.bin" | /usr/bin/cut -d' ' -f1)"
repair_sha="$(/usr/bin/sha256sum "$out/repair-packed/data.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$original_sha" '.passed and .episodes==4 and .datasetEpisodes==5 and .firstEpisode==0 and .dataSHA256==$sha and .studentRollinCommandsReplayed==480 and .studentRollinMaxAbsError==0' "$out/verified-original-fitting-2/result.json" > /dev/null
/usr/bin/jq -e --arg sha "$repair_sha" '.passed and .episodes==2 and .datasetEpisodes==2 and .firstEpisode==0 and .dataSHA256==$sha and .studentRollinCommandsReplayed==240 and .studentRollinMaxAbsError==0' "$out/repair-verified/result.json" > /dev/null
/usr/bin/jq -e --arg original "$original_sha" --arg repair "$repair_sha" '.preservesFittingHistoriesAndRoles and .replacesOnlyValidationIndex==4 and .sourceSHA256==[$original,$repair] and (.records|map(.index))==[0,1,2,3,4] and (.records|map(.source))==[0,0,0,0,1] and (.records|map(.sourceIndex))==[0,1,2,3,1] and (.records|map(.fit))==[true,true,true,true,false]' "$out/runs/2/report.json" > /dev/null
for worker in {0..5}; do
    [[ "$(< "$out/worker-$worker.exit")" == 0 ]]
    sha="$(/usr/bin/sha256sum "$out/packed-$worker/data.bin" | /usr/bin/cut -d' ' -f1)"
    /usr/bin/jq -e --arg sha "$sha" '.passed and .episodes==5 and .datasetEpisodes==5 and .firstEpisode==0 and .dataSHA256==$sha and .commands==.supervisedSteps and .studentRollinCommandsReplayed>=1 and .studentRollinCommandsReplayed<=600 and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .executedCommandsMatchRecordings and .denseOracleLabels and .preActionAlignmentChecked and .zeroPaddingChecked and .taskEventHintAbsent' "$out/verified-$worker/result.json" > /dev/null
    /usr/bin/jq -e --arg sha "$sha" '.dataSHA256==$sha and (.windows|length)==10 and (.windows|all(.fit==(.episode<4) and (.firstAction==0 or .firstAction==60)))' "$out/diagnostic-$worker.json" > /dev/null
    shape="$(/usr/bin/od -An -v -tu8 -w24 -j8 -N24 "$out/packed-$worker/data.bin")"
    /usr/bin/jq -ne --arg shape "$shape" '$shape|split(" ")|map(select(length>0)|tonumber)|.[0]==5 and .[1]==4 and .[2]>=120 and .[2]<=512' > /dev/null
    student=0
    for episode in {0..4}; do
        run="$out/runs/$worker/expert-$episode"
        /usr/bin/jq -e --argjson seed "$((9620000+worker*1000+episode))" '.success and .maximumBrickDistanceM==0.35 and .seed==$seed' "$run/result.json" > /dev/null
        side=1;source="$root/catalogs-v2/$worker/$episode"
        if (( worker==2 && episode==4 ));then side=0;source="$root/repair-catalog/1";fi
        /usr/bin/jq -e --argjson side "$side" --arg source "$source" '.studentActions>=1 and .studentActions<=120 and .scheduledRollinActions==120 and .studentStartAction==0 and .burninActions==0 and .denseOracleLabels and .teacherReturnViaHome and .teacherApproachSide==$side and .sourceScene==$source and .studentWeightsSHA256=="c38fa6cbc57c7a1da996f2c50fa3b2deb251c71c073698ce1269a3e833183ab7"' "$run/supervision.json" > /dev/null
        count="$(/usr/bin/jq '.studentActions' "$run/supervision.json")";student=$((student+count))
        for file in case.json environment.bin; do /usr/bin/cmp "$root/catalogs-v2/$worker/$episode/$file" "$run/scene/$file";done
    done
    /usr/bin/jq -e --argjson student "$student" '.studentRollinCommandsReplayed==$student' "$out/verified-$worker/result.json" > /dev/null
    /usr/bin/jq --argjson worker "$worker" '.+{worker:$worker,fitTrajectories:4,auditedEpisodes:.episodes,physicalCompletions:5,studentCommands:.studentRollinCommandsReplayed}' "$out/verified-$worker/result.json" > "$out/source-$worker.json"
done
/usr/bin/jq -s '.' "$out/source-"{0,1,2,3,4,5}.json > "$out/workers.json"
current="$out/packed-0";run="$out/runs/0"
for worker in {1..5}; do
    target="$out/new-$((5*(worker+1)))"
    "$out/merge" "$current/data.bin" "$run" "$out/packed-$worker/data.bin" "$out/runs/$worker" "$target"
    current="$target";run="$target"
done
/usr/bin/jq -s '.' "$out/new-"{10,15,20,25,30}/report.json > "$out/merges.json"
"$out/merge" "$base/data142/data.bin" "$base/data142" "$current/data.bin" "$current" "$out/merged172"
"$out/runtime/build/flex/control/control" pack-data --data "$out/merged172/data.bin" --output "$out/repacked172" > "$out/repacked172.log" 2>&1
/usr/bin/cmp "$out/merged172/data.bin" "$out/repacked172/data.bin"
coverage() {
    /usr/bin/jq -n --slurpfile workers "$1" --slurpfile final "$2" --slurpfile catalog "$root/catalogs-v2/report.json" --slurpfile state "$out/state-coverage.json" --slurpfile old "$base/coverage.json" --slurpfile merges "$out/merges.json" -f "$dataset/coverage.jq"
}
mkdir "$out/coverage-guards"
/usr/bin/jq '.[0].dataSHA256="wrong"' "$out/workers.json" > "$out/coverage-guards/wrong-source.json"
coverage "$out/coverage-guards/wrong-source.json" "$out/merged172/report.json" > "$out/coverage-guards/wrong-source-result.json"
/usr/bin/jq -e '.passed|not' "$out/coverage-guards/wrong-source-result.json" > /dev/null
/usr/bin/jq '.records[0].fit=false' "$out/merged172/report.json" > "$out/coverage-guards/wrong-role.json"
coverage "$out/workers.json" "$out/coverage-guards/wrong-role.json" > "$out/coverage-guards/wrong-role-result.json"
/usr/bin/jq -e '.passed|not' "$out/coverage-guards/wrong-role-result.json" > /dev/null
coverage "$out/workers.json" "$out/merged172/report.json" > "$out/coverage.json"
/usr/bin/jq -e '.passed' "$out/coverage.json" > /dev/null
for manifest in runtime catalogs robot-asset recipes; do /usr/bin/sha256sum -c "$out/$manifest.sha256" > "$out/$manifest-final.log";done
mkdir "$out/finalizer-used"
cp "$dataset/"{finalize.sh,coverage.jq} "$out/finalizer-used/"
/usr/bin/sha256sum "$out/finalizer-used/"* "$out/merge" > "$out/finalizer.sha256"
mv "$out/merged172" "$out/data172"
printf '0\n' > "$out/dataset.exit"
echo '172 complete histories admitted:136 fitting/36 validation, all previous142 retained.'
