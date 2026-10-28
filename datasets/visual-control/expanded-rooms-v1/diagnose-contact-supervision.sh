#!/usr/bin/env bash
set -euo pipefail

pilot="${1:?Audited pilot directory is required}"
out="${2:?New output directory is required}"
[[ "$(< "$pilot/run.exit")" == 0 && ! -e "$out" ]]
sha="$(/usr/bin/sha256sum "$pilot/packed/data.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$sha" '.passed and .episodes==2 and .datasetEpisodes==2 and .dataSHA256==$sha and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .denseOracleLabels and .taskEventHintAbsent' "$pilot/verified/result.json" > /dev/null
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
for episode in 0 1;do
    run="$pilot/runs/expert-$episode";student="$(/usr/bin/jq -r '.studentActions' "$run/supervision.json")"
    /usr/bin/jq -e --argjson student "$student" '.denseOracleLabels and .studentStartAction==0 and .studentActions==$student and $student>=1' "$run/supervision.json" > /dev/null
    /usr/bin/jq -s --argjson episode "$episode" --argjson student "$student" '.[0:$student] as $rows | [range(1;($rows|length)) as $i | select($rows[$i-1].proprio[5]>0.5) | {executed:$rows[$i].action,oracle:$rows[$i].state.trainingOracle.label,previous:$rows[$i-1].action,stillBlocked:($rows[$i].proprio[5]>0.5)}] | {episode:$episode,fit:($episode==0),studentActions:$student,afterBlocked:length,oracleDiffers:(map(select(((.executed[0]-.oracle[0])|fabs)>0.0001 or ((.executed[1]-.oracle[1])|fabs)>0.0001))|length),studentRepeated:(map(select(.executed==.previous))|length),teacherDirectionReversed:(map(select(.oracle[1]*.previous[1]<0))|length),studentStillBlocked:(map(select(.stillBlocked))|length),samples:.[0:5]}' "$run/decisions.jsonl" > "$out/$episode.json"
done
/usr/bin/jq -s --arg sha "$sha" '{dataSHA256:$sha,audited:true,teacherUsesPrivilegedSimulatorStateOnlyForLabels:true,notStudentTaskPerformance:true,rows:sort_by(.episode)}' "$out"/{0,1}.json > "$out/result.json"
echo 'Audited contact-supervision diagnostic completed.'
