#!/usr/bin/env bash
set -euo pipefail

pilot="${1:?Audited return-pilot directory is required}"
out="${2:?New output directory is required}"
[[ "$(< "$pilot/run.exit")" == 0 && ! -e "$out" ]]
sha="$(/usr/bin/sha256sum "$pilot/packed/data.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$sha" '.passed and .episodes==2 and .datasetEpisodes==2 and .dataSHA256==$sha and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .denseOracleLabels and .taskEventHintAbsent' "$pilot/verified/result.json" > /dev/null
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
for episode in 0 1;do
    run="$pilot/runs/expert-$episode"
    start="$(/usr/bin/jq -r '.studentStartAction' "$run/supervision.json")"
    student="$(/usr/bin/jq -r '.studentActions' "$run/supervision.json")"
    /usr/bin/jq -e --argjson start "$start" --argjson student "$student" '.denseOracleLabels and .studentBeginsAfterConsumption and .studentStartAction==$start and .studentActions==$student and $start>0 and $student>=1' "$run/supervision.json" > /dev/null
    /usr/bin/jq -s --slurpfile supervision "$run/supervision.json" --argjson episode "$episode" --argjson start "$start" --argjson student "$student" '.[0:($start+$student)] as $all | [$all[$start:($start+$student)][]|{executed:.action,oracle:.state.trainingOracle.label,blocked:(.proprio[5]>0.5),vision:.state.case.dockVision.valid,pose:.state.pose,box:.state.case.container.position}] | {episode:$episode,fit:($episode==0),teacherApproachActions:$start,studentReturnActions:length,oracleDiffers:(map(select(((.executed[0]-.oracle[0])|fabs)>0.0001 or ((.executed[1]-.oracle[1])|fabs)>0.0001))|length),blocked:(map(select(.blocked))|length),stop:(map(select((.executed[1]|fabs)<0.05))|length),validBoxVisionFrames:(map(select(.vision))|length),closestRobotCenterToBoxM:(map((.pose[0]-.box[0]) as $x|(.pose[1]-.box[1]) as $y|($x*$x+$y*$y)|sqrt)|min),studentReturnedAfterTeacherApproach:$supervision[0].studentCompletedBeforeHandoff,positionsUsedOnlyForOfflineDiagnostic:true}' "$run/decisions.jsonl" > "$out/$episode.json"
    /usr/bin/jq -e --argjson student "$student" '.studentReturnActions==$student and .positionsUsedOnlyForOfflineDiagnostic' "$out/$episode.json" > /dev/null
done
/usr/bin/jq -s --arg sha "$sha" '{dataSHA256:$sha,audited:true,teacherUsesPrivilegedSimulatorStateOnlyForLabels:true,notAutonomousWholeEpisodePerformance:true,rows:sort_by(.episode)}' "$out"/{0,1}.json > "$out/result.json"
echo 'Audited student return-window diagnostic completed.'
