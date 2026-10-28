#!/usr/bin/env bash
set -euo pipefail

project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$project/build/flex/sim/expanded-rooms-v1"
original="$root/cohort-v1"
prior="$root/cohort-retry-v1"
pilot="$root/consumption-match-v1"
accepted="$root/consumption-match-accepted-v1"
out="$root/fitting-repair-v1"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
printf '%s\n' "$BASHPID" > "$out/run.pid"
cd "$project"
while [[ ! -f "$prior/worker-4.exit" ]];do
    [[ ! -f "$prior/launcher.exit" ]] || { echo 'Previous retry ended without worker 4.';exit 1; }
    [[ -f "$prior/launcher.pid" ]] && kill -0 "$(< "$prior/launcher.pid")" || { echo 'Previous retry launcher disappeared.';exit 1; }
    /usr/bin/sleep 10
done
[[ "$(< "$accepted/run.exit")" == 0 ]]
/usr/bin/jq -e '.passed and .independentPhysicalAndReplayAuditsPassed and .studentPrefixFramesAndActionsIdentical==120 and .originalMismatchedDetectionRejectedAtStep==2075' "$accepted/result.json" > /dev/null
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
export PATH="$out/native-path"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1
mkdir "$out/runs"
"$out/replace-fitting" "$original/packed-4/data.bin" "$original/runs/4" "$pilot/packed/data.bin" "$pilot/runs" "$out/runs/4"
oldsha="$(/usr/bin/sha256sum "$original/packed-4/data.bin" | /usr/bin/cut -d' ' -f1)"
repairsha="$(/usr/bin/sha256sum "$pilot/packed/data.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg old "$oldsha" --arg repair "$repairsha" '.preservesOtherHistoriesAndRoles and .replacesOnlyFittingIndex==2 and .sourceSHA256==[$old,$repair] and (.records|map(.source))==[0,0,1,0,0] and (.records|map(.sourceIndex))==[0,1,0,3,4] and (.records|map(.fit))==[true,true,true,true,false]' "$out/runs/4/report.json" > /dev/null
cd "$out/runtime"
./build/flex/control/control pack-data --data "$out/runs/4/data.bin" --output "$out/packed-4" > "$out/packed-4.log" 2>&1
./build/flex/control/control verify-data --run "$out/runs/4" --data "$out/packed-4/data.bin" --output "$out/verified-4" > "$out/verified-4.log" 2>&1
/usr/bin/jq -e '.passed and .episodes==5 and .datasetEpisodes==5 and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .executedCommandsMatchRecordings and .denseOracleLabels and .preActionAlignmentChecked and .zeroPaddingChecked and .taskEventHintAbsent' "$out/verified-4/result.json" > /dev/null
for episode in {0..4};do
    /usr/bin/jq -e --argjson seed "$((9744000+episode))" '.success and .maximumBrickDistanceM==0.35 and .seed==$seed' "$out/runs/4/expert-$episode/result.json" > /dev/null
    for file in case.json environment.bin;do /usr/bin/cmp "$original/catalog/4/$episode/$file" "$out/runs/4/expert-$episode/scene/$file";done
done
"$out/diagnose" "$out/packed-4/data.bin" "$out/diagnostic-4.json"
cd "$project"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
echo 'One fitting history repaired on the same scene; all five selected histories passed independent audits.'
