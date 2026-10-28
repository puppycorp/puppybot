#!/usr/bin/env bash
set -euo pipefail

project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$project/build/flex/sim/expanded-rooms-v1"
out="$root/contact-cohort-v1"
pilot="$root/correction-rollin-pilot-v1"
long_pilot="$root/correction-contact-pilot-v1"
[[ ! -e "$out/run.exit" && ! -e "$out/runs" ]]
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
printf '%s\n' "$BASHPID" > "$out/run.pid"
cd "$project"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
[[ "$(< "$pilot/run.exit")" == 0 && "$(< "$long_pilot/run.exit")" == 0 ]]
/usr/bin/jq -e '.passed and .studentRollinMaxAbsError==0 and .denseOracleLabels and .taskEventHintAbsent' "$pilot/verified/result.json" > /dev/null
/usr/bin/jq -e '.passed and .studentRollinMaxAbsError==0 and .denseOracleLabels and .taskEventHintAbsent' "$long_pilot/verified/result.json" > /dev/null
/usr/bin/jq -e '.passed and (.records|length)==16 and ([.records[]|select(.fit)]|length)==12 and ([.records[]|select(.fit|not)]|length)==4 and .reservedFinalLayoutsExcluded' "$out/catalog/report.json" > /dev/null
sha="$(/usr/bin/sha256sum "$out/student/weights.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$sha" '.weightsSHA256==$sha and (.taskFeedback|not)' "$out/student/receipt.json" > /dev/null
export PATH="$out/native-path"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1
export PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
mkdir "$out/runs"
cd "$out/runtime"
overall=0
for worker in {0..3};do
    (
        trap 'status=$?; printf "%s\n" "$status" > "$out/worker-'"$worker"'.exit"' EXIT
        printf '%s\n' "$BASHPID" > "$out/worker-$worker.pid"
        ./build/flex/control/control correct --policy "$out/student" --output "$out/runs/$worker" --scene-catalog "$out/catalog/$worker" --episodes 4 --validation 1 --rollin 120 --rollin-min 120 --label-rollin --return-via-home --approach-side 1 --horizon 354 --seed "$((9780000+worker*1000))" > "$out/worker-$worker.log" 2>&1
        ./build/flex/control/control pack-data --data "$out/runs/$worker/data.bin" --output "$out/packed-$worker" > "$out/packed-$worker.log" 2>&1
        ./build/flex/control/control verify-data --run "$out/runs/$worker" --data "$out/packed-$worker/data.bin" --output "$out/verified-$worker" > "$out/verified-$worker.log" 2>&1
        /usr/bin/jq -e '.passed and .episodes==4 and .datasetEpisodes==4 and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .executedCommandsMatchRecordings and .denseOracleLabels and .preActionAlignmentChecked and .taskEventHintAbsent' "$out/verified-$worker/result.json" > /dev/null
        for episode in {0..3};do
            run="$out/runs/$worker/expert-$episode"
            /usr/bin/jq -e --argjson seed "$((9780000+worker*1000+episode))" '.success and .maximumBrickDistanceM==0.35 and .seed==$seed' "$run/result.json" > /dev/null
            /usr/bin/jq -e --arg sha "$sha" '.studentWeightsSHA256==$sha and .denseOracleLabels and .studentStartAction==0 and .scheduledRollinActions==120' "$run/supervision.json" > /dev/null
            for file in case.json environment.bin;do /usr/bin/cmp "$out/catalog/$worker/$episode/$file" "$run/scene/$file";done
        done
        "$out/diagnose" "$out/packed-$worker/data.bin" "$out/diagnostic-$worker.json"
    ) &
    pid=$!
    if ! wait "$pid";then overall=1;fi
done
cd "$project"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
(( overall==0 )) || { echo 'At least one collection or audit failed; partial artifacts retained and nothing admitted.' >&2;exit 1; }
echo 'Sixteen student-roll-in trips and independent audits completed; dataset admission remains separate.'
