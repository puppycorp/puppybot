#!/usr/bin/env bash
set -euo pipefail

run="${1:?Episode directory required}"
audit="${2:?Independent audit result required}"
output="${3:?New report path required}"
[[ ! -e "$output" ]]
/usr/bin/jq -e '.passed and .commandReplayMaxAbsError==0 and .returnPoseChecked and .taskEventHintAbsent' "$audit" > /dev/null
/usr/bin/jq -e '.found==true or .found==false' "$run/result.json" > /dev/null
temporary="$(/usr/bin/mktemp "${output}.tmp.XXXXXXXX")"
trap 'rm -f "$temporary"' EXIT
/usr/bin/jq -s --slurpfile initial "$run/initial.json" --slurpfile result "$run/result.json" --slurpfile audit "$audit" '
    def distance: (.state.pose[0]-.state.case.container.position[0]) as $x |
        (.state.pose[1]-.state.case.container.position[1]) as $y | ($x*$x+$y*$y)|sqrt;
    def phase: .state.findReturn.phase;
    . as $rows | $initial[0].findReturn.phase as $initialPhase |
    if ($rows|length)==0 or ($initialPhase!="search" and $initialPhase!="return") or
       (($initial[0].totalSteps|type)!="number") or ($rows[0].step<=$initial[0].totalSteps) or
       ($result[0].policyWeightsSHA256!=$audit[0].weightsSHA256) or
       (all($rows[]; (.action|length)==2 and (.state.pose|length)>=2 and
            (.state.case.container.position|length)>=2 and (phase=="search" or phase=="return"))|not) or
       (all(range(1;($rows|length)); . as $i |
            $rows[$i].step>$rows[$i-1].step and $rows[$i].sequence==$rows[$i-1].sequence+1 and
            (($rows[$i-1]|phase)!="return" or ($rows[$i]|phase)=="return"))|not) or
       ($initialPhase=="return" and ($rows[0]|phase)!="return")
    then error("inconsistent audited return trace") else . end |
    [$rows[]|select(phase=="return")] as $returns |
    (if $initialPhase=="search" then $returns[1:] else $returns end) as $after |
    if ($result[0].found != (($returns|length)>0 or $initialPhase=="return"))
    then error("brick outcome disagrees with trace") else . end |
    {passed:true,offlinePhysicalTraceOnly:true,actorInputsUnchanged:true,
     policyWeightsSHA256:$audit[0].weightsSHA256,approachedBrick:$result[0].found,returned:$result[0].success,
     returnDecisionFrames:($returns|length),postTransitionActions:($after|length),
     firstReturnStep:(if ($returns|length)>0 then $returns[0].step else null end),
     timeToBrickActionSeconds:(if $initialPhase=="search" and ($returns|length)>0 then (($returns[0].step-$initial[0].totalSteps)/50) else null end),
     firstBoxDistanceM:(if ($returns|length)>0 then ($returns[0]|distance) else null end),
     closestBoxDistanceM:(if ($returns|length)>0 then ($returns|map(distance)|min) else null end),
     lastBoxDistanceM:(if ($returns|length)>0 then ($returns[-1]|distance) else null end),
     forwardActions:($after|map(select(.action[1]>0))|length),reverseActions:($after|map(select(.action[1]<0))|length),
     driveDirectionReversals:($after|map(select(.action[1]!=0)|if .action[1]>0 then 1 else -1 end) |
        reduce .[] as $direction ({previous:null,count:0}; if .previous!=null and .previous!=$direction then .count+=1 else . end | .previous=$direction) | .count),
     stopActions:($after|map(select(.action[1]==0))|length),blockedStates:($after|map(select(.state.blocked))|length),
     stableDockObservations:($returns|map(select(.state.findReturn.stableReturnObservations>0))|length),
     decisionFrameDistancesOnly:true,transitionActionExcluded:($initialPhase=="search" and ($returns|length)>0)}
' "$run/decisions.jsonl" > "$temporary"
/usr/bin/mv "$temporary" "$output"
trap - EXIT
