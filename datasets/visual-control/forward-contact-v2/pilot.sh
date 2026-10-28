#!/usr/bin/env bash
set -euo pipefail
project="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
root="$project/build/flex/sim/forward-contact-v2"
[[ ! -e "$root/pilot" && ! -e "$root/pilot.exit" ]]
trap 'status=$?; printf "%s\n" "$status" > "$root/pilot.exit"' EXIT
mkdir "$root/pilot-catalog"
ln -s "$root/catalogs/0/0" "$root/pilot-catalog/0"
ln -s "$root/catalogs/0/4" "$root/pilot-catalog/1"
export PATH="$project/build/flex/sim/start-pose-v1/models/native-path"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1
cd "$project/build/flex/sim/approach35-v2/route-runtime"
./build/flex/control/control correct --policy "$project/build/flex/sim/start-pose-v1/policy-pose20" --output "$root/pilot" --scene-catalog "$root/pilot-catalog" \
    --episodes 2 --validation 1 --rollin 60 --rollin-min 60 --label-rollin --return-via-home --approach-side 1 --horizon 354 --seed 9580000 > "$root/pilot-recording.log" 2>&1
./build/flex/control/control pack-data --data "$root/pilot/data.bin" --output "$root/pilot-packed" > "$root/pilot-packed.log" 2>&1
./build/flex/control/control verify-data --run "$root/pilot" --data "$root/pilot-packed/data.bin" --output "$root/pilot-verified" > "$root/pilot-verified.log" 2>&1
"$root/states" "$root/pilot-packed/data.bin" "$root/pilot" "$root/pilot-states.json"
/usr/bin/jq -e '.passed and .episodes==2 and .studentRollinCommandsReplayed==120 and .studentRollinMaxAbsError==0 and .taskEventHintAbsent' "$root/pilot-verified/result.json" > /dev/null
/usr/bin/jq -e '.fittingForwardContactFrames>=50' "$root/pilot-states.json" > /dev/null
echo 'Matched fitting pilot adds audited forward-contact states and full physical recovery.'
