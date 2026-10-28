#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?}"
root="$project/build/flex/sim/expanded-rooms-v1"
out="$root/cohort-v1"
[[ ! -e "$out/run.exit" && ! -e "$out/runs" ]]
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
printf '%s\n' "$BASHPID" > "$out/run.pid"
[[ "$(< "$root/pilot-v2/run.exit")" == 0 ]]
/usr/bin/jq -e '.passed and .episodes==2 and .studentRollinCommandsReplayed==240 and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .taskEventHintAbsent' "$root/pilot-v2/verified/result.json" >/dev/null
/usr/bin/jq -e '.fittingScenes==24 and .validationScenes==6 and all(.records[]; .layout!=10 and .layout!=11 and .fit==(.episode<4))' "$out/catalog/report.json" >/dev/null
cd "$project"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
export PATH="$out/native-path"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1
mkdir "$out/runs"
cd "$out/runtime"
overall=0
for group in 0 3;do
    pids=()
    for offset in 0 1 2;do
        worker=$((group+offset))
        (
            trap 'status=$?; printf "%s\n" "$status" > "$out/worker-'"$worker"'.exit"' EXIT
            printf '%s\n' "$BASHPID" > "$out/worker-$worker.pid"
            ./build/flex/control/control correct --policy "$out/student" --output "$out/runs/$worker" --scene-catalog "$out/catalog/$worker" --episodes 5 --validation 1 --rollin 120 --rollin-min 120 --label-rollin --return-via-home --approach-side 1 --horizon 354 --seed "$((9740000+worker*1000))" > "$out/worker-$worker.log" 2>&1
            ./build/flex/control/control pack-data --data "$out/runs/$worker/data.bin" --output "$out/packed-$worker" > "$out/packed-$worker.log" 2>&1
            ./build/flex/control/control verify-data --run "$out/runs/$worker" --data "$out/packed-$worker/data.bin" --output "$out/verified-$worker" > "$out/verified-$worker.log" 2>&1
            /usr/bin/jq -e '.passed and .episodes==5 and .datasetEpisodes==5 and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .executedCommandsMatchRecordings and .denseOracleLabels and .preActionAlignmentChecked and .taskEventHintAbsent' "$out/verified-$worker/result.json" >/dev/null
            for episode in {0..4};do
                /usr/bin/jq -e --argjson seed "$((9740000+worker*1000+episode))" '.success and .maximumBrickDistanceM==0.35 and .seed==$seed' "$out/runs/$worker/expert-$episode/result.json" >/dev/null
                for file in case.json environment.bin;do /usr/bin/cmp "$out/catalog/$worker/$episode/$file" "$out/runs/$worker/expert-$episode/scene/$file";done
            done
            "$out/diagnose" "$out/packed-$worker/data.bin" "$out/diagnostic-$worker.json"
        ) & pids+=("$!")
    done
    for pid in "${pids[@]}";do if ! wait "$pid";then overall=1;fi;done
done
cd "$project"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
(( overall==0 )) || { echo 'At least one trip or audit failed; all partial artifacts retained and nothing admitted.';exit 1; }
/usr/bin/jq -s '{fittingLaterDisagreements:([.[].windows[]|select(.fit and .firstAction==60)|.oracleDisagreements]|add),fittingHistoriesWith20LaterDisagreements:([.[].windows[]|select(.fit and .firstAction==60 and .oracleDisagreements>=20)]|length),sources:.}' "$out/diagnostic-"{0,1,2,3,4,5}.json > "$out/state-coverage.json"
echo 'Thirty teacher-recovery trips and native audits completed; dataset admission remains separate.'
