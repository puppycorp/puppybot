#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$project/build/flex/sim/late-search-v1"
old="$root/artifacts"
out="$root/artifacts-v2"
[[ ! -e "$out" && "$(< "$old/collection.exit")" == 1 && "$(< "$old/worker-0.exit")" == 0 && "$(< "$old/worker-1.exit")" == 0 && "$(< "$old/worker-2.exit")" == 1 ]]
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/collection.exit"' EXIT
printf '%s\n' "$BASHPID" > "$root/resume.pid"
cd "$project"
cp -a "$old/runtime" "$old/student" "$old/native-path" "$out/"
mkdir "$out/recipes" "$out/runs"
cp "$project/datasets/visual-control/late-search-v1/"{generate.flex,resume.sh,replace-validation.flex,diagnose.flex,protocol.json} "$out/recipes/"
cp "$root/diagnose" "$root/replace-validation" "$out/"
for worker in 0 1; do
    ln -s "$old/runs/$worker" "$out/runs/$worker"
    for name in packed verified; do ln -s "$old/$name-$worker" "$out/$name-$worker";done
    ln -s "$old/diagnostic-$worker.json" "$out/diagnostic-$worker.json"
    cp "$old/worker-$worker.exit" "$out/worker-$worker.exit"
done
/usr/bin/find "$out/runtime" -type f -print0 | /usr/bin/sort -z | /usr/bin/xargs -0 /usr/bin/sha256sum > "$out/runtime.sha256"
/usr/bin/find "$root/catalogs-v2" -type f -print0 | /usr/bin/sort -z | /usr/bin/xargs -0 /usr/bin/sha256sum > "$out/catalogs.sha256"
/usr/bin/sha256sum build/flex/sim/puppybot.bin > "$out/robot-asset.sha256"
/usr/bin/sha256sum "$out/recipes/"* "$out/diagnose" "$out/replace-validation" > "$out/recipes.sha256"
export PATH="$out/native-path"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1
cd "$out/runtime"
pids=()
(
    trap 'status=$?; printf "%s\n" "$status" > "$out/worker-2.exit"' EXIT
    printf '%s\n' "$BASHPID" > "$out/worker-2.pid"
    ./build/flex/control/control verify-data --run "$old/runs/2" --data "$old/packed-2/data.bin" --output "$out/verified-original-fitting-2" --audit-start 0 --audit-count 4 > "$out/verified-original-fitting-2.log" 2>&1
    /usr/bin/jq -e '.passed and .episodes==4 and .firstEpisode==0 and .studentRollinCommandsReplayed==480 and .studentRollinMaxAbsError==0' "$out/verified-original-fitting-2/result.json" > /dev/null
    ./build/flex/control/control correct --policy "$out/student" --output "$out/repair" --scene-catalog "$root/repair-catalog" \
        --episodes 2 --validation 1 --rollin 120 --rollin-min 120 --label-rollin --return-via-home --approach-side 0 --horizon 512 --seed 9622003 > "$out/repair.log" 2>&1
    ./build/flex/control/control pack-data --data "$out/repair/data.bin" --output "$out/repair-packed" > "$out/repair-packed.log" 2>&1
    ./build/flex/control/control verify-data --run "$out/repair" --data "$out/repair-packed/data.bin" --output "$out/repair-verified" > "$out/repair-verified.log" 2>&1
    /usr/bin/jq -e '.passed and .episodes==2 and .studentRollinCommandsReplayed==240 and .studentRollinMaxAbsError==0' "$out/repair-verified/result.json" > /dev/null
    "$out/replace-validation" "$old/packed-2/data.bin" "$old/runs/2" "$out/repair-packed/data.bin" "$out/repair" "$out/runs/2"
    ./build/flex/control/control pack-data --data "$out/runs/2/data.bin" --output "$out/packed-2" > "$out/packed-2.log" 2>&1
    ./build/flex/control/control verify-data --run "$out/runs/2" --data "$out/packed-2/data.bin" --output "$out/verified-2" > "$out/verified-2.log" 2>&1
    /usr/bin/jq -e '.passed and .episodes==5 and .datasetEpisodes==5 and .firstEpisode==0 and .studentRollinCommandsReplayed==600 and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .taskEventHintAbsent' "$out/verified-2/result.json" > /dev/null
    "$out/diagnose" "$out/packed-2/data.bin" "$out/diagnostic-2.json"
) &
pids+=("$!")
for worker in 3 4 5; do
    (
        trap 'status=$?; printf "%s\n" "$status" > "$out/worker-'"$worker"'.exit"' EXIT
        printf '%s\n' "$BASHPID" > "$out/worker-$worker.pid"
        ./build/flex/control/control correct --policy "$out/student" --output "$out/runs/$worker" --scene-catalog "$root/catalogs-v2/$worker" \
            --episodes 5 --validation 1 --rollin 120 --rollin-min 120 --label-rollin --return-via-home --approach-side 1 --horizon 512 --seed "$((9620000+worker*1000))" > "$out/worker-$worker.log" 2>&1
        ./build/flex/control/control pack-data --data "$out/runs/$worker/data.bin" --output "$out/packed-$worker" > "$out/packed-$worker.log" 2>&1
        ./build/flex/control/control verify-data --run "$out/runs/$worker" --data "$out/packed-$worker/data.bin" --output "$out/verified-$worker" > "$out/verified-$worker.log" 2>&1
        /usr/bin/jq -e '.passed and .episodes==5 and .datasetEpisodes==5 and .firstEpisode==0 and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .taskEventHintAbsent' "$out/verified-$worker/result.json" > /dev/null
        "$out/diagnose" "$out/packed-$worker/data.bin" "$out/diagnostic-$worker.json"
    ) &
    pids+=("$!")
done
status=0
for pid in "${pids[@]}"; do if ! wait "$pid"; then status=1;fi;done
(( status==0 ))
cd "$project"
for manifest in runtime catalogs robot-asset recipes; do /usr/bin/sha256sum -c "$out/$manifest.sha256" > "$out/$manifest-after.log";done
/usr/bin/jq -s '{fittingLaterDisagreements:([.[].windows[]|select(.fit and .firstAction==60)|.oracleDisagreements]|add),fittingHistoriesWith20LaterDisagreements:([.[].windows[]|select(.fit and .firstAction==60 and .oracleDisagreements>=20)]|length),passed:(([.[].windows[]|select(.fit and .firstAction==60)|.oracleDisagreements]|add)>=300 and ([.[].windows[]|select(.fit and .firstAction==60 and .oracleDisagreements>=20)]|length)>=8),sources:.}' "$out/diagnostic-"{0,1,2,3,4,5}.json > "$out/state-coverage.json"
echo 'Original fitting histories retained, rejected validation trip repaired, all declared trips audited.'
