#!/usr/bin/env bash
# Check the actual initial camera tensors and feedback of two scored policies.
set -euo pipefail
baseline="$(realpath "${1:?Baseline benchmark required}")";candidate="$(realpath "${2:?Candidate benchmark required}")"
out="$(realpath -m "${3:?New output directory required}")";[[ ! -e "$out" ]];mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
[[ "$(< "$baseline/run.exit")" == 0 && "$(< "$candidate/run.exit")" == 0 ]]
for benchmark in "$baseline" "$candidate";do jq -e '.passed and .episodes==8 and .auditedEpisodes==8 and ([.rows[].caseIndex]|sort)==[range(0;8)] and all(.rows[];.auditPassed and (.suppliedMap|not) and (.taskEventHint|not))' "$benchmark/score.json" > /dev/null;done
sha256sum "$baseline/score.json" "$candidate/score.json" > "$out/inputs.sha256"
for ((index=0;index<8;index++));do
    arow="$(jq -c --argjson index "$index" '.rows[]|select(.caseIndex==$index)' "$baseline/score.json")";brow="$(jq -c --argjson index "$index" '.rows[]|select(.caseIndex==$index)' "$candidate/score.json")"
    jq -n -e --argjson a "$arow" --argjson b "$brow" '$a.seed==$b.seed and $a.layoutId==$b.layoutId and $a.startPose==$b.startPose' > /dev/null
    seed="$(jq -er '.seed|select(type=="number" and floor==.)' <<< "$arow")";a="$baseline/$index/$seed";b="$candidate/$index/$seed"
    step="$(jq -er '.step|select(type=="number" and .>=0 and floor==.)' "$a/initial.json")";[[ "$step" == "$(jq -er '.step|select(type=="number" and .>=0 and floor==.)' "$b/initial.json")" ]]
    for pair in "$baseline/$index/verified/result.json" "$candidate/$index/verified/result.json";do jq -e '.passed and .commandReplayMaxAbsError==0 and .taskEventHintAbsent' "$pair" > /dev/null;sha256sum "$pair" >> "$out/inputs.sha256";done
    for file in case.json environment.bin;do cmp "$a/scene/$file" "$b/scene/$file";sha256sum "$a/scene/$file" "$b/scene/$file" >> "$out/inputs.sha256";done
    for suffix in rgb feedback;do cmp "$a/actor-$step.$suffix" "$b/actor-$step.$suffix";sha256sum "$a/actor-$step.$suffix" "$b/actor-$step.$suffix" >> "$out/inputs.sha256";done
    sha256sum "$a/initial.json" "$b/initial.json" >> "$out/inputs.sha256"
done
sha256sum -c "$out/inputs.sha256" > "$out/integrity.log"
jq -n '{passed:true,episodes:8,sceneFilesIdentical:true,initialActorImagesAndFeedbackIdentical:true,policyReplaysPassed:true,fullTrajectoriesNotClaimedIdentical:true}' > "$out/summary.json"
echo 'Matched episodes have identical initial camera tensors and own feedback.'
