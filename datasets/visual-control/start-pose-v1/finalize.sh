#!/usr/bin/env bash
set -euo pipefail
project="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
dataset="$project/datasets/visual-control/start-pose-v1"
root="$project/build/flex/sim/start-pose-v1"
out="$root/artifacts"
base="$project/datasets/visual-control/return-recovery-v1/artifacts-primitive"
[[ "$(< "$out/collection.exit")" == 0 && ! -e "$out/data132" && ! -e "$out/finalize.exit" ]]
trap 'status=$?; printf "%s\n" "$status" > "$out/finalize.exit"' EXIT
cd "$project"
[[ "$(/usr/bin/sha256sum "$base/data96/data.bin" | /usr/bin/cut -d' ' -f1)" == a4dd1b61727f82e7ed044ebaf89268509cf47631a1392f7caa8249d826f3d6f8 ]]
build/flex/control/compiler datasets/visual-control/approach35-v1/merge.flex -o "$out/merge"
for worker in 0 1 2 3; do
    [[ "$(< "$out/worker-$worker.exit")" == 0 ]]
    sha="$(/usr/bin/sha256sum "$out/packed-$worker/data.bin" | /usr/bin/cut -d' ' -f1)"
    /usr/bin/jq -e --arg sha "$sha" '.passed and .episodes==9 and .datasetEpisodes==9 and .firstEpisode==0 and .dataSHA256==$sha and .commands==.supervisedSteps and .studentRollinCommandsReplayed==0 and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .executedCommandsMatchRecordings and .denseOracleLabels and .preActionAlignmentChecked and .zeroPaddingChecked and .taskEventHintAbsent' "$out/verified-$worker/result.json" > /dev/null
    shape="$(/usr/bin/od -An -v -tu8 -w24 -j8 -N24 "$out/packed-$worker/data.bin")"
    /usr/bin/jq -ne --arg shape "$shape" '$shape|split(" ")|map(select(length>0)|tonumber)|.[0]==9 and .[1]==8 and .[2]>=1 and .[2]<=354' > /dev/null
    for episode in {0..8}; do
        run="$out/runs/$worker/expert-$episode"
        /usr/bin/jq -e '.success and .maximumBrickDistanceM==0.35' "$run/result.json" > /dev/null
        /usr/bin/jq -e '.studentActions==0 and .burninActions==0 and .denseOracleLabels and .teacherApproachSide==1 and .studentWeightsSHA256=="a90445e2f138c326776e22deecceb0d5b04c18c3daaa1f1be76bef2fa107bc11"' "$run/supervision.json" > /dev/null
        /usr/bin/cmp "$root/catalogs/$worker/$episode/case.json" "$run/scene/case.json"
        /usr/bin/cmp "$root/catalogs/$worker/$episode/environment.bin" "$run/scene/environment.bin"
    done
    /usr/bin/jq --argjson worker "$worker" --arg sha "$sha" '{worker:$worker,episodes:9,fitTrajectories:8,auditedEpisodes:.episodes,physicalCompletions:9,studentCommands:.studentRollinCommandsReplayed,dataSHA256:$sha,commands,physicalMotionIncrements}' "$out/verified-$worker/result.json" > "$out/source-$worker.json"
done
/usr/bin/jq -s '.' "$out/"source-{0,1,2,3}.json > "$out/workers.json"
"$out/merge" "$out/packed-0/data.bin" "$out/runs/0" "$out/packed-1/data.bin" "$out/runs/1" "$out/merge01"
"$out/merge" "$out/merge01/data.bin" "$out/merge01" "$out/packed-2/data.bin" "$out/runs/2" "$out/merge012"
"$out/merge" "$out/merge012/data.bin" "$out/merge012" "$out/packed-3/data.bin" "$out/runs/3" "$out/new36"
"$out/merge" "$base/data96/data.bin" "$base/data96" "$out/new36/data.bin" "$out/new36" "$out/merged132"
"$out/runtime/build/flex/control/control" pack-data --data "$out/merged132/data.bin" --output "$out/repacked132" > "$out/repacked132.log" 2>&1
/usr/bin/cmp "$out/merged132/data.bin" "$out/repacked132/data.bin"
coverage() {
    /usr/bin/jq -n --slurpfile workers "$1" --slurpfile final "$2" --slurpfile catalog "$root/catalogs/report.json" --slurpfile old "$base/coverage.json" --slurpfile m01 "$out/merge01/report.json" --slurpfile m012 "$out/merge012/report.json" --slurpfile new "$out/new36/report.json" -f "$dataset/coverage.jq"
}
mkdir "$out/coverage-guards"
/usr/bin/jq '.[0].dataSHA256="wrong"' "$out/workers.json" > "$out/coverage-guards/wrong-source.json"
coverage "$out/coverage-guards/wrong-source.json" "$out/merged132/report.json" > "$out/coverage-guards/wrong-source-result.json"
/usr/bin/jq -e '.passed|not' "$out/coverage-guards/wrong-source-result.json" > /dev/null
/usr/bin/jq '.records[0].fit=false' "$out/merged132/report.json" > "$out/coverage-guards/wrong-role.json"
coverage "$out/workers.json" "$out/coverage-guards/wrong-role.json" > "$out/coverage-guards/wrong-role-result.json"
/usr/bin/jq -e '.passed|not' "$out/coverage-guards/wrong-role-result.json" > /dev/null
coverage "$out/workers.json" "$out/merged132/report.json" > "$out/coverage.json"
/usr/bin/jq -e '.passed' "$out/coverage.json" > /dev/null
for manifest in runtime catalogs robot-asset recipes; do /usr/bin/sha256sum -c "$out/$manifest.sha256" > "$out/$manifest-final.log"; done
mkdir "$out/finalizer-used"
cp "$dataset/"{finalize.sh,coverage.jq} "$out/finalizer-used/"
/usr/bin/sha256sum "$out/finalizer-used/"* "$out/merge" > "$out/finalizer.sha256"
mv "$out/merged132" "$out/data132"
printf '0\n' > "$out/dataset.exit"
echo '132 complete histories admitted:104fitting/28validation; all96 original histories retained.'
