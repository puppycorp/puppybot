#!/usr/bin/env bash
set -euo pipefail

project="${PUPPYBOT_PROJECT:?Project root is required}"
base="$project/build/flex/sim/expanded-rooms-v1"
output="${1:?New summary file is required}"
[[ ! -e "$output" && "$(< "$base/matched-training-v3/run.exit")" == 0 ]]
/usr/bin/jq -e '.allEpisodeAuditsPassed and .old.episodes==32 and .expanded.episodes==32 and .old.auditFailures==0 and .expanded.auditFailures==0' "$base/matched-training-v3/comparison.json" > /dev/null
for arm in 172 202;do /usr/bin/jq -e '.episodes==32 and .auditedEpisodes==32 and (.rows|map(.caseIndex)|unique|length)==32' "$base/continued-$arm-motion-v1/result.json" > /dev/null;done
/usr/bin/jq -n --slurpfile comparison "$base/matched-training-v3/comparison.json" --slurpfile training "$base/matched-training-v3/training-comparison.json" --slurpfile old "$base/continued-172-motion-v1/result.json" --slurpfile expanded "$base/continued-202-motion-v1/result.json" '
  def arm: {candidate,episodes,auditedEpisodes,approaches,returns,actions,stop,reverse,blocked,meanPathM,meanMaxExcursionM,byLayout,hiddenDistinctInitialRGBFrames:([.rows[]|select(.layoutId==19)|.initialRGBSHA256]|unique|length)};
  {scope:"same 32 adaptive development cases on layouts 18/19; not independent generalization or physical pickup",task:"simulator consumes the brick within 35 cm, then requires return and docking",training:$training[0],allEpisodeAuditsPassed:$comparison[0].allEpisodeAuditsPassed,original:($old[0]|arm),expanded:($expanded[0]|arm),additionalFourLayoutCheck:"skipped because neither candidate qualified",reservedFinalLayouts:"untouched",retainedPolicyOverwritten:false}' > "$output"
/usr/bin/jq -e '.allEpisodeAuditsPassed and .original.approaches==2 and .original.returns==0 and .expanded.approaches==0 and .expanded.returns==0 and .original.hiddenDistinctInitialRGBFrames==1 and .expanded.hiddenDistinctInitialRGBFrames==1' "$output" > /dev/null
echo 'Matched comparison summary written from audited artifacts.'
