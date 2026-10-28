#!/usr/bin/env bash
# Offline sensitivity to neutralized drive feedback on recorded states.
set -euo pipefail
probe="${1:?Compiled feedback probe required}";policy="${2:?Large policy required}";out="${3:?New output directory required}";shift 3;(( $# > 0 ))
[[ ! -e "$out" ]];mkdir "$out";trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
sha="$(sha256sum "$policy/weights.bin" | cut -d' ' -f1)"
sha256sum "$probe" "$policy/weights.bin" "$policy/policy" "$policy/receipt.json" > "$out/inputs.sha256"
find "$policy/kernels" -type f -print0 | sort -z | xargs -0 -r sha256sum >> "$out/inputs.sha256"
index=0
for episode in "$@";do
    sha256sum "$episode/initial.json" "$episode/decisions.jsonl" "$episode/../verified/result.json" >> "$out/inputs.sha256"
    find "$episode" -maxdepth 1 -type f \( -name 'actor-*.rgb' -o -name 'actor-*.feedback' \) -print0 | sort -z | xargs -0 -r sha256sum >> "$out/inputs.sha256"
    "$probe" "$policy" "$episode" "$out/$index" > "$out/$index.log" 2>&1
    jq -e --arg sha "$sha" '.weightsSHA256==$sha and .actualCommandsReplayedExactly and .counterfactualDidNotAlterServerState and .neutralFeedbackHypothetical and .offlineCounterfactualOnly and .simulatorPhaseUsedOnlyForAnalysis' "$out/$index/result.json" > /dev/null
    jq --arg episode "$episode" '
        def direction: if .<3 then 1 elif .<6 then -1 else 0 end;
        def reversals($field): reduce .[] as $r ({previous:null,count:0}; ($r[$field]|direction) as $current | if .previous!=null and .previous!=0 and $current!=0 and .previous!=$current then .count+=1 else . end | .previous=$current) | .count;
        [.rows[]|select(.actualReturning)] as $return |
        {episode:$episode,frames:(.rows|length),returnFrames:($return|length),neutralFeedbackActionChanges:($return|map(select(.neutralFeedbackChangesAction))|length),actualDriveReversals:($return|reversals("actualClass")),neutralFeedbackDriveReversals:($return|reversals("neutralFeedbackClass")),exactReplay:.actualCommandsReplayedExactly}' "$out/$index/result.json" > "$out/$index-summary.json"
    index=$((index+1))
done
sha256sum -c "$out/inputs.sha256" > "$out/integrity.log"
jq -s --arg sha "$sha" '{passed:true,weightsSHA256:$sha,episodes:length,returnFrames:([.[].returnFrames]|add),neutralFeedbackActionChanges:([.[].neutralFeedbackActionChanges]|add),actualDriveReversals:([.[].actualDriveReversals]|add),neutralFeedbackDriveReversals:([.[].neutralFeedbackDriveReversals]|add),offlineCounterfactualOnly:true,neutralFeedbackHypothetical:true,closedLoopBehaviorNotMeasured:true,simulatorPhaseUsedOnlyForAnalysis:true,rows:.}' "$out/"*-summary.json > "$out/summary.json"
echo 'Offline feedback counterfactuals replayed without changing policy server state.'
