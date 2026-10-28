#!/usr/bin/env bash
# Independently replay a saved prefix and query the coverage teacher at its end.
set -euo pipefail
audit="$(realpath "${1:?Prefix label audit required}")"
prefix="${2:?Reported prefix ID required}"
query="$(realpath "${3:?Coverage replay executable required}")"
runtime="$(realpath "${4:?Frozen simulator runtime required}")"
corpus="$(realpath "${5:?Original corpus directory required}")"
out="$(realpath -m "${6:?New output directory required}")"
[[ "$prefix" =~ ^[0-9]+$ && ! -e "$out" ]]; mkdir -p "$out/scenes" "$out/queries"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
printf '%s\n' "$BASHPID" > "$out/run.pid"
sim="$runtime/build/flex/control/simulator"; model="$runtime/build/flex/sim/puppybot.bin"
[[ -x "$query" && -x "$sim" && -s "$model" ]]
jq -e --argjson prefix "$prefix" '.passed and .driveFeedbackNeutralized and .initialMemoryZero and .prefixBytesIndependentlyCompared and any(.conflicts[]; .prefixId==$prefix and (.examples|length)>1)' "$audit" > /dev/null
data="$corpus/data.bin"; expected_data="$(jq -er '.dataSHA256' "$audit")"; [[ "$(sha256sum "$data" | cut -d' ' -f1)" == "$expected_data" ]]
sha256sum "$audit" "$query" "$sim" "$model" "$data" > "$out/inputs.sha256"
: > "$out/examples.jsonl"
while IFS=$'\t' read -r index time original; do
    [[ "$index" =~ ^[0-9]+$ && "$time" =~ ^[0-9]+$ && "$original" =~ ^[0-6]$ ]]
    run="$(realpath -e "$corpus/expert-$index")"
    source="$(jq -er '.sourceScene|select(type=="string" and length>0)' "$run/supervision.json")"; source="$(realpath -e "$source")"
    cmp "$source/case.json" "$run/scene/case.json"; cmp "$source/environment.bin" "$run/scene/environment.bin"
    jq -e '(.rooms|type)=="array" and (.rooms|length)>0 and (.startRoom|type)=="number"' "$source/layout.json" > /dev/null
    scene="$out/scenes/$index"; mkdir "$scene"; cp "$source/case.json" "$source/environment.bin" "$source/layout.json" "$scene/"
    sha256sum "$run/supervision.json" "$run/initial.json" "$run/decisions.jsonl" "$run/scene/case.json" "$run/scene/environment.bin" "$source/layout.json" "$scene/case.json" "$scene/environment.bin" "$scene/layout.json" >> "$out/inputs.sha256"
    # Include exactly the initial observation and every observation after a replayed action.
    initial="$(jq -er '.totalSteps|select(type=="number" and .>=0 and floor==.)' "$run/initial.json")"
    sha256sum "$run/actor-$initial.rgb" "$run/actor-$initial.feedback" >> "$out/inputs.sha256"
    steps="$out/$index-steps.txt"; jq -r --argjson time "$time" 'select(.step!=null)|.step' "$run/decisions.jsonl" | head -n "$time" > "$steps"
    [[ "$(wc -l < "$steps")" == "$time" ]]
    while IFS= read -r step; do [[ "$step" =~ ^[0-9]+$ ]]; sha256sum "$run/actor-$step.rgb" "$run/actor-$step.feedback" >> "$out/inputs.sha256"; done < "$steps"
    jq -n --argjson episode "$index" --argjson time "$time" --argjson original "$original" --arg run "$run" '{episode:$episode,time:$time,corpusActionClass:$original,recording:$run}' >> "$out/examples.jsonl"
done < <(jq -r --argjson prefix "$prefix" '.conflicts[]|select(.prefixId==$prefix)|.examples[]|[.episode,.time,.actionClass]|@tsv' "$audit")
sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
: > "$out/rows.jsonl"
while IFS=$'\t' read -r index time original run; do
    (cd "$runtime"; LIBGL_ALWAYS_SOFTWARE=1 "$query" "$sim" "$out/scenes/$index" "$run" "$data" "$index" "$time" "$out/queries/$index") > "$out/$index.log" 2>&1
    result="$out/queries/$index/result.json"
    jq -e --argjson time "$time" --argjson original "$original" '.corpusActionClass==$original and .decision==$time and .replayedCommands==$time and .observationFramesMatched==($time+1) and .actorInputsUnchanged and .recordedActionsReplayed and .teacherLabelOnly and .teacherUsesPrivilegedGeometry and (.autonomousSuccessClaimed|not) and (.actionClass>=0 and .actionClass<7)' "$result" > /dev/null
    jq -n --argjson episode "$index" --argjson original "$original" --slurpfile result "$result" '{episode:$episode,corpusActionClass:$original,coverageActionClass:$result[0].actionClass,decision:$result[0].decision,source:$result[0].source,goal:$result[0].goal,actorRGBSHA256:$result[0].actorRGBSHA256,observationFramesMatched:$result[0].observationFramesMatched}' >> "$out/rows.jsonl"
done < <(jq -r '[.episode,.time,.corpusActionClass,.recording]|@tsv' "$out/examples.jsonl")
sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
jq -s --argjson prefix "$prefix" '
  (map(.corpusActionClass)|group_by(.)|map({actionClass:.[0],count:length})) as $original |
  (map(.coverageActionClass)|group_by(.)|map({actionClass:.[0],count:length})) as $coverage |
  {passed:true,prefixId:$prefix,episodes:length,originalActionCounts:$original,coverageActionCounts:$coverage,matchingOriginalLabels:(map(select(.corpusActionClass==.coverageActionClass))|length),sameCoverageLabel:($coverage|length==1),recordedActionsAndObservationsReplayed:true,originalSceneAndLayoutUsed:true,teacherUsesPrivilegedGeometry:true,teacherLabelsOnly:true,autonomousSuccessClaimed:false,rows:.}' "$out/rows.jsonl" > "$out/summary.json"
echo 'Coverage teacher queried on independently replayed identical observation prefixes.'
