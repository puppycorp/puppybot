#!/usr/bin/env bash
set -euo pipefail
project="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
root="$project/build/flex/sim/forward-contact-v2"
out="$root/artifacts"
dataset="$project/datasets/visual-control/forward-contact-v2"
[[ ! -e "$out" && "$(< "$root/pilot.exit")" == 0 ]]
/usr/bin/jq -e '.fittingForwardContactFrames>=50' "$root/pilot-states.json" > /dev/null
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/collection.exit"' EXIT
cd "$project"
cp -a build/flex/sim/approach35-v2/route-runtime "$out/runtime"
cp -a build/flex/sim/start-pose-v1/policy-pose20 "$out/student"
cp -a build/flex/sim/start-pose-v1/models/native-path "$out/native-path"
[[ "$(/usr/bin/sha256sum "$out/student/weights.bin" | /usr/bin/cut -d' ' -f1)" == c03fb6c357fd427e648d3d5fa7068c95f980a2a60f2f71a5b23c0b20e1c50934 ]]
mkdir "$out/recipes" "$out/runs"
cp "$dataset/"{generate.flex,collect.sh,states.flex,protocol.json} "$out/recipes/"
cp datasets/visual-control/forward-contact-v1/states.flex "$out/recipes/states-implementation.flex"
build/flex/control/compiler "$dataset/states.flex" -o "$out/states"
/usr/bin/find "$out/runtime" -type f -print0 | /usr/bin/sort -z | /usr/bin/xargs -0 /usr/bin/sha256sum > "$out/runtime.sha256"
/usr/bin/find "$root/catalogs" -type f -print0 | /usr/bin/sort -z | /usr/bin/xargs -0 /usr/bin/sha256sum > "$out/catalogs.sha256"
/usr/bin/sha256sum build/flex/sim/puppybot.bin > "$out/robot-asset.sha256"
/usr/bin/sha256sum "$out/recipes/"* "$out/states" > "$out/recipes.sha256"
export PATH="$out/native-path"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1
cd "$out/runtime"
pids=()
for worker in 0 1; do
    (
        trap 'status=$?; printf "%s\n" "$status" > "$out/worker-'"$worker"'.exit"' EXIT
        printf '%s\n' "$BASHPID" > "$out/worker-$worker.pid"
        window=60;if (( worker==1 )); then window=8;fi
        ./build/flex/control/control correct --policy "$out/student" --output "$out/runs/$worker" --scene-catalog "$root/catalogs/$worker" \
            --episodes 5 --validation 1 --rollin "$window" --rollin-min "$window" --label-rollin --return-via-home --approach-side 1 --horizon 354 --seed "$((9580000+worker*1000))" > "$out/worker-$worker.log" 2>&1
        ./build/flex/control/control pack-data --data "$out/runs/$worker/data.bin" --output "$out/packed-$worker" > "$out/packed-$worker.log" 2>&1
        ./build/flex/control/control verify-data --run "$out/runs/$worker" --data "$out/packed-$worker/data.bin" --output "$out/verified-$worker" > "$out/verified-$worker.log" 2>&1
        /usr/bin/jq -e '.passed and .episodes==5 and .datasetEpisodes==5 and .firstEpisode==0 and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .taskEventHintAbsent' "$out/verified-$worker/result.json" > /dev/null
        "$out/states" "$out/packed-$worker/data.bin" "$out/runs/$worker" "$out/states-$worker.json"
    ) &
    pids+=("$!")
done
status=0
for pid in "${pids[@]}"; do if ! wait "$pid"; then status=1; fi;done
(( status==0 ))
cd "$project"
for manifest in runtime catalogs robot-asset recipes; do /usr/bin/sha256sum -c "$out/$manifest.sha256" > "$out/$manifest-after.log";done
/usr/bin/jq -s '{newFittingForwardContactFrames:(map(.fittingForwardContactFrames)|add),newFittingForwardContactReverseLabels:(map(.fittingForwardContactReverseLabels)|add),passed:((map(.fittingForwardContactFrames)|add)>=200),sources:.}' "$out/"states-{0,1}.json > "$out/state-coverage.json"
echo 'Matched contact histories audited; fitting-state coverage and aggregate admission are separate gates.'
