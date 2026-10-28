#!/usr/bin/env bash
set -euo pipefail
project="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
root="$project/build/flex/sim/start-pose-v1"
out="$root/artifacts"
dataset="$project/datasets/visual-control/start-pose-v1"
[[ ! -e "$out" ]]
[[ "$(< "$root/pilot-side1.exit")" == 0 ]]
/usr/bin/jq -e '.passed and .episodes==2 and .studentRollinCommandsReplayed==0 and .taskEventHintAbsent' "$root/pilot-side1-verified/result.json" > /dev/null
/usr/bin/jq -e '.fittingScenes==32 and .validationScenes==4 and (.records|length)==36 and (.records|all(.fit==(.layout<6)))' "$root/catalogs/report.json" > /dev/null
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/collection.exit"' EXIT
cd "$project"
cp -a build/flex/sim/approach35-v2/route-runtime "$out/runtime"
cp -a build/flex/sim/sequence-mirror-v1/models/initial-policy "$out/student"
cp -a build/flex/sim/sequence-mirror-v1/models/native-path "$out/native-path"
mkdir "$out/recipes" "$out/runs"
cp "$dataset/"{generate.flex,collect.sh,protocol.json} "$out/recipes/"
/usr/bin/find "$out/runtime" -type f -print0 | /usr/bin/sort -z | /usr/bin/xargs -0 /usr/bin/sha256sum > "$out/runtime.sha256"
/usr/bin/find "$root/catalogs" -type f -print0 | /usr/bin/sort -z | /usr/bin/xargs -0 /usr/bin/sha256sum > "$out/catalogs.sha256"
/usr/bin/sha256sum build/flex/sim/puppybot.bin > "$out/robot-asset.sha256"
/usr/bin/sha256sum "$out/recipes/"* > "$out/recipes.sha256"
export PATH="$out/native-path"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1
cd "$out/runtime"
pids=()
for worker in 0 1 2 3; do
    (
        trap 'status=$?; printf "%s\n" "$status" > "$out/worker-'"$worker"'.exit"' EXIT
        printf '%s\n' "$BASHPID" > "$out/worker-$worker.pid"
        ./build/flex/control/control correct --policy "$out/student" --output "$out/runs/$worker" --scene-catalog "$root/catalogs/$worker" \
            --episodes 9 --validation 1 --rollin 0 --rollin-min 0 --label-rollin --return-via-home --approach-side 1 --horizon 354 --seed "$((9540000+worker*1000))" > "$out/worker-$worker.log" 2>&1
        ./build/flex/control/control pack-data --data "$out/runs/$worker/data.bin" --output "$out/packed-$worker" > "$out/packed-$worker.log" 2>&1
        ./build/flex/control/control verify-data --run "$out/runs/$worker" --data "$out/packed-$worker/data.bin" --output "$out/verified-$worker" > "$out/verified-$worker.log" 2>&1
        /usr/bin/jq -e '.passed and .episodes==9 and .datasetEpisodes==9 and .firstEpisode==0 and .studentRollinCommandsReplayed==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .taskEventHintAbsent' "$out/verified-$worker/result.json" > /dev/null
        for episode in {0..8}; do
            /usr/bin/cmp "$root/catalogs/$worker/$episode/case.json" "$out/runs/$worker/expert-$episode/scene/case.json"
            /usr/bin/cmp "$root/catalogs/$worker/$episode/environment.bin" "$out/runs/$worker/expert-$episode/scene/environment.bin"
        done
    ) &
    pids+=("$!")
done
status=0
for pid in "${pids[@]}"; do if ! wait "$pid"; then status=1; fi; done
(( status==0 ))
cd "$project"
for manifest in runtime catalogs robot-asset recipes; do /usr/bin/sha256sum -c "$out/$manifest.sha256" > "$out/$manifest-after.log"; done
echo 'All36 physical pose histories audited; aggregation and neural evaluation remain separate.'
