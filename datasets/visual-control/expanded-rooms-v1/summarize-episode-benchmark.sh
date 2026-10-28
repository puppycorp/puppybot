#!/usr/bin/env bash
# Summarize complete, independently audited find-and-return episodes.
set -euo pipefail
benchmark="$(realpath "${1:?Completed 32-case benchmark required}")"
out="${2:?New output directory required}"
[[ ! -e "$out" ]];mkdir "$out"
score="$benchmark/score.json"
jq -e '.episodes==32 and .completedRecordings==32 and .auditedEpisodes==32 and ([.rows[].caseIndex]|sort)==[range(0;32)] and all(.rows[]; .recordingCompleted and .auditPassed and .maximumBrickDistanceM==0.35 and (.suppliedMap|not) and (.taskEventHint|not) and (.found|type)=="boolean" and (.physicalReturned|type)=="boolean" and ((.physicalReturned|not) or .found))' "$score" > /dev/null
sha="$(jq -er '.rows[0].policyWeightsSHA256' "$score")"
jq -e --arg sha "$sha" 'all(.rows[]; .policyWeightsSHA256==$sha)' "$score" > /dev/null
sha256sum "$score" > "$out/inputs.sha256"
for ((index=0;index<32;index++));do
    case_seed=$((9960000+index));layout=$((18+index/16));run="$benchmark/$index/$case_seed";audit="$benchmark/$index/verified/result.json";row="$benchmark/$index/benchmark-row.json";distance="$benchmark/$index/distance/result.json"
    jq -e --arg sha "$sha" '.passed and .commandReplayMaxAbsError==0 and .weightsSHA256==$sha and .returnPoseChecked and .taskEventHintAbsent' "$audit" > /dev/null
    jq -e --arg sha "$sha" --argjson index "$index" --argjson layout "$layout" --argjson seed "$case_seed" '.caseIndex==$index and .layoutId==$layout and .seed==$seed and .policyWeightsSHA256==$sha and .recordingCompleted and .auditPassed' "$row" > /dev/null
    jq -n --argjson index "$index" --slurpfile score "$score" --slurpfile row "$row" '[$score[0].rows[]|select(.caseIndex==$index)] as $matched | ($matched|length)==1 and $matched[0]==$row[0]' | jq -e . > /dev/null
    decision_sha="$(sha256sum "$run/decisions.jsonl" | cut -d' ' -f1)"
    jq -e --arg sha "$decision_sha" --slurpfile row "$row" '.decisionsSHA256==$sha and .evaluationOnly and (.referencePositionsEnteredActor|not) and .consumed==$row[0].found and .closestPlanarBaseToBrickM==$row[0].closestBrickDistanceM' "$distance" > /dev/null
    sha256sum "$run/initial.json" "$run/decisions.jsonl" "$audit" "$row" "$distance" >> "$out/inputs.sha256"
    jq -n --slurpfile initial "$run/initial.json" --slurpfile decisions "$run/decisions.jsonl" --slurpfile row "$row" '
      $initial[0].totalSteps as $start |
      [$decisions[]|select(.state.findReturn.consumedIndex>=0)|.state.findReturn.detectionStep] as $hits |
      ($decisions[-1].state.totalSteps) as $end |
      if ($decisions|length)<1 or $end<$start or (($hits|length)>0)!=$row[0].found or ($decisions[-1].state.case.passed!=$row[0].physicalReturned) then error("episode outcome disagrees with recorded states") else . end |
      {caseIndex:$row[0].caseIndex,layoutId:$row[0].layoutId,seed:$row[0].seed,
       approached:$row[0].found,returned:$row[0].physicalReturned,
       approachSeconds:(if ($hits|length)>0 then (($hits[0]-$start)/50) else null end),
       wholeEpisodeSeconds:($end/50),drivingSeconds:(($end-$start)/50)} |
      if .approachSeconds!=null and (.approachSeconds<0 or .approachSeconds>.drivingSeconds) then error("invalid approach time") else . end' >> "$out/rows.jsonl"
done
sha256sum -c "$out/inputs.sha256" > "$out/integrity.log"
jq -s --arg sha "$sha" '
  def avg: if length==0 then null else add/length end;
  def stats:
    {episodes:length,approaches:map(select(.approached))|length,returns:map(select(.returned))|length,
     approachRate:(map(select(.approached))|length)/(length),
     returnRate:(map(select(.returned))|length)/(length),
     meanApproachSecondsAmongApproaches:(map(select(.approached)|.approachSeconds)|avg),
     meanWholeEpisodeSecondsAmongReturns:(map(select(.returned)|.wholeEpisodeSeconds)|avg),
     meanWholeEpisodeSecondsAll:(map(.wholeEpisodeSeconds)|avg)};
  {passed:true,policyWeightsSHA256:$sha,developmentOnly:true,decisionHashesMatchedRecordedDistanceReceipts:true,secondsMeasuredFromSimulationTicks:true,
   approachTimeStartsAfterInitialCameraPositioning:true,returnTimeIncludesInitialCameraPositioning:true,
   overall:stats,open:(map(select(.layoutId==18))|stats),hidden:(map(select(.layoutId==19))|stats),rows:.}' "$out/rows.jsonl" > "$out/summary.json"
jq -e '.passed and .overall.episodes==32 and .open.episodes==16 and .hidden.episodes==16' "$out/summary.json" > /dev/null
echo 'Audited episode success, approach and simulation-time metrics summarized.'
