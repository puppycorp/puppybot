#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$project/build/flex/sim/expanded-rooms-v1/large-model-v1"
arm="${1:?small or large is required}"
[[ "$arm" == small || "$arm" == large ]]
score="$root/score-$arm.json"
out="$root/distance-$arm"
[[ ! -e "$out" ]]
/usr/bin/jq -e '.episodes==32 and .completedRecordings==32 and .auditedEpisodes==32' "$score" > /dev/null
/usr/bin/mkdir "$out"
for ((index=0;index<32;index++)); do
    seed=$((9960000+index))
    "$root/runtime/measure-brick-distance" "$root/benchmark/$arm/$index/$seed" "$out/$index" > "$out/$index.log"
    /usr/bin/jq --argjson index "$index" '.+{caseIndex:$index}' "$out/$index/result.json" > "$out/$index-row.json"
done
/usr/bin/jq -s --arg arm "$arm" '{arm:$arm,evaluationOnly:true,distancesMeasuredAtDecisionFrames:true,episodes:length,meanClosestM:(map(.closestPlanarBaseToBrickM)|add/length),medianClosestM:(map(.closestPlanarBaseToBrickM)|sort|((.[15]+.[16])/2)),minimumClosestM:(map(.closestPlanarBaseToBrickM)|min),rows:sort_by(.caseIndex)}' "$out/"*-row.json > "$out/summary.json"
/usr/bin/jq -e '.episodes==32' "$out/summary.json" > /dev/null
