#!/usr/bin/env bash
set -euo pipefail

project="${PUPPYBOT_PROJECT:?Project root is required}"
suite="$project/build/flex/sim/expanded-rooms-v1/unseen-benchmark-v2"
probe="$project/build/flex/sim/late-search-v1/phase-probe"
out="${1:?New output directory is required}"
[[ ! -e "$out" ]]
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
export PATH="$suite/native-path"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1
for item in baseline:0 baseline:1 baseline:16 student:16;do
    arm=${item%:*};index=${item#*:};episode="$suite/$arm/$index/$((9960000+index))"
    /usr/bin/jq -e '.auditPassed and .recordingCompleted and (.found|not)' "$suite/$arm/$index/benchmark-row.json" > /dev/null
    "$probe" "$suite/$arm/$index/policy" "$episode" "$out/$arm-$index" > "$out/$arm-$index.log" 2>&1
    /usr/bin/jq -e '.actualCommandsReplayedExactly and .phaseHeadReadOnly and (.rows|length)==300 and all(.rows[]; (.actualReturning|not))' "$out/$arm-$index/result.json" > /dev/null
    /usr/bin/jq --arg name "$item" '{sample:$name,frames:(.rows|length),allActualSearch:(all(.rows[]; (.actualReturning|not))),meanPredictedReturnProbability:([.rows[].predictedReturnProbability]|add/length),firstProbability:.rows[0].predictedReturnProbability,lastProbability:.rows[-1].predictedReturnProbability,firstAboveHalf:([.rows[]|select(.predictedReturnProbability>0.5)|.actionIndex]|first),aboveHalf:([.rows[]|select(.predictedReturnProbability>0.5)]|length),stopActions:([.rows[]|select(.actionClass==6)]|length),replayExact:.actualCommandsReplayedExactly}' "$out/$arm-$index/result.json" > "$out/$arm-$index-summary.json"
done
/usr/bin/jq -s '.' "$out/"*-summary.json > "$out/summary.json"
echo 'Recorded policies replayed exactly; phase readouts are diagnostic, not causal evidence.'
