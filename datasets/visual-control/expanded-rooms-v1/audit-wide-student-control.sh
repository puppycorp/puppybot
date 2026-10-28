#!/usr/bin/env bash
# Independently check that every recorded action was student-controlled.
set -euo pipefail
collection="$(realpath "${1:?Student collection required}")"
out="$(realpath -m "${2:?New output directory required}")";[[ ! -e "$out" ]];mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
while [[ ! -f "$collection/run.exit" ]];do [[ -f "$collection/run.pid" ]] && kill -0 "$(< "$collection/run.pid")" || { echo 'Collection ended without a status.' >&2;exit 1; };sleep 20;done
[[ "$(< "$collection/run.exit")" == 0 ]]
expected="$(jq -er '.studentRollinActionsReplayed | select(type=="number" and .>=8 and .<=2400 and floor==.)' "$collection/summary.json")"
jq -e '.passed and .episodes==8 and .fullyStudentControlled and .teacherLabelsTrainingOnly and (.automaticMerge|not)' "$collection/summary.json" > /dev/null
sha256sum "$collection/summary.json" "$collection/verified/result.json" > "$out/inputs.sha256"
total=0
for ((index=0;index<8;index++));do
    run="$collection/runs/expert-$index";steps="$(wc -l < "$run/decisions.jsonl")"
    jq -e --argjson steps "$steps" '.studentStartAction==0 and .scheduledRollinActions==300 and .studentActions==$steps and .studentActions>=1 and .studentActions<=300' "$run/supervision.json" > /dev/null
    jq -e --argjson steps "$steps" '.steps==$steps' "$run/result.json" > /dev/null
    sha256sum "$run/decisions.jsonl" "$run/supervision.json" "$run/result.json" >> "$out/inputs.sha256"
    total=$((total+steps))
done
[[ "$total" == "$expected" ]]
sha256sum -c "$out/inputs.sha256" > "$out/integrity.log"
jq -n --argjson actions "$total" '{passed:true,episodes:8,studentControlledActions: $actions,teacherTakeoverAbsent:true,trainingOnlyTeacherLabels:true,independentPhysicsReplayNotPerformed:true}' > "$out/summary.json"
echo 'All recorded actions were student-controlled; physical replay was not performed.'
