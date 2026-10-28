#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?}"
root="$project/build/flex/sim/expanded-rooms-v1"
out="${PUPPYBOT_PILOT_DIR:-$root/pilot-v2}"
actor="$project/build/flex/sim/target-actor-v1"
[[ ! -e "$out/run.exit" && ! -e "$out/runs" ]]
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
printf '%s\n' "$BASHPID" > "$out/run.pid"
while [[ ! -f "$actor/train.exit" ]];do kill -0 "$(< "$actor/train.pid")" || { echo 'Earlier actor training disappeared';exit 1; };/usr/bin/sleep 10;done
[[ "$(< "$actor/train.exit")" == 0 ]]
cd "$project"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
/usr/bin/jq -e '.layoutId==13 and .fit and (.rooms|length)==2' "$out/catalog/0/layout.json" >/dev/null
/usr/bin/jq -e '.layoutId==7 and (.fit|not) and (.rooms|length)==2' "$out/catalog/1/layout.json" >/dev/null
/usr/bin/jq -e '.heatmapActorFeatures and .heatmapActorGradientDetached and (.taskFeedback|not)' "$out/student/receipt.json" >/dev/null
export PATH="$out/native-path"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1
cd "$out/runtime"
./build/flex/control/control correct --policy "$out/student" --output "$out/runs" --scene-catalog "$out/catalog" --episodes 2 --validation 1 --rollin 120 --rollin-min 120 --label-rollin --return-via-home --approach-side 1 --horizon 512 --seed 9731000 > "$out/collection.log" 2>&1
./build/flex/control/control pack-data --data "$out/runs/data.bin" --output "$out/packed" > "$out/packed.log" 2>&1
./build/flex/control/control verify-data --run "$out/runs" --data "$out/packed/data.bin" --output "$out/verified" > "$out/verified.log" 2>&1
/usr/bin/jq -e '.passed and .episodes==2 and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .executedCommandsMatchRecordings and .denseOracleLabels and .preActionAlignmentChecked and .taskEventHintAbsent' "$out/verified/result.json" >/dev/null
for index in 0 1;do for file in case.json environment.bin;do /usr/bin/cmp "$out/catalog/$index/$file" "$out/runs/expert-$index/scene/$file";done;done
"$out/diagnose" "$out/packed/data.bin" "$out/diagnostic.json"
cd "$project"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
echo 'Two teacher-recovery pilot trips audited; no new data admitted or model retrained.'
