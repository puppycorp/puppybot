#!/usr/bin/env bash
set -euo pipefail
project="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
dataset="$project/datasets/visual-control/forward-contact-v2"
root="$project/build/flex/sim/forward-contact-v2"
out="$root/artifacts"
base="$project/build/flex/sim/start-pose-v1/artifacts"
[[ "$(< "$out/collection.exit")" == 0 && ! -e "$out/data142" && ! -e "$out/finalize.exit" ]]
/usr/bin/jq -e '.passed and .newFittingForwardContactFrames>=200' "$out/state-coverage.json" > /dev/null
trap 'status=$?; printf "%s\n" "$status" > "$out/finalize.exit"' EXIT
cd "$project"
[[ "$(/usr/bin/sha256sum "$base/data132/data.bin" | /usr/bin/cut -d' ' -f1)" == d709d3378a1241c34ec885e1cce131dfa9cc5984208032a031ed315a4ba70eff ]]
build/flex/control/compiler datasets/visual-control/approach35-v1/merge.flex -o "$out/merge"
for worker in 0 1; do
    [[ "$(< "$out/worker-$worker.exit")" == 0 ]]
    window=60;if (( worker==1 ));then window=8;fi
    sha="$(/usr/bin/sha256sum "$out/packed-$worker/data.bin" | /usr/bin/cut -d' ' -f1)"
    /usr/bin/jq -e --arg sha "$sha" --argjson count "$((window*5))" '.passed and .episodes==5 and .datasetEpisodes==5 and .firstEpisode==0 and .dataSHA256==$sha and .commands==.supervisedSteps and .studentRollinCommandsReplayed==$count and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .executedCommandsMatchRecordings and .denseOracleLabels and .preActionAlignmentChecked and .zeroPaddingChecked and .taskEventHintAbsent' "$out/verified-$worker/result.json" > /dev/null
    /usr/bin/jq -e --arg sha "$sha" --argjson count "$((window*5))" '.dataSHA256==$sha and .studentCommands==$count and .episodes==5 and .fittingHistories==4' "$out/states-$worker.json" > /dev/null
    shape="$(/usr/bin/od -An -v -tu8 -w24 -j8 -N24 "$out/packed-$worker/data.bin")"
    /usr/bin/jq -ne --arg shape "$shape" '$shape|split(" ")|map(select(length>0)|tonumber)|.[0]==5 and .[1]==4 and .[2]>=1 and .[2]<=354' > /dev/null
    contacts=0
    for episode in {0..4}; do
        run="$out/runs/$worker/expert-$episode"
        /usr/bin/jq -e '.success and .maximumBrickDistanceM==0.35' "$run/result.json" > /dev/null
        /usr/bin/jq -e --argjson window "$window" --arg source "$root/catalogs/$worker/$episode" '.studentActions==$window and .scheduledRollinActions==$window and .studentStartAction==0 and .burninActions==0 and .denseOracleLabels and .teacherApproachSide==1 and .sourceScene==$source and .studentWeightsSHA256=="c03fb6c357fd427e648d3d5fa7068c95f980a2a60f2f71a5b23c0b20e1c50934"' "$run/supervision.json" > /dev/null
        /usr/bin/cmp "$root/catalogs/$worker/$episode/case.json" "$run/scene/case.json"
        /usr/bin/cmp "$root/catalogs/$worker/$episode/environment.bin" "$run/scene/environment.bin"
        if (( episode<4 )); then
            counted="$(/usr/bin/jq -s --argjson window "$window" '[.[0:($window-1)][]|select(.proprio[5]==1 and .proprio[1]>0 and .state.findReturn.consumedIndex<0)]|length' "$run/decisions.jsonl")"
            contacts=$((contacts+counted))
        fi
    done
    /usr/bin/jq -e --argjson contacts "$contacts" '.fittingForwardContactFrames==$contacts' "$out/states-$worker.json" > /dev/null
    /usr/bin/jq --argjson worker "$worker" --argjson window "$window" --slurpfile state "$out/states-$worker.json" '.+{worker:$worker,episodes:5,fitTrajectories:4,auditedEpisodes:.episodes,physicalCompletions:5,window:$window,studentCommands:.studentRollinCommandsReplayed,fittingForwardContactFrames:$state[0].fittingForwardContactFrames}' "$out/verified-$worker/result.json" > "$out/source-$worker.json"
done
/usr/bin/jq -s '.' "$out/"source-{0,1}.json > "$out/workers.json"
"$out/merge" "$out/packed-0/data.bin" "$out/runs/0" "$out/packed-1/data.bin" "$out/runs/1" "$out/new10"
"$out/merge" "$base/data132/data.bin" "$base/data132" "$out/new10/data.bin" "$out/new10" "$out/merged142"
"$out/runtime/build/flex/control/control" pack-data --data "$out/merged142/data.bin" --output "$out/repacked142" > "$out/repacked142.log" 2>&1
/usr/bin/cmp "$out/merged142/data.bin" "$out/repacked142/data.bin"
coverage() {
    /usr/bin/jq -n --slurpfile workers "$1" --slurpfile final "$2" --slurpfile catalog "$root/catalogs/report.json" --slurpfile state "$out/state-coverage.json" --slurpfile old "$base/coverage.json" --slurpfile new "$out/new10/report.json" -f "$dataset/coverage.jq"
}
mkdir "$out/coverage-guards"
/usr/bin/jq '.[0].dataSHA256="wrong"' "$out/workers.json" > "$out/coverage-guards/wrong-source.json"
coverage "$out/coverage-guards/wrong-source.json" "$out/merged142/report.json" > "$out/coverage-guards/wrong-source-result.json"
/usr/bin/jq -e '.passed|not' "$out/coverage-guards/wrong-source-result.json" > /dev/null
/usr/bin/jq '.records[0].fit=false' "$out/merged142/report.json" > "$out/coverage-guards/wrong-role.json"
coverage "$out/workers.json" "$out/coverage-guards/wrong-role.json" > "$out/coverage-guards/wrong-role-result.json"
/usr/bin/jq -e '.passed|not' "$out/coverage-guards/wrong-role-result.json" > /dev/null
coverage "$out/workers.json" "$out/merged142/report.json" > "$out/coverage.json"
/usr/bin/jq -e '.passed' "$out/coverage.json" > /dev/null
for manifest in runtime catalogs robot-asset recipes; do /usr/bin/sha256sum -c "$out/$manifest.sha256" > "$out/$manifest-final.log";done
mkdir "$out/finalizer-used"
cp "$dataset/"{finalize.sh,coverage.jq} "$out/finalizer-used/"
/usr/bin/sha256sum "$out/finalizer-used/"* "$out/merge" > "$out/finalizer.sha256"
mv "$out/merged142" "$out/data142"
printf '0\n' > "$out/dataset.exit"
echo '142 full histories admitted:112fitting/30validation; original132 preserved, forward-contact coverage verified.'
