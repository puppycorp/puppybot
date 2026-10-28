#!/usr/bin/env bash
set -euo pipefail

screen="${1:?Screen directory is required}"
first="${2:?First candidate name is required}"
second="${3:?Second candidate name is required}"
out="${4:?New output directory is required}"
[[ ! -e "$out" && "$first" != "$second" ]]
for candidate in "$first" "$second";do
    /usr/bin/jq -e '.episodes==8 and .completedRecordings==8 and .auditedEpisodes==8 and .auditFailures==0' "$screen/score-$candidate.json" > /dev/null
done
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
for candidate in "$first" "$second";do
    for index in 0 1 2 3 16 17 18 19;do
        row="$screen/$candidate/$index/benchmark-row.json";seed=$((9960000+index));run="$screen/$candidate/$index/$seed"
        /usr/bin/jq -e --argjson index "$index" '.caseIndex==$index and .auditPassed and .recordingCompleted' "$row" > /dev/null
        /usr/bin/jq -s --slurpfile outcome "$row" --arg candidate "$candidate" --argjson index "$index" '{candidate:$candidate,caseIndex:$index,layoutId:$outcome[0].layoutId,actions:length,forward:(map(select(.action[1]>0.05))|length),reverse:(map(select(.action[1]< -0.05))|length),stop:(map(select((.action[1]|fabs)<=0.05))|length),blocked:(map(select(.proprio[5]>0.5))|length),pathM:$outcome[0].pathM,maxExcursionM:$outcome[0].maxExcursionM,leftStartRoom:$outcome[0].leftStartRoom,found:$outcome[0].found,returned:$outcome[0].physicalReturned,auditPassed:$outcome[0].auditPassed}' "$run/decisions.jsonl" > "$out/$candidate-$index.json"
    done
done
/usr/bin/jq -s '{exploratory:true,notPromotionEvidence:true,arms:(group_by(.candidate)|map({candidate:.[0].candidate,episodes:length,returns:(map(select(.returned))|length),approaches:(map(select(.found))|length),actions:(map(.actions)|add),forward:(map(.forward)|add),reverse:(map(.reverse)|add),stop:(map(.stop)|add),blocked:(map(.blocked)|add),meanPathM:((map(.pathM)|add)/length),meanMaxExcursionM:((map(.maxExcursionM)|add)/length),hiddenLeftStartRoom:(map(select(.layoutId==19 and .leftStartRoom))|length),rows:sort_by(.caseIndex)}))}' "$out"/*.json > "$out/result.json"
/usr/bin/jq -e '.exploratory and .notPromotionEvidence and (.arms|length)==2 and all(.arms[];.episodes==8 and (.rows|map(.caseIndex)|unique)==[0,1,2,3,16,17,18,19])' "$out/result.json" > /dev/null
echo 'Exploratory paired screen motion diagnostic completed.'
