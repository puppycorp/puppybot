#!/usr/bin/env bash
set -euo pipefail

project="${PUPPYBOT_PROJECT:?Project root is required}"
base="$project/build/flex/sim/expanded-rooms-v1"
root="$base/correction-probe-v1"
reference="$base/unseen-benchmark-v2/student"
out="${1:?New output directory is required}"
[[ "$(< "$root/screen.exit")" == 0 && "$(< "$root/forward-epoch20.exit")" == 0 && ! -e "$out" ]]
/usr/bin/jq -e '.exploratory and .allEpisodeAuditsPassed and (.qualifiesForPromotion|not)' "$root/screen-comparison.json" > /dev/null
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
for arm in reference trained;do
    dir="$reference";if [[ "$arm" == trained ]];then dir="$root/screen-epoch20";fi
    for index in 0 1 2 3 16 17 18 19;do
        row="$dir/$index/benchmark-row.json";seed=$((9960000+index));run="$dir/$index/$seed"
        /usr/bin/jq -e --argjson index "$index" '.caseIndex==$index and .auditPassed and .recordingCompleted' "$row" > /dev/null
        /usr/bin/jq -s --slurpfile outcome "$row" --arg arm "$arm" --argjson index "$index" '{arm:$arm,caseIndex:$index,layoutId:$outcome[0].layoutId,actions:length,forward:(map(select(.action[1]>0.05))|length),reverse:(map(select(.action[1]< -0.05))|length),stop:(map(select((.action[1]|fabs)<=0.05))|length),blocked:(map(select(.proprio[5]>0.5))|length),pathM:$outcome[0].pathM,maxExcursionM:$outcome[0].maxExcursionM,leftStartRoom:$outcome[0].leftStartRoom,found:$outcome[0].found,returned:$outcome[0].physicalReturned,auditPassed:$outcome[0].auditPassed}' "$run/decisions.jsonl" > "$out/$arm-$index.json"
    done
done
/usr/bin/jq -s '{exploratory:true,notPromotionEvidence:true,arms:(group_by(.arm)|map({arm:.[0].arm,episodes:length,returns:(map(select(.returned))|length),approaches:(map(select(.found))|length),actions:(map(.actions)|add),forward:(map(.forward)|add),reverse:(map(.reverse)|add),stop:(map(.stop)|add),blocked:(map(.blocked)|add),meanPathM:((map(.pathM)|add)/length),meanMaxExcursionM:((map(.maxExcursionM)|add)/length),hiddenLeftStartRoom:(map(select(.layoutId==19 and .leftStartRoom))|length),rows:sort_by(.caseIndex)}))}' "$out"/*.json > "$out/result.json"
/usr/bin/jq -e '.exploratory and .notPromotionEvidence and (.arms|length)==2 and all(.arms[];.episodes==8)' "$out/result.json" > /dev/null
echo 'Exploratory screen motion diagnostic completed.'
