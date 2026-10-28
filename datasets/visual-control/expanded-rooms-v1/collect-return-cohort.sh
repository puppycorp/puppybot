#!/usr/bin/env bash
set -euo pipefail

project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$project/build/flex/sim/expanded-rooms-v1"
out="$root/return-cohort-v1"
pilot="$root/return-pilot-v1"
[[ ! -e "$out/run.exit" && ! -e "$out/runs" ]]
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
printf '%s\n' "$BASHPID" > "$out/run.pid"
cd "$project"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
[[ "$(< "$pilot/run.exit")" == 0 && "$(< "$out/catalog/run.exit")" == 0 ]]
pilot_sha="$(/usr/bin/sha256sum "$pilot/packed/data.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$pilot_sha" '.passed and .episodes==2 and .dataSHA256==$sha and .studentRollinCommandsReplayed==180 and .studentRollinMaxAbsError==0 and .denseOracleLabels and .datasetInputsMatchActualRGBAndOwnFeedback and .taskEventHintAbsent' "$pilot/verified/result.json" > /dev/null
/usr/bin/jq -e '.passed and (.records|length)==12 and .reservedFinalLayoutsExcluded and .validationEnvironmentExcludedFromFitting' "$out/catalog/report.json" > /dev/null
sha="$(/usr/bin/sha256sum "$out/student/weights.bin" | /usr/bin/cut -d' ' -f1)"
[[ "$sha" == "$(/usr/bin/sha256sum "$pilot/student/weights.bin" | /usr/bin/cut -d' ' -f1)" ]]
/usr/bin/jq -e --arg sha "$sha" '.weightsSHA256==$sha and (.taskFeedback|not)' "$out/student/receipt.json" > /dev/null
export PATH="$out/native-path"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1
export PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
mkdir "$out/runs"
cd "$out/runtime"
overall=0
for worker in {0..5};do
    (
        trap 'status=$?; printf "%s\n" "$status" > "$out/worker-'"$worker"'.exit"' EXIT
        printf '%s\n' "$BASHPID" > "$out/worker-$worker.pid"
        ./build/flex/control/control correct --policy "$out/student" --output "$out/runs/$worker" --scene-catalog "$out/catalog/$worker" --episodes 2 --validation 1 --rollin 90 --rollin-min 90 --label-rollin --return-rollin --return-via-home --approach-side 1 --horizon 354 --seed "$((9800000+worker*1000))" > "$out/worker-$worker.log" 2>&1
        ./build/flex/control/control pack-data --data "$out/runs/$worker/data.bin" --output "$out/packed-$worker" > "$out/packed-$worker.log" 2>&1
        ./build/flex/control/control verify-data --run "$out/runs/$worker" --data "$out/packed-$worker/data.bin" --output "$out/verified-$worker" > "$out/verified-$worker.log" 2>&1
        data_sha="$(/usr/bin/sha256sum "$out/packed-$worker/data.bin" | /usr/bin/cut -d' ' -f1)"
        /usr/bin/jq -e --arg sha "$data_sha" '.passed and .episodes==2 and .datasetEpisodes==2 and .dataSHA256==$sha and .studentRollinCommandsReplayed>=2 and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .executedCommandsMatchRecordings and .denseOracleLabels and .preActionAlignmentChecked and .zeroPaddingChecked and .taskEventHintAbsent' "$out/verified-$worker/result.json" > /dev/null
        student=0
        for episode in 0 1;do
            run="$out/runs/$worker/expert-$episode"
            /usr/bin/jq -e --argjson seed "$((9800000+worker*1000+episode))" '.success and .maximumBrickDistanceM==0.35 and .seed==$seed' "$run/result.json" > /dev/null
            /usr/bin/jq -e --arg sha "$sha" '.studentWeightsSHA256==$sha and .denseOracleLabels and .studentBeginsAfterConsumption and .studentStartAction>0 and .scheduledRollinActions==90 and .studentActions>=1 and .studentActions<=90' "$run/supervision.json" > /dev/null
            student=$((student+$(/usr/bin/jq '.studentActions' "$run/supervision.json")))
            for file in case.json environment.bin;do /usr/bin/cmp "$out/catalog/$worker/$episode/$file" "$run/scene/$file";done
        done
        /usr/bin/jq -e --argjson student "$student" '.studentRollinCommandsReplayed==$student' "$out/verified-$worker/result.json" > /dev/null
    ) &
    pid=$!
    if ! wait "$pid";then overall=1;fi
done
cd "$project"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
(( overall==0 )) || { echo 'At least one collection or audit failed; partial artifacts retained and nothing admitted.' >&2;exit 1; }
echo 'Twelve teacher-approach student-return trips and independent audits completed; dataset admission remains separate.'
