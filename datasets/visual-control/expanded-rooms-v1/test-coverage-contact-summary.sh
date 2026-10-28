#!/usr/bin/env bash
# Contact feedback belongs to the observation before the next action.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]]
cohort="$out/cohort";mkdir -p "$cohort/packed" "$cohort/verified" "$cohort/runs"
printf 'dataset\n' > "$cohort/packed/data.bin";sha="$(sha256sum "$cohort/packed/data.bin" | cut -d' ' -f1)"
jq -n --arg sha "$sha" '{passed:true,episodes:8,studentRollinActionsReplayed:2400,dataSHA256:$sha,fullyStudentControlled:true,teacherLabelsTrainingOnly:true,actorTaskEventHint:false}' > "$cohort/summary.json"
jq -n --arg sha "$sha" '{passed:true,episodes:8,datasetEpisodes:8,dataSHA256:$sha,studentPolicies256:8,studentRollinCommandsReplayed:2400,studentRollinMaxAbsError:0,datasetInputsMatchActualRGBAndOwnFeedback:true,executedCommandsMatchRecordings:true,denseOracleLabels:true,taskEventHintAbsent:true}' > "$cohort/verified/result.json"
for i in {0..7};do
    run="$cohort/runs/expert-$i";audit="$cohort/goal-audit-$i";mkdir -p "$run" "$audit"
    printf '{"passed":true,"oracleLabelsMatched":true,"actorInputsChecked":false}\n' > "$audit/result.json"
    printf '{"studentStartAction":0,"studentActions":300,"denseOracleLabels":true}\n' > "$run/supervision.json"
    jq -nc 'range(0;300) as $i | {action:[0,1],proprio:[0,0,0,0,0,(if $i==0 then 1 else 0 end),0]}' > "$run/decisions.jsonl"
    jq -nc 'range(0;300) as $i | {step:$i,label:[0,(if $i==1 then -1 else 1 end)]}' > "$run/teacher-search.jsonl"
    sha256sum "$run/teacher-search.jsonl" > "$audit/inputs.sha256"
done
driver="$project/datasets/visual-control/expanded-rooms-v1/summarize-coverage-contact.sh"
bash "$driver" "$cohort" "$out/good" > "$out/good.log" 2>&1
jq -e '.passed and .episodes==8 and .firstActionPerEpisodeExcluded and .contactFeedbackActions==8 and .oppositeOracle==8 and all(.rows[]; .contactFeedbackActions==1 and .oppositeOracle==1)' "$out/good/summary.json" > /dev/null
jq -c 'if .step==1 then .step=2 else . end' "$cohort/runs/expert-0/teacher-search.jsonl" > "$out/altered.jsonl";cp "$out/altered.jsonl" "$cohort/runs/expert-0/teacher-search.jsonl"
sha256sum "$cohort/runs/expert-0/teacher-search.jsonl" > "$cohort/goal-audit-0/inputs.sha256"
if bash "$driver" "$cohort" "$out/bad" > "$out/bad.log" 2>&1;then echo 'Misaligned teacher records were accepted.' >&2;exit 1;fi
[[ ! -e "$out/bad/summary.json" ]]
echo 'Coverage contact summary uses the preceding observation and rejects misaligned labels.'
