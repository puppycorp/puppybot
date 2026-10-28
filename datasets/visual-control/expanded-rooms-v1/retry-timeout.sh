#!/usr/bin/env bash
set -euo pipefail

project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$project/build/flex/sim/expanded-rooms-v1"
original="$root/cohort-v1"
prior="$root/cohort-retry-v1"
out="$root/timeout-retry-v1"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
printf '%s\n' "$BASHPID" > "$out/run.pid"
cd "$project"
while [[ ! -f "$prior/launcher.exit" ]];do
    [[ -f "$prior/launcher.pid" ]] && kill -0 "$(< "$prior/launcher.pid")" || { echo 'Previous retry launcher disappeared.';exit 1; }
    /usr/bin/sleep 10
done
[[ "$(< "$original/worker-0.exit")" != 0 && "$(< "$prior/worker-0.exit")" != 0 ]]
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
export PATH="$out/native-path"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1
export PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
mkdir "$out/runs"
cd "$out/runtime"
./build/flex/control/control correct --policy "$out/student" --output "$out/runs/0" --scene-catalog "$out/catalog/0" --episodes 5 --validation 1 --rollin 120 --rollin-min 120 --label-rollin --return-via-home --approach-side 1 --horizon 354 --seed 9740000 > "$out/worker-0.log" 2>&1
./build/flex/control/control pack-data --data "$out/runs/0/data.bin" --output "$out/packed-0" > "$out/packed-0.log" 2>&1
./build/flex/control/control verify-data --run "$out/runs/0" --data "$out/packed-0/data.bin" --output "$out/verified-0" > "$out/verified-0.log" 2>&1
/usr/bin/jq -e '.passed and .episodes==5 and .datasetEpisodes==5 and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .executedCommandsMatchRecordings and .denseOracleLabels and .preActionAlignmentChecked and .taskEventHintAbsent' "$out/verified-0/result.json" > /dev/null
for episode in {0..4};do
    /usr/bin/jq -e --argjson seed "$((9740000+episode))" '.success and .maximumBrickDistanceM==0.35 and .seed==$seed' "$out/runs/0/expert-$episode/result.json" > /dev/null
    for file in case.json environment.bin;do /usr/bin/cmp "$original/catalog/0/$episode/$file" "$out/runs/0/expert-$episode/scene/$file";done
done
"$out/diagnose" "$out/packed-0/data.bin" "$out/diagnostic-0.json"
cd "$project"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
echo 'The exact timed-out worker completed with a longer bounded stream timeout and passed all data audits.'
