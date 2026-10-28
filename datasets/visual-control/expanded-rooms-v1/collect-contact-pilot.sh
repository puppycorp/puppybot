#!/usr/bin/env bash
set -euo pipefail

project="${PUPPYBOT_PROJECT:?Project root is required}"
base="$project/build/flex/sim/expanded-rooms-v1"
probe="$base/correction-probe-v1"
reference="$base/unseen-benchmark-v2"
out="$base/correction-contact-pilot-v1"
prior="$base/correction-rollin-pilot-v1"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
printf '%s\n' "$BASHPID" > "$out/run.pid"
while [[ ! -f "$probe/screen.exit" ]];do
    [[ -f "$probe/screen.pid" ]] && kill -0 "$(< "$probe/screen.pid")" || { echo 'Exploratory screen disappeared without a status.';exit 1; }
    /usr/bin/sleep 10
done
[[ "$(< "$probe/screen.exit")" == 0 && "$(< "$probe/forward-epoch20.exit")" == 0 ]]
while [[ ! -f "$prior/run.exit" ]];do
    [[ -f "$prior/run.pid" ]] && kill -0 "$(< "$prior/run.pid")" || { echo 'Previous roll-in pilot disappeared without a status.';exit 1; }
    /usr/bin/sleep 10
done
cd "$project"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
/usr/bin/jq -e '.exploratory and .allEpisodeAuditsPassed and (.qualifiesForPromotion|not)' "$probe/screen-comparison.json" > /dev/null
/usr/bin/cmp "$probe/model/epoch-20.bin" "$probe/policy-20/weights.bin"
/usr/bin/cmp "$out/runtime/build/flex/control/simulator" "$reference/runtime/build/flex/control/simulator"
sha="$(/usr/bin/sha256sum "$probe/policy-20/weights.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$sha" '.weightsSHA256==$sha and (.taskFeedback|not)' "$probe/policy-20/receipt.json" > /dev/null
export PATH="$out/native-path"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1
export PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
cd "$out/runtime"
./build/flex/control/control correct --policy "$probe/policy-20" --output "$out/runs" --scene-catalog "$out/catalog" --episodes 2 --validation 1 --rollin 150 --rollin-min 150 --label-rollin --return-via-home --approach-side 1 --horizon 354 --seed 9760000 > "$out/collection.log" 2>&1
./build/flex/control/control pack-data --data "$out/runs/data.bin" --output "$out/packed" > "$out/packed.log" 2>&1
./build/flex/control/control verify-data --run "$out/runs" --data "$out/packed/data.bin" --output "$out/verified" > "$out/verified.log" 2>&1
/usr/bin/jq -e '.passed and .episodes==2 and .datasetEpisodes==2 and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .executedCommandsMatchRecordings and .denseOracleLabels and .preActionAlignmentChecked and .taskEventHintAbsent' "$out/verified/result.json" > /dev/null
for episode in 0 1;do
    /usr/bin/jq -e --argjson seed "$((9760000+episode))" '.success and .maximumBrickDistanceM==0.35 and .seed==$seed' "$out/runs/expert-$episode/result.json" > /dev/null
    /usr/bin/jq -e --arg sha "$sha" '.studentWeightsSHA256==$sha and .denseOracleLabels and .studentStartAction==0 and .scheduledRollinActions==150' "$out/runs/expert-$episode/supervision.json" > /dev/null
    for file in case.json environment.bin;do /usr/bin/cmp "$out/catalog/$episode/$file" "$out/runs/expert-$episode/scene/$file";done
done
"$out/diagnose" "$out/packed/data.bin" "$out/diagnostic.json"
cd "$project"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
echo 'Two longer exploratory contact roll-ins and independent data audits completed; no dataset was admitted.'
