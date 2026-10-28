#!/usr/bin/env bash
# Independently normalize an audited large-model development benchmark for
# the existing qualification gate. No result is promoted by this command.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
run="${1:?Completed benchmark directory required}"
policy="${2:?Scored policy directory required}"
out="${3:?New output directory required}"
name="${4:?Candidate name required}"
[[ "$name" =~ ^[a-zA-Z0-9_-]+$ && ! -e "$out" ]]
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
score="$run/score.json"
[[ "$(< "$run/run.exit")" == 0 ]]
sha="$(/usr/bin/sha256sum "$policy/weights.bin" | /usr/bin/cut -d' ' -f1)"
binary="$(/usr/bin/sha256sum "$policy/policy" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$sha" --arg binary "$binary" '.memoryWidth==256 and .weightsSHA256==$sha and .binarySHA256==$binary and .taskFeedback==false and (.imageSide // 84)==84' "$policy/receipt.json" > /dev/null
/usr/bin/jq -e --arg sha "$sha" '.episodes==32 and .completedRecordings==32 and .auditedEpisodes==32 and (.rows|length)==32 and ([.rows[].caseIndex]|sort)==[range(0;32)] and all(.rows[]; .recordingCompleted and .auditPassed and .policyWeightsSHA256==$sha and .maximumBrickDistanceM==0.35 and .suppliedMap==false and .taskEventHint==false)' "$score" > /dev/null
/usr/bin/sha256sum "$score" "$policy/weights.bin" "$policy/policy" "$policy/receipt.json" > "$out/inputs.sha256"
mkdir "$out/$name"
for ((index=0;index<32;index++)); do
    layout=$((18+index/16)); scene=$((index%16)); seed=$((9960000+index))
    original="$run/$index"; episode="$original/$seed"; row="$original/benchmark-row.json"; destination="$out/$name/$index"
    /usr/bin/jq -e --argjson index "$index" --slurpfile row "$row" '[.rows[]|select(.caseIndex==$index)]==[$row[0]]' "$score" > /dev/null
    /usr/bin/jq -e --argjson index "$index" --argjson layout "$layout" --argjson seed "$seed" '.caseIndex==$index and .layoutId==$layout and .seed==$seed and .recordingCompleted and .auditPassed' "$row" > /dev/null
    /usr/bin/jq -e --arg sha "$sha" '.passed and .weightsSHA256==$sha and .commandReplayMaxAbsError==0 and .taskEventHintAbsent and .blackout==false' "$original/verified/result.json" > /dev/null
    for file in case.json environment.bin; do /usr/bin/cmp "$episode/scene/$file" "$project/build/flex/sim/expanded-rooms-v1/unseen-benchmark-v2/scenes/$layout/$scene/$file"; done
    recorded="$(/usr/bin/tail -n 1 "$episode/decisions.jsonl" | /usr/bin/jq -r '.state.case.passed')"
    [[ "$recorded" == true || "$recorded" == false ]]
    /usr/bin/jq -e --argjson recorded "$recorded" '.physicalReturned==$recorded and .success==$recorded and ((.physicalReturned|not) or .found)' "$row" > /dev/null
    /usr/bin/jq -e --slurpfile row "$row" '.complete and .episodes==1 and .rows[0].seed==$row[0].seed and .rows[0].found==$row[0].found and .rows[0].success==$row[0].success and .rows[0].policyWeightsSHA256==$row[0].policyWeightsSHA256' "$original/summary.json" > /dev/null
    mkdir "$destination"
    /usr/bin/ln -s "$(/usr/bin/realpath "$original/verified")" "$destination/verified"
    /usr/bin/ln -s "$(/usr/bin/realpath "$episode")" "$destination/$seed"
    /usr/bin/jq --argjson scene "$scene" --argjson recorded "$recorded" '.+{sceneId:$scene,recordedPhysicalReturn:$recorded}' "$row" > "$destination/benchmark-row.json"
done
/usr/bin/jq -s --arg candidate "$name" '{candidate:$candidate,episodes:length,completedRecordings:(map(select(.recordingCompleted))|length),auditedEpisodes:(map(select(.auditPassed))|length),auditFailures:(map(select(.auditPassed|not))|length),physicalReturns:(map(select(.physicalReturned))|length),auditedApproaches:(map(select(.auditPassed and .found))|length),openReturns:(map(select(.layoutId==18 and .physicalReturned))|length),hiddenReturns:(map(select(.layoutId==19 and .physicalReturned))|length),meanSuccessfulSimulationSeconds:(map(select(.physicalReturned)|.simulationSeconds)|if length>0 then add/length else null end),rows:sort_by(.caseIndex)}' "$out/$name/"*/benchmark-row.json > "$out/score-$name.json"
/usr/bin/jq -e --slurpfile source "$score" '.episodes==$source[0].episodes and .auditedEpisodes==$source[0].auditedEpisodes and .physicalReturns==$source[0].returns and .auditedApproaches==$source[0].approaches and .openReturns==$source[0].openReturns and .hiddenReturns==$source[0].hiddenReturns' "$out/score-$name.json" > /dev/null
/usr/bin/bash "$project/datasets/visual-control/expanded-rooms-v1/select-episode-candidate.sh" "$out/selection" "$out/score-$name.json" "$policy" > "$out/selection.log" 2>&1
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
/usr/bin/jq -e '.reservedFinalStillRequired and (.retainedPolicyOverwritten|not)' "$out/selection/selection.json" > /dev/null
