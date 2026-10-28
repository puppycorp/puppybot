#!/usr/bin/env bash
set -euo pipefail

project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$project/build/flex/sim/expanded-rooms-v1"
pilot="$root/consumption-match-v1"
original="$root/cohort-v1/runs/4/expert-2"
out="$root/consumption-match-accepted-v1"
[[ "$(< "$pilot/run.exit")" == 1 && ! -e "$out" ]]
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
cd "$project"
/usr/bin/rg -q 'listed files could not be read' "$pilot/run.log"
/usr/bin/sha256sum -c "$pilot/inputs.sha256" > "$out/pilot-integrity.log"
sha="$(/usr/bin/sha256sum "$pilot/packed/data.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$sha" '.passed and .episodes==2 and .datasetEpisodes==2 and .studentRollinCommandsReplayed==240 and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .executedCommandsMatchRecordings and .denseOracleLabels and .taskEventHintAbsent and .dataSHA256==$sha' "$pilot/verified/result.json" > /dev/null
for episode in 0 1;do
    /usr/bin/jq -e --argjson seed "$((9744002+episode))" '.success and .maximumBrickDistanceM==0.35 and .seed==$seed' "$pilot/runs/expert-$episode/result.json" > /dev/null
    for file in case.json environment.bin;do /usr/bin/cmp "$pilot/catalog/$episode/$file" "$pilot/runs/expert-$episode/scene/$file";done
done
for file in case.json environment.bin;do /usr/bin/cmp "$original/scene/$file" "$pilot/runs/expert-0/scene/$file";done
frame="$(/usr/bin/jq -r '.totalSteps' "$original/initial.json")"
[[ "$frame" == "$(/usr/bin/jq -r '.totalSteps' "$pilot/runs/expert-0/initial.json")" ]]
for ((index=0;index<120;index++));do
    for extension in rgb feedback;do /usr/bin/cmp "$original/actor-$((frame+index*10)).$extension" "$pilot/runs/expert-0/actor-$((frame+index*10)).$extension";done
done
/usr/bin/jq -sc '[.[0:120][]|[.step,.action]]' "$original/decisions.jsonl" > "$out/original-prefix.json"
/usr/bin/jq -sc '[.[0:120][]|[.step,.action]]' "$pilot/runs/expert-0/decisions.jsonl" > "$out/new-prefix.json"
/usr/bin/cmp "$out/original-prefix.json" "$out/new-prefix.json"
/usr/bin/jq -se '[.[]|select(.step==2075)|.state.findReturn.consumedIndex]|.[0]==-1' "$pilot/runs/expert-0/decisions.jsonl" > /dev/null
/usr/bin/jq -se '[.[]|select(.state.findReturn.detectionStep==.step)|.step]|.[0]==2085' "$pilot/runs/expert-0/decisions.jsonl" > /dev/null
/usr/bin/jq -n --arg sha "$sha" '{passed:true,sourcePilotExit:1,sourcePilotFailure:"integrity check ran outside project directory",independentIntegrityCheckPassed:true,independentPhysicalAndReplayAuditsPassed:true,studentPrefixFramesAndActionsIdentical:120,originalMismatchedDetectionRejectedAtStep:2075,subsequentAuditedDetectionAtStep:2085,maximumBrickDistanceM:0.35,dataSHA256:$sha}' > "$out/result.json"
echo 'Pilot accepted by separate integrity and audit checks; original failed wrapper remains preserved.'
