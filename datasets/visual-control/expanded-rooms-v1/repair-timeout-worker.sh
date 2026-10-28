#!/usr/bin/env bash
set -euo pipefail

project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$project/build/flex/sim/expanded-rooms-v1"
original="$root/cohort-v1"
source="$root/timeout-retry-v1"
audits="$root/timeout-individual-audit-v1"
first="$root/timeout-consumption-pilot-v1"
second="$root/timeout-consumption-pilot-3-v1"
out="$root/timeout-worker-repair-v1"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
printf '%s\n' "$BASHPID" > "$out/run.pid"
cd "$project"
for job in "$audits/run" "$first/run" "$second/run";do
    while [[ ! -f "$job.exit" ]];do
        [[ -f "$job.pid" ]] && kill -0 "$(< "$job.pid")" || { echo "Process exited without status: $job";exit 1; }
        /usr/bin/sleep 10
    done
    [[ "$(< "$job.exit")" == 0 ]] || { echo "Recovery prerequisite failed: $job";exit 1; }
done
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
for pilot in "$first" "$second";do
    /usr/bin/sha256sum -c "$pilot/inputs.sha256" > "$out/$(basename "$pilot")-integrity.log"
    sha="$(/usr/bin/sha256sum "$pilot/packed/data.bin" | /usr/bin/cut -d' ' -f1)"
    /usr/bin/jq -e --arg sha "$sha" '.passed and .episodes==2 and .datasetEpisodes==2 and .dataSHA256==$sha and .studentRollinMaxAbsError==0 and .taskEventHintAbsent' "$pilot/verified/result.json" > /dev/null
done
oldsha="$(/usr/bin/sha256sum "$source/packed-0/data.bin" | /usr/bin/cut -d' ' -f1)"
for episode in 0 2 4;do
    [[ "$(< "$audits/audit-$episode.exit")" == 0 ]]
    /usr/bin/jq -e --arg sha "$oldsha" --argjson episode "$episode" '.passed and .episodes==1 and .datasetEpisodes==5 and .firstEpisode==$episode and .dataSHA256==$sha and .studentRollinMaxAbsError==0' "$audits/audit-$episode/result.json" > /dev/null
done
for episode in 1 3;do
    [[ "$(< "$audits/audit-$episode.exit")" != 0 ]]
    /usr/bin/rg -q 'RGB consumption bbox does not contain the actual brick projection' "$audits/audit-$episode.log"
done
export PATH="$out/native-path"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1
mkdir "$out/runs"
"$out/replace-fitting" "$source/packed-0/data.bin" "$source/runs/0" "$first/packed/data.bin" "$first/runs" "$out/stage1" 1
"$out/replace-fitting" "$out/stage1/data.bin" "$out/stage1" "$second/packed/data.bin" "$second/runs" "$out/runs/0" 3
/usr/bin/jq -e '.preservesOtherHistoriesAndRoles and .replacesOnlyFittingIndex==1 and (.records|map(.source))==[0,1,0,0,0] and (.records|map(.fit))==[true,true,true,true,false]' "$out/stage1/report.json" > /dev/null
/usr/bin/jq -e '.preservesOtherHistoriesAndRoles and .replacesOnlyFittingIndex==3 and (.records|map(.source))==[0,0,0,1,0] and (.records|map(.fit))==[true,true,true,true,false]' "$out/runs/0/report.json" > /dev/null
cd "$out/runtime"
./build/flex/control/control pack-data --data "$out/runs/0/data.bin" --output "$out/packed-0" > "$out/packed-0.log" 2>&1
./build/flex/control/control verify-data --run "$out/runs/0" --data "$out/packed-0/data.bin" --output "$out/verified-0" > "$out/verified-0.log" 2>&1
/usr/bin/jq -e '.passed and .episodes==5 and .datasetEpisodes==5 and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .executedCommandsMatchRecordings and .denseOracleLabels and .preActionAlignmentChecked and .zeroPaddingChecked and .taskEventHintAbsent' "$out/verified-0/result.json" > /dev/null
for episode in {0..4};do
    /usr/bin/jq -e --argjson seed "$((9740000+episode))" '.success and .maximumBrickDistanceM==0.35 and .seed==$seed' "$out/runs/0/expert-$episode/result.json" > /dev/null
    for file in case.json environment.bin;do /usr/bin/cmp "$original/catalog/0/$episode/$file" "$out/runs/0/expert-$episode/scene/$file";done
done
"$out/diagnose" "$out/packed-0/data.bin" "$out/diagnostic-0.json"
cd "$project"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
echo 'Two same-scene fitting histories repaired; all five selected histories passed independent audits.'
