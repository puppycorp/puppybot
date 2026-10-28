#!/usr/bin/env bash
set -euo pipefail
project="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
root="$project/build/flex/sim/start-pose-v1"
[[ ! -e "$root/pilot" && ! -e "$root/pilot.exit" ]]
trap 'status=$?; printf "%s\n" "$status" > "$root/pilot.exit"' EXIT
mkdir "$root/pilot-catalog"
ln -s "$root/catalogs/3/7" "$root/pilot-catalog/0"
ln -s "$root/catalogs/3/8" "$root/pilot-catalog/1"
export PATH="$project/build/flex/sim/sequence-mirror-v1/models/native-path"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1
cd "$project"
/usr/bin/sha256sum -c build/flex/sim/approach35-v2/route-runtime.sha256 > "$root/pilot-runtime-integrity.log"
cd "$project/build/flex/sim/approach35-v2/route-runtime"
./build/flex/control/control correct --policy "$project/build/flex/sim/sequence-mirror-v1/models/initial-policy" \
    --output "$root/pilot" --scene-catalog "$root/pilot-catalog" --episodes 2 --validation 1 \
    --rollin 0 --rollin-min 0 --label-rollin --return-via-home --hidden-target --horizon 354 --seed 9530000 > "$root/pilot-recording.log" 2>&1
./build/flex/control/control pack-data --data "$root/pilot/data.bin" --output "$root/pilot-packed" > "$root/pilot-packed.log" 2>&1
./build/flex/control/control verify-data --run "$root/pilot" --data "$root/pilot-packed/data.bin" --output "$root/pilot-verified" > "$root/pilot-verified.log" 2>&1
/usr/bin/jq -e '.passed and .episodes==2 and .studentRollinCommandsReplayed==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .taskEventHintAbsent' "$root/pilot-verified/result.json" > /dev/null
for index in 0 1; do
    /usr/bin/cmp "$root/pilot-catalog/$index/case.json" "$root/pilot/expert-$index/scene/case.json"
    /usr/bin/cmp "$root/pilot-catalog/$index/environment.bin" "$root/pilot/expert-$index/scene/environment.bin"
done
echo 'Physical fitting-pose pilot completed and passed native data audit; no neural success claimed.'
