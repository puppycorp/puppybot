#!/usr/bin/env bash
# Compare the two retained coverage-teacher examples with exact-input conflicts.
set -euo pipefail
scene_audit="$(realpath "${1:?Conflict scene audit required}")"
pilot="$(realpath "${2:?Audited two-episode coverage pilot required}")"
out="$(realpath -m "${3:?New output directory required}")"
[[ ! -e "$out" ]]
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
jq -e '.passed and .actorInputsMatched and .sceneMetadataEvaluationOnly' "$scene_audit" > /dev/null
jq -e '.passed and .episodes==2 and .teacherCompleted==2 and (.studentAutonomousSuccessClaimed|not)' "$pilot/summary.json" > /dev/null
jq -e '.passed and .taskEventHintAbsent' "$pilot/verified/result.json" > /dev/null
sha256sum "$scene_audit" "$pilot/summary.json" "$pilot/verified/result.json" > "$out/inputs.sha256"
: > "$out/rows.jsonl"
for index in 0 1; do
    episode="$pilot/runs/expert-$index"; initial="$episode/initial.json"; scene="$episode/scene/case.json"; trace="$episode/teacher-search.jsonl"; audit="$pilot/goal-audit-$index/result.json"
    jq -e '.passed and .reconstructedFromRoomBoundsAndRecordedCamera and .oracleLabelsMatched and .brickPositionNotReadBySearchReconstruction and .teacherGeometryPrivileged' "$audit" > /dev/null
    frame="$(jq -er '.totalSteps | select(type=="number" and .>=0 and floor==.)' "$initial")"
    rgb="$episode/actor-$frame.rgb"; feedback="$episode/actor-$frame.feedback"
    [[ "$(stat -c %s "$rgb")" == 21168 && "$(stat -c %s "$feedback")" == 28 ]]
    input="$( { cat "$rgb"; head -c 20 /dev/zero; tail -c 8 "$feedback"; } | sha256sum | cut -d' ' -f1)"
    scene_sha="$(sha256sum "$scene" | cut -d' ' -f1)"
    supervision="$episode/supervision.json"; pilot_scene="$(jq -er '.sourceScene | select(type=="string" and length>0)' "$supervision")"
    layout="$pilot_scene/layout.json"; [[ -f "$layout" ]]
    cmp "$scene" "$pilot_scene/case.json"; cmp "$episode/scene/environment.bin" "$pilot_scene/environment.bin"
    layout_sha="$(jq -c '{rooms,startRoom}' "$layout" | sha256sum | cut -d' ' -f1)"
    sha256sum "$supervision" "$layout" "$pilot_scene/case.json" "$pilot_scene/environment.bin" "$episode/scene/environment.bin" >> "$out/inputs.sha256"
    first="$(head -n 1 "$trace")"
    jq -e '.step==0 and .source=="coverage" and .label==[0,1]' <<< "$first" > /dev/null
    jq -e '.findReturn.phase=="search" and .case.perception.chosen == -1 and (.case.perception.detections|length)==0' "$initial" > /dev/null
    matches="$out/$index-matches.jsonl"; : > "$matches"
    while IFS=$'\t' read -r number action recording; do
        [[ "$number" =~ ^[0-9]+$ && "$action" =~ ^[0-6]$ ]]
        source_scene="$recording/scene/case.json"; source_sha="$(sha256sum "$source_scene" | cut -d' ' -f1)"
        if [[ "$source_sha" == "$scene_sha" ]]; then
            source_supervision="$recording/supervision.json"; training_scene="$(jq -er '.sourceScene | select(type=="string" and length>0)' "$source_supervision")"; training_layout="$training_scene/layout.json"
            cmp "$source_scene" "$training_scene/case.json"; cmp "$recording/scene/environment.bin" "$training_scene/environment.bin"
            training_layout_sha="$(jq -c '{rooms,startRoom}' "$training_layout" | sha256sum | cut -d' ' -f1)"
            jq -n --argjson episode "$number" --argjson action "$action" --arg layout "$training_layout_sha" '{episode:$episode,actionClass:$action,trainingLayoutSHA256:$layout}' >> "$matches"
            sha256sum "$source_supervision" "$training_layout" "$training_scene/case.json" "$training_scene/environment.bin" "$recording/scene/environment.bin" >> "$out/inputs.sha256"
        fi
        sha256sum "$source_scene" >> "$out/inputs.sha256"
    done < <(jq -r --arg input "$input" '.groups[] | select(.rows[0].inputSHA256==$input) | .rows[] | [.episode,.actionClass,.recording] | @tsv' "$scene_audit")
    jq -s -e 'length>0' "$matches" > /dev/null
    sha256sum "$initial" "$scene" "$trace" "$audit" "$rgb" "$feedback" >> "$out/inputs.sha256"
    jq -n --argjson pilotIndex "$index" --arg input "$input" --arg scene "$scene_sha" --arg layout "$layout_sha" --slurpfile initial "$initial" --slurpfile matches "$matches" '{pilotIndex:$pilotIndex,inputSHA256:$input,sceneSHA256:$scene,teacherLayoutSHA256:$layout,recordedPose:$initial[0].pose,teacherActionClass:1,teacherSource:"coverage",matchingCorpusLabels:$matches}' >> "$out/rows.jsonl"
done
sha256sum -c "$out/inputs.sha256" > "$out/integrity.log"
jq -s -e 'length==2 and .[0].inputSHA256==.[1].inputSHA256 and .[0].sceneSHA256!=.[1].sceneSHA256 and .[0].recordedPose==.[1].recordedPose and all(.[]; .teacherActionClass==1)' "$out/rows.jsonl" > /dev/null
jq -s '{passed:true,episodes:length,identicalActorInputs:true,differentCaseFiles:true,identicalStartingPose:true,bothCoverageLabelsForwardStraight:true,teacherLayoutMatchesCorpus:(all(.[]; .teacherLayoutSHA256 as $layout | all(.matchingCorpusLabels[]; .trainingLayoutSHA256==$layout))),oracleLabelsForSameCases:[.[].matchingCorpusLabels[]],teacherUsesPrivilegedGeometry:true,searchGoalAuditDidNotReadUnseenBrick:true,detectorIsNotActorRecognition:true,teacherAssistedOnly:true,notPolicyPerformance:true,rows:.}' "$out/rows.jsonl" > "$out/summary.json"
echo 'Matched the two coverage-teacher examples to conflicting corpus observations.'
