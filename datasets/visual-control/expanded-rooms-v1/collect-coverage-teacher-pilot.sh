#!/usr/bin/env bash
# Exploratory teacher-controlled trips after one student action. Success here
# is teacher assistance, never an autonomous student success or dataset merge.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
root="$project/build/flex/sim/expanded-rooms-v1/large-model-v1"
fixture="$root/coverage-teacher-counterfactual-v1"
runtime="$fixture/runtime"
policy="$root/expanded-236-mirrored"
out="${PUPPYBOT_COVERAGE_PILOT_OUT:?New output directory required}"
[[ ! -e "$out" ]];mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
audit="$project/datasets/visual-control/expanded-rooms-v1/audit-coverage-teacher.sh"
audit_jq="$project/datasets/visual-control/expanded-rooms-v1/audit-coverage-teacher.jq"
sha256sum "$runtime/build/flex/control/control" "$runtime/build/flex/control/simulator" "$policy/weights.bin" "$policy/policy" "$policy/receipt.json" "$audit" "$audit_jq" "$fixture"/catalog/{0,1}/{case.json,environment.bin,layout.json} > "$out/inputs.sha256"
sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1 PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
cd "$runtime"
./build/flex/control/control correct --policy "$policy" --scene-catalog "$fixture/catalog" --output "$out/runs" --episodes 2 --validation 1 --rollin 1 --rollin-min 1 --horizon 300 --seed 2026000 --label-rollin --allow-incomplete --coverage-teacher --large-model > "$out/collect.log" 2>&1
./build/flex/control/control verify-data --run "$out/runs" --data "$out/runs/data.bin" --output "$out/verified" --allow-incomplete --large-model > "$out/verify.log" 2>&1
jq -e '.passed and .episodes==2 and .studentRollinCommandsReplayed==2 and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .denseOracleLabels and .taskEventHintAbsent and (.incompleteEpisodesClaimedSuccessful|not)' "$out/verified/result.json" > /dev/null
for i in 0 1;do bash "$audit" "$out/runs/expert-$i" "$out/goal-audit-$i";done
sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
jq -n --slurpfile report "$out/runs/report.json" --slurpfile a "$out/runs/expert-0/result.json" --slurpfile b "$out/runs/expert-1/result.json" --slurpfile audit_a "$out/goal-audit-0/result.json" --slurpfile audit_b "$out/goal-audit-1/result.json" '{passed:true,exploratory:true,episodes:2,studentActions:2,teacherControlledAfterFirstAction:true,teacherCompleted:$report[0].teacherCompleted,found:([$a[0],$b[0]]|map(select(.found))|length),returns:([$a[0],$b[0]]|map(select(.success))|length),goalAudits:[$audit_a[0],$audit_b[0]],datasetAutomaticallyAdmitted:false,studentAutonomousSuccessClaimed:false}' > "$out/summary.json"
echo 'Coverage-teacher pilot completed and was independently checked.'
