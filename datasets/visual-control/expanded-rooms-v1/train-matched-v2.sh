#!/usr/bin/env bash
set -euo pipefail

project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$project/build/flex/sim/expanded-rooms-v1/matched-training-v2"
expanded="$project/build/flex/sim/expanded-rooms-v1"
unseen="$expanded/unseen-benchmark-v2"
absence="$project/build/flex/sim/target-absence-v1"
labels="$expanded/labels-v2"
old="$project/build/flex/sim/late-search-v1/artifacts-v2/data172/data.bin"
oldlabels="$project/build/flex/sim/memory-pose-v1/target-candidates-v1/targets"
trap 'status=$?; printf "%s\n" "$status" > "$root/run.exit"' EXIT
printf '%s\n' "$BASHPID" > "$root/run.pid"
cd "$project"
for job in "$labels/run" "$unseen/run" "$absence/train";do
    while [[ ! -f "$job.exit" ]];do
        [[ -f "$job.pid" ]] && kill -0 "$(< "$job.pid")" || { echo "Process exited without status: $job";exit 1; }
        /usr/bin/sleep 10
    done
done
[[ "$(< "$labels/run.exit")" == 0 && "$(< "$unseen/run.exit")" == 0 ]]
/usr/bin/jq -e '.allEpisodeAuditsPassed and .episodesPerPolicy==32' "$unseen/comparison.json" > /dev/null
/usr/bin/sha256sum -c "$root/inputs.sha256" > "$root/integrity-before.log"
/usr/bin/sha256sum -c "$unseen/inputs.sha256" > "$root/benchmark-integrity-before.log"
[[ "$(/usr/bin/sha256sum "$old" | /usr/bin/cut -d' ' -f1)" == 05032e0eb2a4a98a7f0146db66195792b2c22fe3bda3138039e9c721bc69b284 ]]
[[ "$(/usr/bin/sha256sum "$oldlabels/targets.bin" | /usr/bin/cut -d' ' -f1)" == 9846229a1a28aa77c7e8653d1bbe14dbe6185c27d90a46b77d68b5e1bf0e5294 ]]
[[ "$(/usr/bin/sha256sum "$root/initial/weights.bin" | /usr/bin/cut -d' ' -f1)" == c71a7588ad40b5e41cef15e6789f663844aa3711ca604fa89e4c10e5ba5f3560 ]]
new="$expanded/admission-v2/data202/data.bin"
newsha="$(/usr/bin/sha256sum "$new" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$newsha" '.passed and .episodes==202 and .sourceDataSHA256==$sha and .actorInputsUnchanged' "$labels/preflight.json" > /dev/null
/usr/bin/jq -e '.passed and .existingHistoriesPreserved==172' "$labels/preserved.json" > /dev/null
export PATH="$root/native-path"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1
cd "$root/runtime"
for arm in old expanded;do
    data="$old";targets="$oldlabels";epochs=40
    if [[ "$arm" == expanded ]];then data="$new";targets="$labels/targets";epochs=34;fi
    ./build/flex/control/control train --initial-policy "$root/initial" --data "$data" --output "$root/$arm" --epochs "$epochs" --batch 2 --learning-rate-micros 100 --seed 197 --checkpoint-every 1 --event-aux --target-heatmap "$targets" --heat-actor --heat-stop-gradient > "$root/$arm.log" 2>&1
    /usr/bin/cmp "$root/initial/weights.bin" "$root/$arm/seed.bin"
    /usr/bin/jq -e --argjson epochs "$epochs" '.heatmapActorGradientDetached and .heatmapActorFeatures and .targetHeatmapAuxiliary and .cameraEventAuxiliary and (.taskFeedback|not) and .epochs==$epochs' "$root/$arm/receipt.json" > /dev/null
    /usr/bin/jq -s --argjson epochs "$epochs" 'length==($epochs+1) and .[-1].epoch==$epochs and .[-1].optimizerSteps==2720' "$root/$arm/curves.jsonl" > /dev/null
done
/usr/bin/cmp "$root/old/initial.bin" "$root/expanded/initial.bin"
/usr/bin/jq -n --slurpfile old "$root/old/curves.jsonl" --slurpfile expanded "$root/expanded/curves.jsonl" '{method:"same initial weights and optimizer steps; differing training sets and shuffle orders",optimizerStepsPerArm:2720,oldEpochs:40,expandedEpochs:34,oldSelectedEpoch:([$old[]|select(.selected)|.epoch]|last),expandedSelectedEpoch:([$expanded[]|select(.selected)|.epoch]|last),runtimeInputs:["TCP RGB","own feedback","recurrent state"],teacherLabelsTrainingOnly:true}' > "$root/training-comparison.json"
cd "$project"
bash "$unseen/benchmark.sh" "$root/old" continued-172
bash "$unseen/benchmark.sh" "$root/expanded" continued-202
/usr/bin/sha256sum -c "$root/inputs.sha256" > "$root/integrity-after.log"
/usr/bin/sha256sum -c "$unseen/inputs.sha256" > "$root/benchmark-integrity-after.log"
[[ "$(/usr/bin/sha256sum "$new" | /usr/bin/cut -d' ' -f1)" == "$newsha" ]]
/usr/bin/jq -s '{selection:"minimum demonstration validation loss, initial checkpoint included",old:.[0],expanded:.[1],allEpisodeAuditsPassed:all(.[]; .completedRecordings==32 and .auditedEpisodes==32 and .auditFailures==0),finalLayoutsStillRequired:true,retainedPolicyOverwritten:false}' "$unseen/score-continued-172.json" "$unseen/score-continued-202.json" > "$root/comparison.json"
echo 'Matched-compute continuation and 32-case episode comparisons complete.'
