#!/usr/bin/env bash
set -euo pipefail

project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$project/build/flex/sim/expanded-rooms-v1"
out="$root/timeout-consumption-pilot-v1"
original="$root/timeout-retry-v1/runs/0/expert-1"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
printf '%s\n' "$BASHPID" > "$out/run.pid"
cd "$project"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
export PATH="$out/native-path"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1
export PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
cd "$out/runtime"
./build/flex/control/control correct --policy "$out/student" --output "$out/runs" --scene-catalog "$out/catalog" --episodes 2 --validation 1 --rollin 120 --rollin-min 120 --label-rollin --return-via-home --approach-side 1 --horizon 354 --seed 9740001 > "$out/collection.log" 2>&1
./build/flex/control/control pack-data --data "$out/runs/data.bin" --output "$out/packed" > "$out/packed.log" 2>&1
./build/flex/control/control verify-data --run "$out/runs" --data "$out/packed/data.bin" --output "$out/verified" > "$out/verified.log" 2>&1
/usr/bin/jq -e '.passed and .episodes==2 and .datasetEpisodes==2 and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .executedCommandsMatchRecordings and .denseOracleLabels and .taskEventHintAbsent' "$out/verified/result.json" > /dev/null
for episode in 0 1;do
    /usr/bin/jq -e --argjson seed "$((9740001+episode))" '.success and .maximumBrickDistanceM==0.35 and .seed==$seed' "$out/runs/expert-$episode/result.json" > /dev/null
    for file in case.json environment.bin;do /usr/bin/cmp "$out/catalog/$episode/$file" "$out/runs/expert-$episode/scene/$file";done
done
frame="$(/usr/bin/jq -r '.totalSteps' "$original/initial.json")"
[[ "$frame" == "$(/usr/bin/jq -r '.totalSteps' "$out/runs/expert-0/initial.json")" ]]
for ((index=0;index<120;index++));do
    for extension in rgb feedback;do /usr/bin/cmp "$original/actor-$((frame+index*10)).$extension" "$out/runs/expert-0/actor-$((frame+index*10)).$extension";done
done
/usr/bin/jq -sc '[.[0:120][]|[.step,.action]]' "$original/decisions.jsonl" > "$out/original-prefix.json"
/usr/bin/jq -sc '[.[0:120][]|[.step,.action]]' "$out/runs/expert-0/decisions.jsonl" > "$out/new-prefix.json"
/usr/bin/cmp "$out/original-prefix.json" "$out/new-prefix.json"
cd "$project"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
echo 'Corrected same-scene retry passed independent data audit and student-prefix parity.'
