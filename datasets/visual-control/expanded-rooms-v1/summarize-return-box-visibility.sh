#!/usr/bin/env bash
# Evaluate recorded simulator detector outputs; do not use them as actor input.
set -euo pipefail
comparison="${1:?Teacher comparison directory required}"
out="${2:?New output directory required}"
[[ ! -e "$out" ]];mkdir "$out"
jq -e '.complete and .episodes==2 and .identicalSearchPrefixes and .teacherAssisted and (.autonomousWholeEpisodeSuccessClaimed|not)' "$comparison/comparison.json" > /dev/null
sha256sum "$comparison/comparison.json" > "$out/inputs.sha256"
for kind in reference forward;do
    for index in 0 1;do
        path="$comparison/$kind/runs/expert-$index/decisions.jsonl"
        sha256sum "$path" >> "$out/inputs.sha256"
        jq -s -e 'length>0 and all(.[]; (.state.findReturn.phase=="search" or .state.findReturn.phase=="return" or .state.findReturn.phase=="docked") and (.state.case.dockVision.valid|type)=="boolean" and (.state.case.dockVision.attention.fresh|type)=="boolean")' "$path" > /dev/null
        jq -s --arg kind "$kind" --argjson index "$index" '
            [.[]|select(.state.findReturn.phase=="return")] as $rows |
            {teacher:$kind,index:$index,postDetectionDecisions:($rows|length),
             validBoxObservations:([$rows[]|select(.state.case.dockVision.valid==true)]|length),
             freshBoxAttention:([$rows[]|select(.state.case.dockVision.attention.fresh==true)]|length)}' "$path" > "$out/$kind-$index.json"
    done
done
sha256sum -c "$out/inputs.sha256" > "$out/integrity.log"
jq -s '{passed:true,detectorIsEvaluationOnly:true,actorRecognitionNotMeasured:true,staleMarkerCountsIgnored:true,rows:.}' "$out/"{reference,forward}-{0,1}.json > "$out/summary.json"
echo 'Summarized fresh simulator box detections during teacher return.'
