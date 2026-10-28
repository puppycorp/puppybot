#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$project/build/flex/sim/expanded-rooms-v1/large-model-v1"
arm="${1:?expanded or mirrored is required}"
[[ "$arm" == expanded || "$arm" == mirrored ]]
score="$root/score-236-$arm.json"
out="$root/expanded-distance-$arm"
[[ ! -e "$out" ]]
while ! /usr/bin/jq -e '.episodes==32 and .completedRecordings==32 and .auditedEpisodes==32' "$score" > /dev/null 2>&1; do
    if [[ -f "$root/expanded-benchmark.exit" ]]; then echo 'Benchmark ended without a fully audited score.' >&2; exit 1; fi
    [[ -f "$root/expanded-benchmark.pid" ]] && kill -0 "$(< "$root/expanded-benchmark.pid")" || { echo 'Benchmark ended without a status.' >&2; exit 1; }
    /usr/bin/sleep 20
done
/usr/bin/mkdir "$out"
for ((index=0;index<32;index++)); do
    seed=$((9960000+index))
    "$root/runtime/measure-brick-distance" "$root/expanded-benchmark/$arm/$index/$seed" "$out/$index" > "$out/$index.log"
    /usr/bin/jq --argjson index "$index" '.+{caseIndex:$index}' "$out/$index/result.json" > "$out/$index-row.json"
done
/usr/bin/jq -s --arg arm "$arm" '{arm:$arm,evaluationOnly:true,distancesMeasuredAtDecisionFrames:true,episodes:length,meanClosestM:(map(.closestPlanarBaseToBrickM)|add/length),medianClosestM:(map(.closestPlanarBaseToBrickM)|sort|((.[15]+.[16])/2)),minimumClosestM:(map(.closestPlanarBaseToBrickM)|min),rows:sort_by(.caseIndex)}' "$out/"*-row.json > "$out/summary.json"
/usr/bin/jq -e '.episodes==32' "$out/summary.json" > /dev/null
