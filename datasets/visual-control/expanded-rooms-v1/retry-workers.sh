#!/usr/bin/env bash
set -euo pipefail

project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$project/build/flex/sim/expanded-rooms-v1"
original="$root/cohort-v1"
out="$root/cohort-retry-v1"
[[ -f "$original/run.exit" && "$(< "$original/run.exit")" != 0 ]]
[[ "$(< "$project/build/flex/sim/target-detach-v1/train.exit")" == 0 ]]
[[ ! -e "$out/run.exit" && ! -e "$out/runs" ]]
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
printf '%s\n' "$BASHPID" > "$out/run.pid"
cd "$project"
/usr/bin/sha256sum -c "$original/inputs.sha256" > "$out/integrity-before.log"
export PATH="$original/native-path"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1
mkdir "$out/runs"
cd "$original/runtime"
overall=0
for worker in {0..5};do
    [[ -f "$original/worker-$worker.exit" ]]
    [[ "$(< "$original/worker-$worker.exit")" != 0 ]] || continue
    (
        trap 'status=$?; printf "%s\n" "$status" > "$out/worker-'"$worker"'.exit"' EXIT
        printf '%s\n' "$BASHPID" > "$out/worker-$worker.pid"
        ./build/flex/control/control correct --policy "$original/student" --output "$out/runs/$worker" --scene-catalog "$original/catalog/$worker" --episodes 5 --validation 1 --rollin 120 --rollin-min 120 --label-rollin --return-via-home --approach-side 1 --horizon 354 --seed "$((9740000+worker*1000))" > "$out/worker-$worker.log" 2>&1
        ./build/flex/control/control pack-data --data "$out/runs/$worker/data.bin" --output "$out/packed-$worker" > "$out/packed-$worker.log" 2>&1
        ./build/flex/control/control verify-data --run "$out/runs/$worker" --data "$out/packed-$worker/data.bin" --output "$out/verified-$worker" > "$out/verified-$worker.log" 2>&1
        /usr/bin/jq -e '.passed and .episodes==5 and .datasetEpisodes==5 and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .executedCommandsMatchRecordings and .denseOracleLabels and .preActionAlignmentChecked and .taskEventHintAbsent' "$out/verified-$worker/result.json" >/dev/null
        for episode in {0..4};do
            /usr/bin/jq -e --argjson seed "$((9740000+worker*1000+episode))" '.success and .maximumBrickDistanceM==0.35 and .seed==$seed' "$out/runs/$worker/expert-$episode/result.json" >/dev/null
            for file in case.json environment.bin;do /usr/bin/cmp "$original/catalog/$worker/$episode/$file" "$out/runs/$worker/expert-$episode/scene/$file";done
        done
        "$original/diagnose" "$out/packed-$worker/data.bin" "$out/diagnostic-$worker.json"
    ) &
    pid=$!
    if ! wait "$pid";then overall=1;fi
done
cd "$project"
/usr/bin/sha256sum -c "$original/inputs.sha256" > "$out/integrity-after.log"
(( overall==0 )) || { echo 'A retry or audit failed; all partial artifacts retained and nothing admitted.';exit 1; }
echo 'Failed collection workers retried sequentially and audited; dataset admission remains separate.'
