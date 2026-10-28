#!/usr/bin/env bash
set -euo pipefail

project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$project/build/flex/sim/expanded-rooms-v1"
out="$root/return-pilot-v1"
quick="$root/contact-quick-v1"
reference="$root/unseen-benchmark-v2"
[[ ! -e "$out/run.exit" && ! -e "$out/runs" ]]
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
printf '%s\n' "$BASHPID" > "$out/run.pid"
cd "$project"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
[[ "$(< "$quick/run.exit")" == 0 && "$(< "$out/catalog/run.exit")" == 0 ]]
/usr/bin/jq -e '.exploratory and .allEpisodeAuditsPassed and (.qualifiesForPromotion|not) and .continued.auditedApproaches==1 and .continued.physicalReturns==0' "$quick/comparison.json" > /dev/null
/usr/bin/jq -e '.passed and .records[0].fit and (.records[1].fit|not) and .reservedFinalLayoutsExcluded and .validationEnvironmentExcludedFromFitting' "$out/catalog/report.json" > /dev/null
/usr/bin/cmp "$out/runtime/build/flex/control/simulator" "$reference/runtime/build/flex/control/simulator"
sha="$(/usr/bin/sha256sum "$out/student/weights.bin" | /usr/bin/cut -d' ' -f1)"
[[ "$sha" == "$(/usr/bin/sha256sum "$quick/model/weights.bin" | /usr/bin/cut -d' ' -f1)" ]]
/usr/bin/jq -e --arg sha "$sha" '.weightsSHA256==$sha and (.taskFeedback|not)' "$out/student/receipt.json" > /dev/null
export PATH="$out/native-path"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1
export PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
cd "$out/runtime"
./build/flex/control/control correct --policy "$out/student" --output "$out/runs" --scene-catalog "$out/catalog" --episodes 2 --validation 1 --rollin 90 --rollin-min 90 --label-rollin --return-rollin --return-via-home --approach-side 1 --horizon 354 --seed 9790000 > "$out/collection.log" 2>&1
./build/flex/control/control pack-data --data "$out/runs/data.bin" --output "$out/packed" > "$out/packed.log" 2>&1
./build/flex/control/control verify-data --run "$out/runs" --data "$out/packed/data.bin" --output "$out/verified" > "$out/verified.log" 2>&1
data_sha="$(/usr/bin/sha256sum "$out/packed/data.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$data_sha" '.passed and .episodes==2 and .datasetEpisodes==2 and .dataSHA256==$sha and .studentRollinCommandsReplayed>=2 and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .executedCommandsMatchRecordings and .denseOracleLabels and .preActionAlignmentChecked and .zeroPaddingChecked and .taskEventHintAbsent' "$out/verified/result.json" > /dev/null
student=0
for episode in 0 1;do
    run="$out/runs/expert-$episode"
    /usr/bin/jq -e --argjson seed "$((9790000+episode))" '.success and .maximumBrickDistanceM==0.35 and .seed==$seed' "$run/result.json" > /dev/null
    /usr/bin/jq -e --arg sha "$sha" '.studentWeightsSHA256==$sha and .denseOracleLabels and .studentBeginsAfterConsumption and .studentStartAction>0 and .scheduledRollinActions==90 and .studentActions>=1 and .studentActions<=90' "$run/supervision.json" > /dev/null
    student=$((student+$(/usr/bin/jq '.studentActions' "$run/supervision.json")))
    for file in case.json environment.bin;do /usr/bin/cmp "$out/catalog/$episode/$file" "$run/scene/$file";done
done
/usr/bin/jq -e --argjson student "$student" '.studentRollinCommandsReplayed==$student' "$out/verified/result.json" > /dev/null
cd "$project"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
echo 'Two teacher-approach student-return histories and full replay audits completed; dataset admission is separate.'
