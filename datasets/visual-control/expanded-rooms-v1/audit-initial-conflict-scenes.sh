#!/usr/bin/env bash
# Relate identical initial actor inputs to recorded scene metadata offline.
set -euo pipefail
conflicts="$(realpath "${1:?Neutral-drive initial-label audit required}")"
corpus="$(realpath "${2:?Corpus directory with expert-N recordings required}")"
out="$(realpath -m "${3:?New output directory required}")"
[[ ! -e "$out" ]]
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
jq -e '.passed and .driveFeedbackNeutralized and .initialMemoryZero and .offlineAnalysisOnly and (.conflicts|type)=="array"' "$conflicts" > /dev/null
sha256sum "$conflicts" > "$out/inputs.sha256"
: > "$out/examples.jsonl"
while IFS=$'\t' read -r group input episode split action; do
    [[ "$group" =~ ^[0-9]+$ && "$episode" =~ ^[0-9]+$ && "$action" =~ ^[0-6]$ && "$input" =~ ^[0-9a-f]{64}$ ]]
    [[ "$split" == fit || "$split" == validation ]]
    run="$(realpath -e "$corpus/expert-$episode")"
    initial="$run/initial.json"; scene="$run/scene/case.json"
    frame="$(jq -er '.totalSteps | select(type=="number" and .>=0 and floor==.)' "$initial")"
    rgb="$run/actor-$frame.rgb"; feedback="$run/actor-$frame.feedback"
    [[ "$(stat -c %s "$rgb")" == 21168 && "$(stat -c %s "$feedback")" == 28 ]]
    # Match the exact input of the neutral-drive model: RGB, five zeros,
    # contact feedback and the already-masked task-event field.
    hash="$( { cat "$rgb"; head -c 20 /dev/zero; tail -c 8 "$feedback"; } | sha256sum | cut -d' ' -f1)"
    [[ "$hash" == "$input" ]]
    sha256sum "$initial" "$scene" "$rgb" "$feedback" >> "$out/inputs.sha256"
    jq -n -e --argjson group "$group" --arg input "$input" --argjson episode "$episode" --arg split "$split" --argjson action "$action" --arg run "$run" --slurpfile initial "$initial" --slurpfile scene "$scene" '
      $initial[0] as $i | $scene[0] as $s | [$s.objects[]? | select(.kind=="block") | .position | select(type=="array" and length>=2 and (.[0]|type)=="number" and (.[1]|type)=="number")] as $targets |
      select(($i.pose|type)=="array" and ($i.pose|length)==3 and ($i.findReturn.phase|type)=="string") |
      {group:$group,inputSHA256:$input,episode:$episode,split:$split,actionClass:$action,recording:$run,sceneId:$s.id,environment:$i.environment.name,startPose:$i.pose,targetPositions:$targets,phase:$i.findReturn.phase,detectorChosen:$i.case.perception.chosen,detectorCount:(if ($i.case.perception.detections|type)=="array" then ($i.case.perception.detections|length) else null end)}' >> "$out/examples.jsonl"
done < <(jq -r '.conflicts | to_entries[] | .key as $group | .value.inputSHA256 as $hash | .value.examples[] | [$group,$hash,.episode,.split,.actionClass] | @tsv' "$conflicts")
sha256sum -c "$out/inputs.sha256" > "$out/integrity.log"
jq -s --slurpfile audit "$conflicts" '
  group_by(.group) | map({group:.[0].group,examples:length,splits:(map(.split)|unique),actionClasses:(map(.actionClass)|unique),sceneIds:(map(.sceneId)|unique),startPoses:(map(.startPose)|unique),targetPositions:(map(.targetPositions)|unique),allHaveOneBlock:(all(.[]; (.targetPositions|length)==1)),allSearch:(all(.[]; .phase=="search")),allDetectorEmpty:(all(.[]; .detectorChosen == -1 and .detectorCount==0)),rows:.}) as $groups |
  {passed:true,dataSHA256:$audit[0].dataSHA256,conflictingGroups:($groups|length),examples:([$groups[].examples]|add // 0),groupsWithDifferentTargetPositions:([$groups[] | select((.targetPositions|length)>1)]|length),groupsWithDifferentStartPoses:([$groups[] | select((.startPoses|length)>1)]|length),groupsWithOneBlockAndSearch:([$groups[] | select(.allHaveOneBlock and .allSearch)]|length),groupsWithEmptySimulatorDetector:([$groups[] | select(.allDetectorEmpty)]|length),actorInputsMatched:true,sceneMetadataEvaluationOnly:true,detectorIsNotActorRecognition:true,causalityNotEstablished:true,groups:$groups}' "$out/examples.jsonl" > "$out/summary.json"
echo 'Matched conflicting initial inputs to recorded scene metadata for offline analysis.'
