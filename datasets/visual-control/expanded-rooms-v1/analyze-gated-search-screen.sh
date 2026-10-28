#!/usr/bin/env bash
# Offline physical-distance scoring of the matched four-case development screen.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
pair="${1:?Completed matched screen required}"
out="${2:?New output directory required}"
measure="${3:?Distance measurement executable required}"
[[ ! -e "$out" ]]
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
[[ "$(< "$pair/run.exit")" == 0 ]]
/usr/bin/jq -e '.exploratory and .episodesPerModel==4 and .optimizerStepsPerModel==98 and .initialWeightsIdentical and .reservedFinalStillRequired and (.automaticPromotion|not)' "$pair/comparison.json" > /dev/null
/usr/bin/sha256sum "$measure" "$pair/comparison.json" "$pair/baseline-policy/weights.bin" "$pair/augmented-policy/weights.bin" > "$out/inputs.sha256"
for arm in baseline augmented;do
    policy_sha="$(/usr/bin/sha256sum "$pair/$arm-policy/weights.bin" | /usr/bin/cut -d' ' -f1)"
    for index in 2 15 16 17;do
        seed=$((9960000+index));original="$pair/$arm-screen/$index";episode="$original/$seed";destination="$out/$arm-$index"
        /usr/bin/jq -e --arg sha "$policy_sha" '.passed and .weightsSHA256==$sha and .commandReplayMaxAbsError==0 and .taskEventHintAbsent and (.blackout|not)' "$original/verified/result.json" > /dev/null
        /usr/bin/jq -e --arg sha "$policy_sha" '.complete and .episodes==1 and .rows[0].policyWeightsSHA256==$sha and (.rows[0].suppliedMap|not) and (.rows[0].taskEventHint|not)' "$original/summary.json" > /dev/null
        /usr/bin/sha256sum "$episode/decisions.jsonl" "$episode/initial.json" "$original/verified/result.json" "$original/summary.json" >> "$out/inputs.sha256"
        "$measure" "$episode" "$destination" > "$out/$arm-$index.log" 2>&1
        /usr/bin/jq -e '.closestPlanarBaseToBrickM>=0' "$destination/result.json" > /dev/null
        /usr/bin/jq -s '{actions:length,forward:(map(select(.action[1]>0))|length),reverse:(map(select(.action[1]<0))|length),stopped:(map(select(.action[1]==0))|length)}' "$episode/decisions.jsonl" > "$destination/motion.json"
        /usr/bin/jq -n --arg arm "$arm" --argjson index "$index" --slurpfile distance "$destination/result.json" --slurpfile motion "$destination/motion.json" --slurpfile episode "$original/summary.json" '{arm:$arm,caseIndex:$index,closestBrickDistanceM:$distance[0].closestPlanarBaseToBrickM,found:$episode[0].rows[0].found,returned:$episode[0].rows[0].success,motion:$motion[0]}' > "$destination/row.json"
    done
done
for index in 2 15 16 17;do
    seed=$((9960000+index));for file in case.json environment.bin;do /usr/bin/cmp "$pair/baseline-screen/$index/$seed/scene/$file" "$pair/augmented-screen/$index/$seed/scene/$file";done
done
/usr/bin/jq -s '[.[]|select(.arm=="baseline")] as $base | [.[]|select(.arm=="augmented")] as $new | {exploratory:true,episodesPerModel:4,baselineMeanClosestM:($base|map(.closestBrickDistanceM)|add/length),augmentedMeanClosestM:($new|map(.closestBrickDistanceM)|add/length),rows:sort_by(.caseIndex,.arm),referencePositionsUsedOnlyForOfflineScoring:true,actorInputsUnchanged:true,reservedFinalStillRequired:true,automaticPromotion:false}' "$out/"*/row.json > "$out/comparison.json"
/usr/bin/jq -e '.exploratory and .episodesPerModel==4 and (.rows|length)==8 and .referencePositionsUsedOnlyForOfflineScoring and .actorInputsUnchanged and (.automaticPromotion|not)' "$out/comparison.json" > /dev/null
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
echo 'Matching development episodes scored by recorded physical distance and motion.'
