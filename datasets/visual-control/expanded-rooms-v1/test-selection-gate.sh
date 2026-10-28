#!/usr/bin/env bash
set -euo pipefail

project="${PUPPYBOT_PROJECT:?Project root is required}"
score="${1:?Audited 32-case score is required}"
policy="${2:?Scored policy directory is required}"
original="$(/usr/bin/dirname "$score")/$(/usr/bin/jq -r '.candidate' "$score")"
gate="$project/datasets/visual-control/expanded-rooms-v1/select-episode-candidate.sh"
fixture="$(/usr/bin/mktemp -d /tmp/puppy-selection-gate-XXXXXX)"
make_score() {
    local name="$1" count="$2"
    /usr/bin/jq --arg name "$name" --argjson count "$count" '.candidate=$name | .rows |= map(if .caseIndex<$count then .physicalReturned=true|.recordedPhysicalReturn=true|.found=true else .physicalReturned=false|.recordedPhysicalReturn=false end) | .physicalReturns=([.rows[]|select(.physicalReturned)]|length) | .openReturns=([.rows[]|select(.layoutId==18 and .physicalReturned)]|length) | .hiddenReturns=([.rows[]|select(.layoutId==19 and .physicalReturned)]|length) | .auditedApproaches=([.rows[]|select(.auditPassed and .found)]|length) | .meanSuccessfulSimulationSeconds=([.rows[]|select(.physicalReturned)|.simulationSeconds]|if length==0 then null else add/length end)' "$score" > "$fixture/score-$name.json"
    for i in {0..31};do
        local destination="$fixture/$name/$i"
        mkdir -p "$destination/verified" "$destination/$((9960000+i))"
        /usr/bin/jq --argjson i "$i" '.rows[]|select(.caseIndex==$i)' "$fixture/score-$name.json" > "$destination/benchmark-row.json"
        /usr/bin/cp "$original/$i/verified/result.json" "$destination/verified/result.json"
        /usr/bin/jq -c '{state:{case:{passed:.recordedPhysicalReturn}}}' "$destination/benchmark-row.json" > "$destination/$((9960000+i))/decisions.jsonl"
    done
}
make_score qualify 24
/usr/bin/bash "$gate" "$fixture/gate-qualify" "$fixture/score-qualify.json" "$policy" > /dev/null
/usr/bin/jq -e '.qualified and .selected.physicalReturns==24 and .selected.hiddenReturns==8' "$fixture/gate-qualify/selection.json" > /dev/null
make_score below 23
/usr/bin/bash "$gate" "$fixture/gate-below" "$fixture/score-below.json" "$policy" > /dev/null
/usr/bin/jq -e '.qualified|not' "$fixture/gate-below/selection.json" > /dev/null
/usr/bin/jq '.auditPassed=false' "$fixture/qualify/0/benchmark-row.json" > "$fixture/changed-row"
/usr/bin/mv "$fixture/changed-row" "$fixture/qualify/0/benchmark-row.json"
if /usr/bin/bash "$gate" "$fixture/gate-row" "$fixture/score-qualify.json" "$policy" > /dev/null 2>&1;then echo 'Changed episode row was accepted' >&2;exit 1;fi
/usr/bin/jq '.rows[]|select(.caseIndex==0)' "$fixture/score-qualify.json" > "$fixture/qualify/0/benchmark-row.json"
/usr/bin/jq '.passed=false' "$fixture/qualify/0/verified/result.json" > "$fixture/changed-audit"
/usr/bin/mv "$fixture/changed-audit" "$fixture/qualify/0/verified/result.json"
if /usr/bin/bash "$gate" "$fixture/gate-audit" "$fixture/score-qualify.json" "$policy" > /dev/null 2>&1;then echo 'Failed replay audit was accepted' >&2;exit 1;fi
mkdir "$fixture/policy"
/usr/bin/cp "$policy/weights.bin" "$policy/policy" "$fixture/policy/"
/usr/bin/jq '.taskFeedback=null' "$policy/receipt.json" > "$fixture/policy/receipt.json"
if /usr/bin/bash "$gate" "$fixture/gate-input" "$fixture/score-below.json" "$fixture/policy" > /dev/null 2>&1;then echo 'Missing task-input boundary was accepted' >&2;exit 1;fi
echo 'Qualification gate boundary and negative evidence fixtures passed.'
