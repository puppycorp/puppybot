#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$project/build/flex/sim/late-search-v1"
student="$project/build/flex/sim/forward-contact-v2/policy-contact142-20"
[[ ! -e "$root/pilot" && ! -e "$root/pilot.exit" ]]
trap 'status=$?; printf "%s\n" "$status" > "$root/pilot.exit"' EXIT
[[ "$(/usr/bin/sha256sum "$student/weights.bin" | /usr/bin/cut -d' ' -f1)" == c38fa6cbc57c7a1da996f2c50fa3b2deb251c71c073698ce1269a3e833183ab7 ]]
export PATH="$project/build/flex/sim/start-pose-v1/models/native-path"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1
cd "$project/build/flex/sim/approach35-v2/route-runtime"
./build/flex/control/control correct --policy "$student" --output "$root/pilot" --scene-catalog "$root/pilot-catalog" \
    --episodes 2 --validation 1 --rollin 120 --rollin-min 120 --label-rollin --return-via-home --approach-side 1 --horizon 354 --seed 9610000 > "$root/pilot-recording.log" 2>&1
./build/flex/control/control pack-data --data "$root/pilot/data.bin" --output "$root/pilot-packed" > "$root/pilot-packed.log" 2>&1
./build/flex/control/control verify-data --run "$root/pilot" --data "$root/pilot-packed/data.bin" --output "$root/pilot-verified" > "$root/pilot-verified.log" 2>&1
/usr/bin/jq -e '.passed and .episodes==2 and .studentRollinCommandsReplayed==240 and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .taskEventHintAbsent' "$root/pilot-verified/result.json" > /dev/null
echo 'Later-search pilot completed and independently audited; fitting-state usefulness remains a separate gate.'
