#!/usr/bin/env bash
# Matched teacher-assisted trips, not a learned-policy evaluation.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
root="$project/build/flex/sim/expanded-rooms-v1/large-model-v1"
baseline="$root/coverage-teacher-cohort-v1"
runtime="$root/coverage-teacher-v2-runtime-v1/runtime"
policy="$root/gated-search-pair-v1/augmented-policy"
auditor="$project/datasets/visual-control/expanded-rooms-v1/audit-coverage-teacher-v2.sh"
audit_jq="$project/datasets/visual-control/expanded-rooms-v1/audit-coverage-teacher-v2.jq"
out="${PUPPYBOT_COVERAGE_TEACHER_V2_OUT:?New output directory required}"
[[ ! -e "$out" ]];mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
while [[ ! -f "$baseline/run.exit" ]];do [[ -f "$baseline/run.pid" ]] && kill -0 "$(< "$baseline/run.pid")" || { echo 'Baseline teacher collection ended without a status.' >&2;exit 1; }; /usr/bin/sleep 20;done
[[ "$(< "$baseline/run.exit")" == 0 ]]
/usr/bin/jq -e '.passed and .episodes==4 and .teacherSearchGoalsReconstructed and .teacherControlledAfterFirstAction and (.studentAutonomousSuccessClaimed|not)' "$baseline/summary.json" > /dev/null
/usr/bin/sha256sum "$runtime/build/flex/control/control" "$runtime/build/flex/control/simulator" "$runtime/build/flex/sim/puppybot.bin" "$policy/weights.bin" "$policy/policy" "$policy/receipt.json" "$auditor" "$audit_jq" "$baseline/summary.json" "$baseline/verified/result.json" "$baseline"/catalog/{0,1,2,3}/{case.json,environment.bin,layout.json} "$baseline"/runs/expert-{0,1,2,3}/{initial.json,result.json,decisions.jsonl} > "$out/inputs.sha256"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1 PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
cd "$runtime"
./build/flex/control/control correct --policy "$policy" --output "$out/runs" --scene-catalog "$baseline/catalog" --episodes 4 --validation 2 --rollin 1 --rollin-min 1 --horizon 300 --label-rollin --allow-incomplete --coverage-teacher --seed 1992000 --large-model > "$out/collect.log" 2>&1
./build/flex/control/control verify-data --run "$out/runs" --data "$out/runs/data.bin" --output "$out/verified" --allow-incomplete --large-model > "$out/verify.log" 2>&1
/usr/bin/jq -e '.passed and .episodes==4 and .studentRollinCommandsReplayed==4 and .studentRollinMaxAbsError==0 and .denseOracleLabels and .taskEventHintAbsent and (.incompleteEpisodesClaimedSuccessful|not)' "$out/verified/result.json" > /dev/null
for i in 0 1 2 3;do
    old="$baseline/runs/expert-$i";new="$out/runs/expert-$i"
    /usr/bin/bash "$auditor" "$new" "$out/goal-audit-$i"
    for file in case.json environment.bin;do /usr/bin/cmp "$old/scene/$file" "$new/scene/$file";done
    old_frame="$(/usr/bin/jq -r '.totalSteps' "$old/initial.json")";new_frame="$(/usr/bin/jq -r '.totalSteps' "$new/initial.json")"
    /usr/bin/cmp "$old/actor-$old_frame.rgb" "$new/actor-$new_frame.rgb"
    /usr/bin/cmp "$old/actor-$old_frame.feedback" "$new/actor-$new_frame.feedback"
    /usr/bin/head -1 "$old/decisions.jsonl" | /usr/bin/jq -c '.action' > "$out/first-old-$i.json"
    /usr/bin/head -1 "$new/decisions.jsonl" | /usr/bin/jq -c '.action' > "$out/first-new-$i.json"
    /usr/bin/cmp "$out/first-old-$i.json" "$out/first-new-$i.json"
done
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
/usr/bin/jq -n --slurpfile old0 "$baseline/runs/expert-0/result.json" --slurpfile old1 "$baseline/runs/expert-1/result.json" --slurpfile old2 "$baseline/runs/expert-2/result.json" --slurpfile old3 "$baseline/runs/expert-3/result.json" --slurpfile new0 "$out/runs/expert-0/result.json" --slurpfile new1 "$out/runs/expert-1/result.json" --slurpfile new2 "$out/runs/expert-2/result.json" --slurpfile new3 "$out/runs/expert-3/result.json" '
    [$old0[0],$old1[0],$old2[0],$old3[0]] as $old | [$new0[0],$new1[0],$new2[0],$new3[0]] as $new |
    {passed:true,episodes:4,identicalScenesAndInitialActorInputs:true,identicalFirstStudentAction:true,teacherControlledAfterFirstAction:true,studentAutonomousSuccessClaimed:false,rows:[range(0;4) as $i | {episode:$i,layout:(if $i%2==0 then "open" else "two-room" end),baselineFound:$old[$i].found,baselineReturn:$old[$i].success,baselineSteps:$old[$i].steps,baselineLeftStartRoom:$old[$i].leftStartRoom,candidateFound:$new[$i].found,candidateReturn:$new[$i].success,candidateSteps:$new[$i].steps,candidateLeftStartRoom:$new[$i].leftStartRoom}]}' > "$out/comparison.json"
echo 'Matched teacher-assisted room-order comparison completed.'
