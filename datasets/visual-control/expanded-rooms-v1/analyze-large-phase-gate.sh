#!/usr/bin/env bash
# Replay recorded autonomous trajectories; simulator phase is used only for analysis.
set -euo pipefail
probe="${1:?Compiled large phase probe required}"
policy="${2:?Gated policy directory required}"
out="${3:?New output directory required}"
shift 3
(( $# > 0 ))
[[ ! -e "$out" ]]
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
sha="$(/usr/bin/sha256sum "$policy/weights.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/sha256sum "$probe" "$policy/weights.bin" "$policy/policy" "$policy/receipt.json" > "$out/inputs.sha256"
index=0
for episode in "$@"; do
    /usr/bin/sha256sum "$episode/initial.json" "$episode/decisions.jsonl" "$episode/../verified/result.json" >> "$out/inputs.sha256"
    find "$episode" -maxdepth 1 -type f \( -name 'actor-*.rgb' -o -name 'actor-*.feedback' \) -print0 | /usr/bin/sort -z | /usr/bin/xargs -0 -r /usr/bin/sha256sum >> "$out/inputs.sha256"
    "$probe" "$policy" "$episode" "$out/$index" > "$out/$index.log" 2>&1
    /usr/bin/jq -e --arg sha "$sha" '.weightsSHA256==$sha and .actualCommandsReplayedExactly and .actorUsesPhaseGate and .phaseProbeReadOnly and .simulatorPhaseUsedOnlyForAnalysis and (.rows|length)>0' "$out/$index/result.json" > /dev/null
    /usr/bin/jq --arg episode "$episode" '
        def stats: {frames:length, meanProbability:(if length>0 then (map(.predictedReturnProbability)|add/length) else null end), aboveHalf:(map(select(.predictedReturnProbability>0.5))|length)};
        {episode:$episode, frames:(.rows|length), search:([.rows[]|select(.actualReturning|not)]|stats), return:([.rows[]|select(.actualReturning)]|stats), firstActualReturn:([.rows[]|select(.actualReturning)|.actionIndex]|first), firstAboveHalf:([.rows[]|select(.predictedReturnProbability>0.5)|.actionIndex]|first), thresholdCrossings:([.rows[].predictedReturnProbability>0.5]|reduce .[] as $v ({prev:null,count:0}; if .prev!=null and .prev!=$v then .count+=1 else . end | .prev=$v)|.count), replayExact:.actualCommandsReplayedExactly}' "$out/$index/result.json" > "$out/$index-summary.json"
    index=$((index+1))
done
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
/usr/bin/jq -s --arg sha "$sha" '{weightsSHA256:$sha,episodes:length,rows:.,actorInputsUnchanged:true,phaseLabelsUsedOnlyForAnalysis:true,notCausalEvidence:true}' "$out/"*-summary.json > "$out/summary.json"
echo 'Gated policy replayed exactly; simulator phase was used only for analysis.'
