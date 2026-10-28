#!/usr/bin/env bash
# Diagnose action choices on replay-verified contact feedback, offline only.
set -euo pipefail
cohort="$(realpath "${1:?Verified student cohort required}")"
out="${2:?New output directory required}"
[[ ! -e "$out" ]];mkdir "$out"
data="$cohort/packed/data.bin";sha="$(sha256sum "$data" | cut -d' ' -f1)"
jq -e --arg sha "$sha" '.passed and .episodes==8 and .studentRollinActionsReplayed==2400 and .dataSHA256==$sha and .fullyStudentControlled and .teacherLabelsTrainingOnly and (.actorTaskEventHint|not)' "$cohort/summary.json" > /dev/null
jq -e --arg sha "$sha" '.passed and .episodes==8 and .datasetEpisodes==8 and .dataSHA256==$sha and .studentPolicies256==8 and .studentRollinCommandsReplayed==2400 and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .executedCommandsMatchRecordings and .denseOracleLabels and .taskEventHintAbsent' "$cohort/verified/result.json" > /dev/null
sha256sum "$data" "$cohort/summary.json" "$cohort/verified/result.json" > "$out/inputs.sha256"
for i in {0..7};do
    run="$cohort/runs/expert-$i";audit="$cohort/goal-audit-$i/result.json"
    jq -e '.passed and .oracleLabelsMatched and (.actorInputsChecked|not)' "$audit" > /dev/null
    sha256sum -c "$cohort/goal-audit-$i/inputs.sha256" > "$out/goal-integrity-$i.log"
    jq -e '.studentStartAction==0 and .studentActions==300 and .denseOracleLabels' "$run/supervision.json" > /dev/null
    sha256sum "$audit" "$run/supervision.json" "$run/decisions.jsonl" "$run/teacher-search.jsonl" >> "$out/inputs.sha256"
    jq -sc --argjson i "$i" --slurpfile goals "$run/teacher-search.jsonl" '
        . as $rows |
        if length!=300 or ($goals|length)!=length or
           any(to_entries[]; $goals[.key].step!=.key or
               (.value.proprio[5]!=0 and .value.proprio[5]!=1) or
               (.value.action[1]|type)!="number" or
               ($goals[.key].label[1]|type)!="number")
        then error("inconsistent decision or oracle rows") else . end |
        # Journal feedback belongs to the observation after this action.
        # The next action sees that feedback; omit the first action rather
        # than infer its initial contact from the wrong journal row.
        to_entries | map(select(.key>0 and $rows[.key-1].proprio[5]==1)) |
        {episode:$i,contactFeedbackActions:length,
         oppositeOracle:map(select((.value.action[1]*$goals[.key].label[1])<0))|length,
         oracleStopped:map(select($goals[.key].label[1]==0))|length,
         studentStopped:map(select(.value.action[1]==0))|length}' "$run/decisions.jsonl" >> "$out/rows.jsonl"
done
sha256sum -c "$out/inputs.sha256" > "$out/integrity.log"
jq -s --arg sha "$sha" '{passed:true,episodes:length,dataSHA256:$sha,contactFeedbackActions:(map(.contactFeedbackActions)|add),oppositeOracle:(map(.oppositeOracle)|add),episodesWithAtLeast188ContactFeedbackActions:(map(select(.contactFeedbackActions>=188))|length),studentInput:"previous recorded observation contact feedback",firstActionPerEpisodeExcluded:true,oracleLabelsTrainingOnly:true,offlineAnalysisOnly:true,rows:.}' "$out/rows.jsonl" > "$out/summary.json"
jq -e '.passed and .episodes==8 and .contactFeedbackActions>=.oppositeOracle' "$out/summary.json" > /dev/null
echo 'Contact-feedback actions compared against audited teacher labels.'
