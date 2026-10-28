#!/usr/bin/env bash
set -euo pipefail
project="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
root="$project/build/flex/sim/start-pose-v1"
side="${1:?Approach side1..3 is required}"
[[ "$side" == 1 || "$side" == 2 || "$side" == 3 ]]
out="$root/pilot-side$side"
[[ ! -e "$out" && ! -e "$out.exit" ]]
trap 'status=$?; printf "%s\n" "$status" > "$out.exit"' EXIT
export PATH="$project/build/flex/sim/sequence-mirror-v1/models/native-path"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1
cd "$project/build/flex/sim/approach35-v2/route-runtime"
./build/flex/control/control correct --policy "$project/build/flex/sim/sequence-mirror-v1/models/initial-policy" \
    --output "$out" --scene-catalog "$root/pilot-catalog" --episodes 2 --validation 1 \
    --rollin 0 --rollin-min 0 --label-rollin --return-via-home --hidden-target --horizon 354 --seed 9530000 --approach-side "$side" > "$out-recording.log" 2>&1
./build/flex/control/control pack-data --data "$out/data.bin" --output "$out-packed" > "$out-packed.log" 2>&1
./build/flex/control/control verify-data --run "$out" --data "$out-packed/data.bin" --output "$out-verified" > "$out-verified.log" 2>&1
/usr/bin/jq -e '.passed and .episodes==2 and .studentRollinCommandsReplayed==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .taskEventHintAbsent' "$out-verified/result.json" > /dev/null
for index in 0 1; do
    /usr/bin/cmp "$root/pilot-catalog/$index/case.json" "$out/expert-$index/scene/case.json"
    /usr/bin/cmp "$root/pilot-catalog/$index/environment.bin" "$out/expert-$index/scene/environment.bin"
done
echo 'Same-scene physical pose repair passed native data audit; no neural success claimed.'
