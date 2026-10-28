#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]];mkdir "$out"
fixture="$out/comparison";mkdir "$fixture"
printf '{"complete":true,"episodes":2,"identicalSearchPrefixes":true,"teacherAssisted":true,"autonomousWholeEpisodeSuccessClaimed":false}\n' > "$fixture/comparison.json"
for kind in reference forward;do for index in 0 1;do
    mkdir -p "$fixture/$kind/runs/expert-$index"
    cat > "$fixture/$kind/runs/expert-$index/decisions.jsonl" <<'EOF'
{"state":{"findReturn":{"phase":"search"},"case":{"dockVision":{"valid":true,"attention":{"fresh":true}}}}}
{"state":{"findReturn":{"phase":"return"},"case":{"dockVision":{"valid":false,"visibleCorners":4,"attention":{"fresh":false}}}}}
{"state":{"findReturn":{"phase":"return"},"case":{"dockVision":{"valid":true,"attention":{"fresh":true}}}}}
EOF
done;done
driver="$project/datasets/visual-control/expanded-rooms-v1/summarize-return-box-visibility.sh"
bash "$driver" "$fixture" "$out/good" > /dev/null
jq -e '.passed and .detectorIsEvaluationOnly and .actorRecognitionNotMeasured and .staleMarkerCountsIgnored and (.rows|length)==4 and all(.rows[]; .postDetectionDecisions==2 and .validBoxObservations==1 and .freshBoxAttention==1)' "$out/good/summary.json" > /dev/null
jq '.identicalSearchPrefixes=false' "$fixture/comparison.json" > "$out/bad-receipt";cp "$out/bad-receipt" "$fixture/comparison.json"
if bash "$driver" "$fixture" "$out/bad" > "$out/bad.log" 2>&1;then echo 'Visibility summary accepted unmatched prefixes.' >&2;exit 1;fi
[[ ! -e "$out/bad/summary.json" ]]
echo 'Return box-visibility summary excludes search and stale markers.'
