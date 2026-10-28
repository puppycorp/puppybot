#!/usr/bin/env bash
set -euo pipefail

benchmark="${1:?Benchmark directory is required}"
candidate="${2:?Candidate name is required}"
out="${3:?New output directory is required}"
[[ -f "$benchmark/score-$candidate.json" && ! -e "$out" ]]
/usr/bin/jq -e '.episodes==32 and .auditedEpisodes==32 and .auditFailures==0' "$benchmark/score-$candidate.json" > /dev/null
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
for index in {0..31};do
    row="$benchmark/$candidate/$index/benchmark-row.json"
    seed=$((9960000+index));run="$benchmark/$candidate/$index/$seed"
    /usr/bin/jq -e --argjson index "$index" '.caseIndex==$index and .auditPassed and .recordingCompleted' "$row" > /dev/null
    frame="$(/usr/bin/jq -r '.totalSteps' "$run/initial.json")"
    rgbsha="$(/usr/bin/sha256sum "$run/actor-$frame.rgb" | /usr/bin/cut -d' ' -f1)"
    /usr/bin/jq -s --slurpfile outcome "$row" --argjson index "$index" --arg rgb "$rgbsha" '{caseIndex:$index,layoutId:$outcome[0].layoutId,initialRGBSHA256:$rgb,actions:length,forward:(map(select(.action[1]>0.05))|length),reverse:(map(select(.action[1]< -0.05))|length),stop:(map(select((.action[1]|fabs)<=0.05))|length),blocked:(map(select(.proprio[5]>0.5))|length),pathM:$outcome[0].pathM,maxExcursionM:$outcome[0].maxExcursionM,found:$outcome[0].found,returned:$outcome[0].physicalReturned,auditPassed:$outcome[0].auditPassed}' "$run/decisions.jsonl" > "$out/$index.json"
done
/usr/bin/jq -s --arg candidate "$candidate" '{candidate:$candidate,episodes:length,auditedEpisodes:(map(select(.auditPassed))|length),returns:(map(select(.returned))|length),approaches:(map(select(.found))|length),actions:(map(.actions)|add),forward:(map(.forward)|add),reverse:(map(.reverse)|add),stop:(map(.stop)|add),blocked:(map(.blocked)|add),meanPathM:((map(.pathM)|add)/length),meanMaxExcursionM:((map(.maxExcursionM)|add)/length),pathsUnderOneMeter:(map(select(.pathM<1))|length),distinctInitialRGBFrames:([.[].initialRGBSHA256]|unique|length),byLayout:(group_by(.layoutId)|map({layoutId:.[0].layoutId,episodes:length,returns:(map(select(.returned))|length),approaches:(map(select(.found))|length),actions:(map(.actions)|add),stop:(map(.stop)|add),reverse:(map(.reverse)|add),blocked:(map(.blocked)|add),pathsUnderOneMeter:(map(select(.pathM<1))|length)})),rows:sort_by(.caseIndex)}' "$out"/*.json > "$out/result.json"
/usr/bin/jq -e '.episodes==32 and .auditedEpisodes==32 and (.rows|map(.caseIndex)|unique|length)==32' "$out/result.json" > /dev/null
echo 'Completed episode motion diagnostic; it is not itself a success metric.'
