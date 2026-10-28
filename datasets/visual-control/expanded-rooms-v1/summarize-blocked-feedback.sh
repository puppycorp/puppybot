#!/usr/bin/env bash
# Relate offline feedback interventions to the actual pre-action contact input.
set -euo pipefail
probe="$(realpath "${1:?Completed feedback probe required}")"
run="$(realpath "${2:?Audited autonomous episode required}")"
out="${3:?New output directory required}"
[[ ! -e "$out" ]];mkdir "$out"
audit="$run/../verified/result.json";report="$probe/result.json";decisions="$run/decisions.jsonl"
sha="$(jq -er '.weightsSHA256' "$report")"
jq -e --arg sha "$sha" '.passed and .commandReplayMaxAbsError==0 and .weightsSHA256==$sha and .taskEventHintAbsent' "$audit" > /dev/null
jq -e --arg sha "$sha" '.weightsSHA256==$sha and .actualCommandsReplayedExactly and .counterfactualDidNotAlterServerState and .neutralFeedbackHypothetical and .offlineCounterfactualOnly and .simulatorPhaseUsedOnlyForAnalysis' "$report" > /dev/null
sha256sum "$report" "$decisions" "$audit" > "$out/inputs.sha256"
jq -n --slurpfile p "$report" --slurpfile decisions "$decisions" '
  $p[0].rows as $rows |
  if ($rows|length)<2 or ($rows|length)!=($decisions|length) or ([$rows[].actionIndex] != [range(0;($rows|length))]) or
     (all($rows[]; (.actualClass>=0 and .actualClass<7 and .neutralFeedbackClass>=0 and .neutralFeedbackClass<7) and (.actualReturning|type)=="boolean" and .neutralFeedbackChangesAction==(.actualClass!=.neutralFeedbackClass))|not) or
     (all($decisions[]; (.proprio|length)==7 and (.proprio[5]==0 or .proprio[5]==1))|not)
  then error("probe and recorded feedback do not align") else . end |
  [$rows[] as $row | select($row.actionIndex>0 and ($row.actualReturning|not) and $decisions[$row.actionIndex-1].proprio[5]==1) | $row] as $blocked |
  {passed:true,weightsSHA256:$p[0].weightsSHA256,frames:($rows|length),blockedSearchInputFrames:($blocked|length),
   actionsChangedWhenPriorDriveFeedbackNeutralized:($blocked|map(select(.neutralFeedbackChangesAction))|length),
   actualForward:($blocked|map(select(.actualClass<3))|length),actualReverse:($blocked|map(select(.actualClass>=3 and .actualClass<6))|length),
   hypotheticalForward:($blocked|map(select(.neutralFeedbackClass<3))|length),hypotheticalReverse:($blocked|map(select(.neutralFeedbackClass>=3 and .neutralFeedbackClass<6))|length),hypotheticalStop:($blocked|map(select(.neutralFeedbackClass==6))|length),
   initialActionExcluded:true,contactInputTakenFromPreviousRecordedObservation:true,contactFeedbackPreservedInCounterfactual:true,
   actualCommandsReplayedExactly:true,offlineCounterfactualOnly:true,closedLoopBehaviorNotMeasured:true}' > "$out/summary.json"
sha256sum -c "$out/inputs.sha256" > "$out/integrity.log"
echo 'Blocked-search feedback sensitivity summarized with pre-action alignment.'
