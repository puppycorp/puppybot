#!/usr/bin/env bash
set -euo pipefail

project="${PUPPYBOT_PROJECT:?Project root is required}"
base="$project/build/flex/sim/expanded-rooms-v1"
root="$base/correction-probe-v1"
reference="$base/unseen-benchmark-v2"
trap 'status=$?; printf "%s\n" "$status" > "$root/screen.exit"' EXIT
printf '%s\n' "$BASHPID" > "$root/screen.pid"
cd "$project"
while [[ ! -f "$root/run.exit" ]];do
    [[ -f "$root/run.pid" ]] && kill -0 "$(< "$root/run.pid")" || { echo 'Probe training disappeared without a terminal status.';exit 1; }
    /usr/bin/sleep 10
done
[[ "$(< "$root/run.exit")" == 0 ]]
/usr/bin/sha256sum -c "$root/screen-inputs.sha256" > "$root/screen-integrity-before.log"
/usr/bin/jq -e '.exploratory and .notAutonomousPerformance and .retainedPolicyOverwritten==false' "$root/results.json" > /dev/null
/usr/bin/cmp "$root/screen-runtime/build/flex/control/simulator" "$reference/runtime/build/flex/control/simulator"
for index in 0 1 2 3 16 17 18 19;do
    layout=$((18+index/16));scene=$((index%16));seed=$((9960000+index))
    for file in case.json environment.bin;do /usr/bin/cmp "$root/scenes/$layout/$scene/$file" "$reference/student/$index/$seed/scene/$file";done
    /usr/bin/jq -e '.auditPassed and .recordingCompleted and .policyWeightsSHA256=="c71a7588ad40b5e41cef15e6789f663844aa3711ca604fa89e4c10e5ba5f3560"' "$reference/student/$index/benchmark-row.json" > /dev/null
done
/usr/bin/jq '[.rows[]|select(.caseIndex<4 or (.caseIndex>=16 and .caseIndex<20))]|{candidate:"initial",episodes:length,auditedEpisodes:(map(select(.auditPassed))|length),physicalReturns:(map(select(.physicalReturned))|length),auditedApproaches:(map(select(.auditPassed and .found))|length),openReturns:(map(select(.layoutId==18 and .physicalReturned))|length),hiddenReturns:(map(select(.layoutId==19 and .physicalReturned))|length),rows:sort_by(.caseIndex)}' "$reference/score-student.json" > "$root/score-screen-reference.json"
/usr/bin/jq -e '.episodes==8 and .auditedEpisodes==8' "$root/score-screen-reference.json" > /dev/null
bash "$root/screen-benchmark.sh" "$root/policy-20" screen-epoch20
/usr/bin/sha256sum -c "$root/screen-inputs.sha256" > "$root/screen-integrity-after.log"
/usr/bin/jq -s '{exploratory:true,selection:"six correction histories selected after observing development failures; epoch 20 fixed before screening",reference:.[0],trained:.[1],allEpisodeAuditsPassed:(.[0].auditedEpisodes==8 and .[1].auditedEpisodes==8 and .[1].auditFailures==0),qualifiesForPromotion:false,retainedPolicyOverwritten:false}' "$root/score-screen-reference.json" "$root/score-screen-epoch20.json" > "$root/screen-comparison.json"
echo 'Exploratory eight-case correction screen completed; it is not a promotion test.'
