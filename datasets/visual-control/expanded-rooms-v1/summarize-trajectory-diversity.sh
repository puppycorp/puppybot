#!/usr/bin/env bash
# Identify exactly repeated actor trajectories in an audited development benchmark.
set -euo pipefail
benchmark="$(realpath "${1:?Completed 32-case benchmark required}")"
out="${2:?New output directory required}"
[[ ! -e "$out" ]];mkdir "$out"
score="$benchmark/score.json"
jq -e '.episodes==32 and .completedRecordings==32 and .auditedEpisodes==32 and ([.rows[].caseIndex]|sort)==[range(0;32)] and all(.rows[]; .recordingCompleted and .auditPassed and .maximumBrickDistanceM==0.35 and (.suppliedMap|not) and (.taskEventHint|not))' "$score" > /dev/null
sha="$(jq -er '.rows[0].policyWeightsSHA256' "$score")"
jq -e --arg sha "$sha" 'all(.rows[]; .policyWeightsSHA256==$sha)' "$score" > /dev/null
sha256sum "$score" > "$out/inputs.sha256"
for ((index=0;index<32;index++));do
    seed=$((9960000+index));layout=$((18+index/16));run="$benchmark/$index/$seed";row="$benchmark/$index/benchmark-row.json";audit="$benchmark/$index/verified/result.json";distance="$benchmark/$index/distance/result.json"
    jq -e --arg sha "$sha" '.passed and .commandReplayMaxAbsError==0 and .weightsSHA256==$sha and .returnPoseChecked and .taskEventHintAbsent' "$audit" > /dev/null
    jq -n --argjson index "$index" --argjson layout "$layout" --argjson seed "$seed" --slurpfile score "$score" --slurpfile row "$row" '[$score[0].rows[]|select(.caseIndex==$index)] as $matched | ($matched|length)==1 and $matched[0]==$row[0] and $row[0].layoutId==$layout and $row[0].seed==$seed' | jq -e . > /dev/null
    decision_sha="$(sha256sum "$run/decisions.jsonl" | cut -d' ' -f1)"
    jq -e --arg sha "$decision_sha" --slurpfile row "$row" '.decisionsSHA256==$sha and .evaluationOnly and (.referencePositionsEnteredActor|not) and .consumed==$row[0].found' "$distance" > /dev/null
    jq -e '(.pose|type)=="array" and (.pose|length)==3 and all(.pose[];type=="number")' "$run/initial.json" > /dev/null
    initial_step="$(jq -er '.totalSteps | select(type=="number" and .>=0 and floor==.)' "$run/initial.json")"
    initial_image="$run/actor-$initial_step.rgb";initial_feedback="$run/actor-$initial_step.feedback"
    [[ "$(stat -c %s "$initial_image")" == 21168 && "$(stat -c %s "$initial_feedback")" == 28 ]]
    jq -se --slurpfile row "$row" 'length==$row[0].steps and length>0 and all(.[]; (.actorSHA256|type)=="string" and (.actorSHA256|length)==64 and (.proprio|type)=="array" and (.proprio|length)==7 and (.action|type)=="array" and (.action|length)==2 and all(.proprio[],.action[];type=="number"))' "$run/decisions.jsonl" > /dev/null
    # Each journal row records the action and the resulting observation. Include
    # the initial observation too, before the first action in the sequence.
    actor_sha="$({ sha256sum "$initial_image" | cut -d' ' -f1;sha256sum "$initial_feedback" | cut -d' ' -f1;jq -c '[.action,.actorSHA256,.proprio]' "$run/decisions.jsonl"; } | sha256sum | cut -d' ' -f1)"
    jq -nc --argjson index "$index" --argjson layout "$layout" --arg sha "$actor_sha" --slurpfile initial "$run/initial.json" --slurpfile row "$row" '{caseIndex:$index,layoutId:$layout,startPose:$initial[0].pose,actorTrajectorySHA256:$sha,approached:$row[0].found,returned:$row[0].physicalReturned,leftStartRoom:$row[0].leftStartRoom,pathM:$row[0].pathM,maxExcursionM:$row[0].maxExcursionM}' >> "$out/rows.jsonl"
    sha256sum "$run/initial.json" "$initial_image" "$initial_feedback" "$run/decisions.jsonl" "$audit" "$row" "$distance" >> "$out/inputs.sha256"
done
sha256sum -c "$out/inputs.sha256" > "$out/integrity.log"
jq -s --arg sha "$sha" '
  def stats:
    {episodes:length,uniqueStartPoses:(map(.startPose)|unique|length),uniqueActorTrajectories:(map(.actorTrajectorySHA256)|unique|length),
     repeatedTrajectoryGroups:(group_by(.actorTrajectorySHA256)|map(select(length>1)|{cases:map(.caseIndex),count:length})),
     leftStartRoom:map(select(.leftStartRoom))|length,
     meanPathM:(map(.pathM)|add/length),meanMaxExcursionM:(map(.maxExcursionM)|add/length)};
  {passed:true,developmentOnly:true,policyWeightsSHA256:$sha,decisionHashesMatchedRecordedDistanceReceipts:true,
   trajectoryDefinition:"initial resized actor frame and feedback, then ordered actions and resulting actor observations; exact equality only",
   repeatedTrajectoriesAreNotIndependentEvidence:true,overall:stats,open:(map(select(.layoutId==18))|stats),hidden:(map(select(.layoutId==19))|stats),rows:.}' "$out/rows.jsonl" > "$out/summary.json"
jq -e '.passed and .overall.episodes==32 and .open.episodes==16 and .hidden.episodes==16' "$out/summary.json" > /dev/null
echo 'Audited exact actor-trajectory repetition and start poses.'
