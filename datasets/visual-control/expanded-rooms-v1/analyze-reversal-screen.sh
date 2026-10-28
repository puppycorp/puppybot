#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
base="$project/build/flex/sim/expanded-rooms-v1"
root="$base/large-model-v1"
screen="$root/reversal-screen-v1"
source="$root/source/reversal-screen-analysis-v1/diagnose-return-progress.sh"
out="$root/reversal-screen-analysis-v1"
[[ ! -e "$out" ]]
/usr/bin/mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
while [[ ! -f "$screen/run.exit" ]]; do
    [[ -f "$screen/run.pid" ]] && kill -0 "$(< "$screen/run.pid")" || { echo 'Screen ended without a status.' >&2; exit 1; }
    /usr/bin/sleep 20
done
[[ "$(< "$screen/run.exit")" == 0 ]]
/usr/bin/jq -e '.exploratory and .episodesPerModel==4 and .optimizerStepsPerModel==98 and (.independentFinalHoldout|not) and (.automaticPromotion|not)' "$screen/comparison.json" > /dev/null
/usr/bin/sha256sum "$source" "$screen/comparison.json" "$screen/plain-policy/receipt.json" "$screen/penalty-policy/receipt.json" > "$out/inputs.sha256"
for index in 2 15 16 17; do
    layout=$((18+index/16)); scene=$((index%16)); seed=$((9960000+index))
    for arm in plain penalty; do
        episode="$screen/$arm-screen/$index/$seed"; audit="$screen/$arm-screen/$index/verified/result.json"
        /usr/bin/cmp "$episode/scene/case.json" "$base/unseen-benchmark-v2/scenes/$layout/$scene/case.json"
        /usr/bin/cmp "$episode/scene/environment.bin" "$base/unseen-benchmark-v2/scenes/$layout/$scene/environment.bin"
        /usr/bin/sha256sum "$episode/initial.json" "$episode/result.json" "$episode/decisions.jsonl" "$audit" >> "$out/inputs.sha256"
        /usr/bin/bash "$source" "$episode" "$audit" "$out/$arm-$index.json"
    done
    /usr/bin/jq -n --argjson index "$index" --argjson layout "$layout" --slurpfile plain "$out/plain-$index.json" --slurpfile penalty "$out/penalty-$index.json" '{caseIndex:$index,layoutId:$layout,baseline:$plain[0],regularized:$penalty[0]}' > "$out/pair-$index.json"
done
/usr/bin/jq -s 'sort_by(.caseIndex) | {exploratory:true,cases:length,commonApproaches:map(select(.baseline.approachedBrick and .regularized.approachedBrick))|length,baselineApproaches:map(select(.baseline.approachedBrick))|length,regularizedApproaches:map(select(.regularized.approachedBrick))|length,baselineReturns:map(select(.baseline.returned))|length,regularizedReturns:map(select(.regularized.returned))|length,decisionFrameDistancesOnly:true,independentFinalHoldout:false,automaticPromotion:false,rows:.}' "$out"/pair-*.json > "$out/comparison.json"
/usr/bin/jq -e '.cases==4 and (.rows|length)==4 and .exploratory and (.independentFinalHoldout|not) and (.automaticPromotion|not)' "$out/comparison.json" > /dev/null
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
