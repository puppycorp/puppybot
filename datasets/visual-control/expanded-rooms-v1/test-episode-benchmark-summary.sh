#!/usr/bin/env bash
# Check timing and reject mismatched outcomes or failed audits on fake records.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]]
benchmark="$out/benchmark";mkdir -p "$benchmark"
for ((index=0;index<32;index++));do
    layout=$((18+index/16));seed=$((9960000+index));run="$benchmark/$index/$seed"
    mkdir -p "$run" "$benchmark/$index/verified" "$benchmark/$index/distance"
    found=false;returned=false;if (( index==0 || index==17 ));then found=true;fi;if (( index==0 ));then returned=true;fi
    jq -n --argjson index "$index" --argjson layout "$layout" --argjson seed "$seed" --argjson found "$found" --argjson returned "$returned" '{caseIndex:$index,layoutId:$layout,seed:$seed,recordingCompleted:true,auditPassed:true,maximumBrickDistanceM:0.35,suppliedMap:false,taskEventHint:false,found:$found,physicalReturned:$returned,closestBrickDistanceM:1,policyWeightsSHA256:"test-sha"}' > "$benchmark/$index/benchmark-row.json"
    printf '{"passed":true,"commandReplayMaxAbsError":0,"weightsSHA256":"test-sha","returnPoseChecked":true,"taskEventHintAbsent":true}\n' > "$benchmark/$index/verified/result.json"
    printf '{"totalSteps":295}\n' > "$run/initial.json"
    printf '{"state":{"totalSteps":305,"findReturn":{"consumedIndex":-1,"detectionStep":-1},"case":{"passed":false}}}\n' > "$run/decisions.jsonl"
    if [[ "$found" == true ]];then consumed=0;detection=315;else consumed=-1;detection=-1;fi
    jq -n --argjson consumed "$consumed" --argjson detection "$detection" --argjson returned "$returned" '{state:{totalSteps:315,findReturn:{consumedIndex:$consumed,detectionStep:$detection},case:{passed:$returned}}}' >> "$run/decisions.jsonl"
    decision_sha="$(sha256sum "$run/decisions.jsonl" | cut -d' ' -f1)"
    jq -n --arg sha "$decision_sha" --argjson found "$found" '{decisionsSHA256:$sha,evaluationOnly:true,referencePositionsEnteredActor:false,consumed:$found,closestPlanarBaseToBrickM:1}' > "$benchmark/$index/distance/result.json"
done
jq -s '{episodes:32,completedRecordings:32,auditedEpisodes:32,rows:sort_by(.caseIndex)}' "$benchmark/"*/benchmark-row.json > "$benchmark/score.json"
driver="$project/datasets/visual-control/expanded-rooms-v1/summarize-episode-benchmark.sh"
bash "$driver" "$benchmark" "$out/good" > "$out/good.log" 2>&1
jq -e '.passed and .overall.episodes==32 and .overall.approaches==2 and .overall.returns==1 and .open.approaches==1 and .hidden.approaches==1 and .hidden.returns==0 and .overall.meanApproachSecondsAmongApproaches==0.4 and .overall.meanWholeEpisodeSecondsAmongReturns==6.3' "$out/good/summary.json" > /dev/null
cp "$benchmark/0/9960000/decisions.jsonl" "$out/original.jsonl"
jq -c '.state.findReturn.consumedIndex=-1 | .state.findReturn.detectionStep=-1' "$out/original.jsonl" > "$benchmark/0/9960000/decisions.jsonl"
decision_sha="$(sha256sum "$benchmark/0/9960000/decisions.jsonl" | cut -d' ' -f1)";jq --arg sha "$decision_sha" '.decisionsSHA256=$sha' "$benchmark/0/distance/result.json" > "$out/distance.tmp";cp "$out/distance.tmp" "$benchmark/0/distance/result.json"
if bash "$driver" "$benchmark" "$out/bad-outcome" > "$out/bad-outcome.log" 2>&1;then echo 'Inconsistent event was accepted.' >&2;exit 1;fi
[[ ! -e "$out/bad-outcome/summary.json" ]]
cp "$out/original.jsonl" "$benchmark/0/9960000/decisions.jsonl"
decision_sha="$(sha256sum "$benchmark/0/9960000/decisions.jsonl" | cut -d' ' -f1)";jq --arg sha "$decision_sha" '.decisionsSHA256=$sha' "$benchmark/0/distance/result.json" > "$out/distance.tmp";cp "$out/distance.tmp" "$benchmark/0/distance/result.json"
jq '.passed=false' "$benchmark/0/verified/result.json" > "$out/bad-audit.json";cp "$out/bad-audit.json" "$benchmark/0/verified/result.json"
if bash "$driver" "$benchmark" "$out/bad-audit" > "$out/bad-audit.log" 2>&1;then echo 'Failed audit was accepted.' >&2;exit 1;fi
[[ ! -e "$out/bad-audit/summary.json" ]]
echo 'Episode metrics calculate timing and reject mismatched events or failed audits.'
