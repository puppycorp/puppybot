#!/usr/bin/env bash
set -euo pipefail

project="${PUPPYBOT_PROJECT:?Project root is required}"
base="$project/build/flex/sim/expanded-rooms-v1"
root="$base/correction-probe-v1"
benchmark="$base/unseen-benchmark-v2"
trap 'status=$?; printf "%s\n" "$status" > "$root/run.exit"' EXIT
printf '%s\n' "$BASHPID" > "$root/run.pid"
cd "$project"
/usr/bin/sha256sum -c "$root/inputs.sha256" > "$root/integrity-before.log"
/usr/bin/jq -e '.exploratory and .sourceIndices==[136,140,144,148,152,156,196,197] and .fittingHistories==6 and .validationHistories==2 and .completeSourceSequencesPreserved' "$root/subset/report.json" > /dev/null
/usr/bin/jq -e '.passed and .episodes==8 and .actorInputsUnchanged' "$root/subset/preflight.json" > /dev/null
[[ "$(/usr/bin/sha256sum "$root/initial/weights.bin" | /usr/bin/cut -d' ' -f1)" == c71a7588ad40b5e41cef15e6789f663844aa3711ca604fa89e4c10e5ba5f3560 ]]
/usr/bin/jq -e '.auditPassed and .recordingCompleted and (.found|not)' "$benchmark/student/16/benchmark-row.json" > /dev/null
export PATH="$root/native-path"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1
cd "$root/runtime"
./build/flex/control/control verify-data --run "$root/subset" --data "$root/subset/data.bin" --output "$root/verified" > "$root/verified.log" 2>&1
/usr/bin/jq -e '.passed and .episodes==8 and .datasetEpisodes==8 and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .executedCommandsMatchRecordings and .denseOracleLabels and .taskEventHintAbsent' "$root/verified/result.json" > /dev/null
./build/flex/control/control train --initial-policy "$root/initial" --data "$root/subset/data.bin" --output "$root/model" --epochs 20 --batch 2 --learning-rate-micros 100 --seed 197 --checkpoint-every 1 --event-aux --target-heatmap "$root/subset/targets" --heat-actor --heat-stop-gradient > "$root/train.log" 2>&1
/usr/bin/cmp "$root/initial/weights.bin" "$root/model/initial.bin"
./build/flex/control/forward-tests "$root/model" "$root/subset/data.bin" "$root/forward" > "$root/forward.log" 2>&1
/usr/bin/jq -e '.passed and .logitMaxAbsError==0 and .memoryMaxAbsError==0 and .resetBitIdentical' "$root/forward/result.json" > /dev/null
for epoch in 1 5 10 20;do
    "$root/publish" "$root/model/epoch-$epoch.bin" "$root/subset/data.bin" "$root/model/initial.bin" "$root/policy-$epoch" "$epoch" "$root/subset/targets" > "$root/publish-$epoch.log" 2>&1
done
fit="$root/subset/expert-4";heldout="$benchmark/student/16/9960016"
/usr/bin/jq -e '.action==[0,0] and .state.trainingOracle.enabled and ((.state.trainingOracle.label[0]-0.6)|fabs)<0.001 and .state.trainingOracle.label[1]==1' < <(/usr/bin/head -1 "$fit/decisions.jsonl") > /dev/null
for query in fitting heldout;do
    run="$fit";if [[ "$query" == heldout ]];then run="$heldout";fi
    frame="$(/usr/bin/jq -r '.totalSteps' "$run/initial.json")"
    for epoch in initial 1 5 10 20;do
        policy="$root/initial";if [[ "$epoch" != initial ]];then policy="$root/policy-$epoch";fi
        "$root/frame-probe" "$policy" "$run/actor-$frame.rgb" "$run/actor-$frame.feedback" "$root/probe-$query-$epoch" > "$root/probe-$query-$epoch.log" 2>&1
    done
    /usr/bin/jq -e '.actionClass==6 and .action==[0,0] and .zeroRecurrentState' "$root/probe-$query-initial/result.json" > /dev/null
done
cd "$project"
/usr/bin/sha256sum -c "$root/inputs.sha256" > "$root/integrity-after.log"
/usr/bin/jq -n --slurpfile fi "$root/probe-fitting-initial/result.json" --slurpfile f1 "$root/probe-fitting-1/result.json" --slurpfile f5 "$root/probe-fitting-5/result.json" --slurpfile f10 "$root/probe-fitting-10/result.json" --slurpfile f20 "$root/probe-fitting-20/result.json" --slurpfile hi "$root/probe-heldout-initial/result.json" --slurpfile h1 "$root/probe-heldout-1/result.json" --slurpfile h5 "$root/probe-heldout-5/result.json" --slurpfile h10 "$root/probe-heldout-10/result.json" --slurpfile h20 "$root/probe-heldout-20/result.json" '{exploratory:true,selection:"subset selected after observing development failures",notAutonomousPerformance:true,oracleFittingAction:[0.6,1],fitting:{initial:$fi[0],epoch1:$f1[0],epoch5:$f5[0],epoch10:$f10[0],epoch20:$f20[0]},heldout:{initial:$hi[0],epoch1:$h1[0],epoch5:$h5[0],epoch10:$h10[0],epoch20:$h20[0]},retainedPolicyOverwritten:false}' > "$root/results.json"
echo 'Exploratory correction fine-tuning and single-frame probes completed; episode performance remains untested.'
