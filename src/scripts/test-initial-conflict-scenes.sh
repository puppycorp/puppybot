#!/usr/bin/env bash
# Check provenance joins, scene summaries and rejection of changed observations.
set -euo pipefail
out="$(realpath -m "${1:?New output directory required}")"
[[ ! -e "$out" ]]
mkdir -p "$out/corpus"
for episode in 0 1; do
    run="$out/corpus/expert-$episode"; mkdir -p "$run/scene"
    dd if=/dev/zero of="$run/actor-7.rgb" bs=21168 count=1 status=none
    dd if=/dev/zero of="$run/actor-7.feedback" bs=28 count=1 status=none
    jq -n '{totalSteps:7,pose:[0,0,0],findReturn:{phase:"search"},environment:{name:"test"},case:{perception:{chosen:-1,detections:[]}}}' > "$run/initial.json"
    jq -n --argjson x "$episode" '{id:"test",objects:[{kind:"block",position:[$x,1,0]}]}' > "$run/scene/case.json"
done
input="$( { cat "$out/corpus/expert-0/actor-7.rgb"; head -c 20 /dev/zero; tail -c 8 "$out/corpus/expert-0/actor-7.feedback"; } | sha256sum | cut -d' ' -f1)"
jq -n --arg input "$input" '{passed:true,driveFeedbackNeutralized:true,initialMemoryZero:true,offlineAnalysisOnly:true,dataSHA256:"test",conflicts:[{inputSHA256:$input,examples:[{episode:0,split:"fit",actionClass:0},{episode:1,split:"fit",actionClass:1}]}]}' > "$out/conflicts.json"
analysis="$(cd "$(dirname "$0")/../.." && pwd)/datasets/visual-control/expanded-rooms-v1/audit-initial-conflict-scenes.sh"
"$analysis" "$out/conflicts.json" "$out/corpus" "$out/good" > "$out/good.log"
jq -e '.passed and .conflictingGroups==1 and .examples==2 and .groupsWithDifferentTargetPositions==1 and .groupsWithDifferentStartPoses==0 and .groupsWithOneBlockAndSearch==1 and .groupsWithEmptySimulatorDetector==1 and .actorInputsMatched and .sceneMetadataEvaluationOnly and .detectorIsNotActorRecognition and .causalityNotEstablished' "$out/good/summary.json" > /dev/null
printf '\001' | dd of="$out/corpus/expert-1/actor-7.rgb" bs=1 seek=0 conv=notrunc status=none
if "$analysis" "$out/conflicts.json" "$out/corpus" "$out/bad" > "$out/bad.log" 2>&1; then echo 'Changed actor input accepted.' >&2; exit 1; fi
[[ "$(< "$out/bad/run.exit")" != 0 && ! -e "$out/bad/summary.json" ]]
echo 'Initial conflict scene audit checks source inputs and rejects changed pixels.'
