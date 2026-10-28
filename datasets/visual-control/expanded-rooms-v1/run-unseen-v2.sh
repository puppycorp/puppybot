#!/usr/bin/env bash
set -euo pipefail

project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$project/build/flex/sim/expanded-rooms-v1/unseen-benchmark-v2"
original="$project/build/flex/sim/expanded-rooms-v1/unseen-benchmark-v1"
accepted="$project/build/flex/sim/expanded-rooms-v1/consumption-match-accepted-v1"
[[ ! -e "$root/run.exit" ]]
trap 'status=$?; printf "%s\n" "$status" > "$root/run.exit"' EXIT
printf '%s\n' "$BASHPID" > "$root/run.pid"
cd "$project"
while [[ ! -f "$original/run.exit" ]];do
    [[ -f "$original/run.pid" ]] && kill -0 "$(< "$original/run.pid")" || { echo 'Previous benchmark disappeared without a terminal status.';exit 1; }
    /usr/bin/sleep 10
done
[[ "$(< "$accepted/run.exit")" == 0 ]]
/usr/bin/sha256sum -c "$root/inputs.sha256" > "$root/integrity-before.log"
/usr/bin/jq -e '.passed and .independentPhysicalAndReplayAuditsPassed and .studentPrefixFramesAndActionsIdentical==120' "$root/consumption-pilot.json" > /dev/null
/usr/bin/jq -e '.passed and .cases==32 and .openLayout==18 and .hiddenLayout==19 and .noPriorOrCohortCaseOrEnvironmentOverlap' "$root/holdout-audit.json" > /dev/null
[[ "$(/usr/bin/sha256sum "$root/policies/baseline/weights.bin" | /usr/bin/cut -d' ' -f1)" == c38fa6cbc57c7a1da996f2c50fa3b2deb251c71c073698ce1269a3e833183ab7 ]]
[[ "$(/usr/bin/sha256sum "$root/policies/student/weights.bin" | /usr/bin/cut -d' ' -f1)" == c71a7588ad40b5e41cef15e6789f663844aa3711ca604fa89e4c10e5ba5f3560 ]]
for layout in 18 19;do for scene in {0..15};do
    casehash="$(/usr/bin/sha256sum "$root/scenes/$layout/$scene/case.json" | /usr/bin/cut -d' ' -f1)"
    envhash="$(/usr/bin/sha256sum "$root/scenes/$layout/$scene/environment.bin" | /usr/bin/cut -d' ' -f1)"
    /usr/bin/jq -e --argjson layout "$layout" --argjson scene "$scene" --arg casehash "$casehash" --arg envhash "$envhash" '[.rows[]|select(.layout==$layout and .scene==$scene and .caseSHA256==$casehash and .environmentSHA256==$envhash)]|length==1' "$root/holdout-audit.json" > /dev/null
done;done
bash "$root/benchmark.sh" "$root/policies/baseline" baseline
bash "$root/benchmark.sh" "$root/policies/student" student
/usr/bin/sha256sum -c "$root/inputs.sha256" > "$root/integrity-after.log"
/usr/bin/jq -s '{selection:"fixed policies selected on prior development data",episodesPerPolicy:32,baseline:.[0],student:.[1],allEpisodeAuditsPassed:all(.[]; .completedRecordings==32 and .auditedEpisodes==32 and .auditFailures==0),reservedFinalStillRequired:true,retainedPolicyOverwritten:false}' "$root/score-baseline.json" "$root/score-student.json" > "$root/comparison.json"
echo 'Matched unseen-layout comparison completed; inspect episode audits and scores.'
