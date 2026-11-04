#!/usr/bin/env bash
set -euo pipefail
project="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$project"
out="${1:?New output directory required}"
mkdir "$out"
mkdir "$out/run"
jq -n '{totalSteps:0,findReturn:{phase:"search"}}' > "$out/run/initial.json"
jq -n '{found:true,success:false,policyWeightsSHA256:"test"}' > "$out/run/result.json"
jq -n '{passed:true,commandReplayMaxAbsError:0,returnPoseChecked:true,taskEventHintAbsent:true,weightsSHA256:"test"}' > "$out/audit.json"
jq -nc 'def row($s;$p;$a;$x;$blocked): {sequence:$s,step:($s*10),action:[0,$a],state:{pose:[$x,0,0],blocked:$blocked,findReturn:{phase:$p,stableReturnObservations:0},case:{container:{position:[0,0,0]}}}}; row(1;"search";1;3;false),row(2;"return";0;2;true),row(3;"return";-1;1;false),row(4;"return";1;2;false)' > "$out/run/decisions.jsonl"
bash datasets/visual-control/expanded-rooms-v1/diagnose-return-progress.sh "$out/run" "$out/audit.json" "$out/result.json"
jq -e '.passed and .approachedBrick and (.returned|not) and .returnDecisionFrames==3 and .postTransitionActions==2 and .timeToBrickActionSeconds==0.4 and .firstBoxDistanceM==2 and .closestBoxDistanceM==1 and .lastBoxDistanceM==2 and .forwardActions==1 and .reverseActions==1 and .driveDirectionReversals==1 and .stopActions==0 and .blockedStates==0 and .transitionActionExcluded' "$out/result.json" > /dev/null
cp "$out/run/decisions.jsonl" "$out/good.jsonl"
jq -c 'if .sequence==4 then .state.findReturn.phase="search" else . end' "$out/good.jsonl" > "$out/run/decisions.jsonl"
if bash datasets/visual-control/expanded-rooms-v1/diagnose-return-progress.sh "$out/run" "$out/audit.json" "$out/rejected.json" > "$out/rejected.log" 2>&1; then echo 'Return phase regression was accepted.' >&2; exit 1; fi
[[ ! -e "$out/rejected.json" ]]
echo 'Return diagnostic checks action alignment and rejects inconsistent traces.'
