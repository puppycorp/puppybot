#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$project/build/flex/sim/late-search-v1"
out="$root/artifacts"
[[ ! -e "$out" && "$(< "$root/pilot.exit")" == 0 && "$(< "$root/compatibility.exit")" == 0 ]]
/usr/bin/jq -e '.passed and .studentRollinCommandsReplayed==240 and .studentRollinMaxAbsError==0' "$root/pilot-verified/result.json" > /dev/null
/usr/bin/jq -e 'any(.windows[]; .fit and .firstAction==60 and .frames==60 and .oracleDisagreements>=20)' "$root/pilot-diagnostic.json" > /dev/null
/usr/bin/jq -e '.passed' "$root/size-contracts/result.json" "$root/guards/result.json" "$root/compatibility/result.json" > /dev/null
/usr/bin/cmp "$root/compatibility/"{old,new}-losses.json
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/collection.exit"' EXIT
cd "$project"
cp -a build/flex/sim/approach35-v2/route-runtime "$out/runtime"
cp -a build/flex/sim/forward-contact-v2/policy-contact142-20 "$out/student"
cp -a build/flex/sim/start-pose-v1/models/native-path "$out/native-path"
# Collection behavior stays frozen. Only the shared host dataset reader changes.
cp build/flex/control/control "$out/runtime/build/flex/control/control"
[[ "$(/usr/bin/sha256sum "$out/student/weights.bin" | /usr/bin/cut -d' ' -f1)" == c38fa6cbc57c7a1da996f2c50fa3b2deb251c71c073698ce1269a3e833183ab7 ]]
mkdir "$out/recipes" "$out/runs"
cp "$project/datasets/visual-control/late-search-v1/"{generate.flex,collect.sh,diagnose.flex,protocol.json} "$out/recipes/"
cp "$root/diagnose" "$out/diagnose"
/usr/bin/find "$out/runtime" -type f -print0 | /usr/bin/sort -z | /usr/bin/xargs -0 /usr/bin/sha256sum > "$out/runtime.sha256"
/usr/bin/find "$root/catalogs-v2" -type f -print0 | /usr/bin/sort -z | /usr/bin/xargs -0 /usr/bin/sha256sum > "$out/catalogs.sha256"
/usr/bin/sha256sum build/flex/sim/puppybot.bin > "$out/robot-asset.sha256"
/usr/bin/sha256sum "$out/recipes/"* "$out/diagnose" > "$out/recipes.sha256"
export PATH="$out/native-path"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1
cd "$out/runtime"
for group in 0 3; do
    pids=()
    for offset in 0 1 2; do
        worker=$((group+offset))
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
done
cd "$project"
for manifest in runtime catalogs robot-asset recipes; do /usr/bin/sha256sum -c "$out/$manifest.sha256" > "$out/$manifest-after.log";done
/usr/bin/jq -s '{fittingLaterDisagreements:([.[].windows[]|select(.fit and .firstAction==60)|.oracleDisagreements]|add),fittingHistoriesWith20LaterDisagreements:([.[].windows[]|select(.fit and .firstAction==60 and .oracleDisagreements>=20)]|length),passed:(([.[].windows[]|select(.fit and .firstAction==60)|.oracleDisagreements]|add)>=300 and ([.[].windows[]|select(.fit and .firstAction==60 and .oracleDisagreements>=20)]|length)>=8),sources:.}' "$out/diagnostic-"{0,1,2,3,4,5}.json > "$out/state-coverage.json"
echo 'Later-search trips audited; fitting coverage and aggregate admission remain separate gates.'
