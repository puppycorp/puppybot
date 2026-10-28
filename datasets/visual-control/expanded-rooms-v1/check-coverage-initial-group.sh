#!/usr/bin/env bash
# Re-query coverage labels in original scenes, with no student inference.
set -euo pipefail
audit="$(realpath "${1:?Conflict scene audit required}")"
group="${2:?Conflict group index required}"
query="$(realpath "${3:?Coverage query executable required}")"
runtime="$(realpath "${4:?Frozen simulator runtime required}")"
out="$(realpath -m "${5:?New output directory required}")"
[[ "$group" =~ ^[0-9]+$ && ! -e "$out" ]]
mkdir -p "$out/scenes" "$out/queries"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
printf '%s\n' "$BASHPID" > "$out/run.pid"
sim="$runtime/build/flex/control/simulator"; model="$runtime/build/flex/sim/puppybot.bin"
[[ -x "$query" && -x "$sim" && -s "$model" ]]
jq -e '.passed and .actorInputsMatched and .sceneMetadataEvaluationOnly' "$audit" > /dev/null
jq -e --argjson group "$group" 'any(.groups[]; .group==$group and .allHaveOneBlock and .allSearch and (.startPoses|length)==1 and (.rows|length)>1)' "$audit" > /dev/null
input="$(jq -er --argjson group "$group" '.groups[]|select(.group==$group)|.rows[0].inputSHA256' "$audit")"
[[ "$input" =~ ^[0-9a-f]{64}$ ]]
sha256sum "$audit" "$query" "$sim" "$model" > "$out/inputs.sha256"
: > "$out/scenes.jsonl"
while IFS=$'\t' read -r index corpus_action recording; do
    [[ "$index" =~ ^[0-9]+$ && "$corpus_action" =~ ^[0-6]$ ]]
    source="$(jq -er '.sourceScene|select(type=="string" and length>0)' "$recording/supervision.json")"
    source="$(realpath -e "$source")"
    cmp "$source/case.json" "$recording/scene/case.json"
    cmp "$source/environment.bin" "$recording/scene/environment.bin"
    jq -e '(.rooms|type)=="array" and (.rooms|length)>0 and (.startRoom|type)=="number"' "$source/layout.json" > /dev/null
    scene="$out/scenes/$index"; mkdir "$scene"
    cp "$source/case.json" "$source/environment.bin" "$source/layout.json" "$scene/"
    sha256sum "$recording/supervision.json" "$recording/scene/case.json" "$recording/scene/environment.bin" "$source/layout.json" "$scene/case.json" "$scene/environment.bin" "$scene/layout.json" >> "$out/inputs.sha256"
    jq -n --argjson episode "$index" --argjson corpusAction "$corpus_action" --arg recording "$recording" --arg source "$source" '{episode:$episode,corpusActionClass:$corpusAction,recording:$recording,sourceScene:$source}' >> "$out/scenes.jsonl"
done < <(jq -r --argjson group "$group" '.groups[]|select(.group==$group)|.rows[]|[.episode,.actionClass,.recording]|@tsv' "$audit")
sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
: > "$out/rows.jsonl"
while IFS=$'\t' read -r index corpus_action; do
    (cd "$runtime"; LIBGL_ALWAYS_SOFTWARE=1 "$query" "$sim" "$out/scenes/$index" "$out/queries/$index") > "$out/$index.log" 2>&1
    result="$out/queries/$index/result.json"
    jq -e --arg input "$input" '.actorInputSHA256==$input and .actorInputsUnchanged and .teacherLabelOnly and .teacherUsesPrivilegedGeometry and (.autonomousSuccessClaimed|not) and .source=="coverage" and (.actionClass>=0 and .actionClass<7)' "$result" > /dev/null
    jq -n --argjson episode "$index" --argjson original "$corpus_action" --slurpfile result "$result" '{episode:$episode,corpusActionClass:$original,coverageActionClass:$result[0].actionClass,action:$result[0].action,coverageIndex:$result[0].coverageIndex,goal:$result[0].goal,actorInputSHA256:$result[0].actorInputSHA256,initialPose:$result[0].initialPose}' >> "$out/rows.jsonl"
done < <(jq -r '[.episode,.corpusActionClass]|@tsv' "$out/scenes.jsonl")
sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
jq -s --arg input "$input" --argjson group "$group" '
  (map(.corpusActionClass)|group_by(.)|map({actionClass:.[0],count:length})) as $original |
  (map(.coverageActionClass)|group_by(.)|map({actionClass:.[0],count:length})) as $coverage |
  {passed:true,group:$group,actorInputSHA256:$input,episodes:length,originalActionCounts:$original,coverageActionCounts:$coverage,matchingOriginalLabels:(map(select(.corpusActionClass==.coverageActionClass))|length),sameCoverageLabel:($coverage|length==1),actorInputsMatched:true,originalSceneAndLayoutUsed:true,teacherUsesPrivilegedGeometry:true,teacherLabelsOnly:true,autonomousSuccessClaimed:false,rows:.}' "$out/rows.jsonl" > "$out/summary.json"
echo 'Queried the coverage teacher independently on the original conflicting scenes.'
