#!/usr/bin/env bash
# Freeze a no-training weight ablation and check its neural outputs.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
root="$project/build/flex/sim/expanded-rooms-v1/large-model-v1"
source="$root/incomplete-return-training-v1/policy";episode="$root/incomplete-return-standard-comparison-v1/candidate/5/9980005"
ablate="${PUPPYBOT_DRIVE_ABLATE_BINARY:?Frozen ablation binary required}"
probe="${PUPPYBOT_DRIVE_ABLATE_PROBE:?Frozen forward probe required}"
capacity="${PUPPYBOT_DRIVE_ABLATE_WAIT_RUN:?Previous GPU job required}"
out="${PUPPYBOT_DRIVE_ABLATE_OUT:?New output directory required}"
[[ ! -e "$out" ]];mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
for job in "$root/incomplete-return-training-v1/run" "$root/incomplete-return-standard-comparison-v1/run";do [[ "$(< "$job.exit")" == 0 ]];done
while [[ ! -f "$capacity.exit" ]];do [[ -f "$capacity.pid" ]] && kill -0 "$(< "$capacity.pid")" || { echo 'Previous GPU job ended without a status.' >&2;exit 1; };sleep 20;done
printf '%s\n' "$(< "$capacity.exit")" > "$out/prior-gpu-status.txt"
source_sha="$(sha256sum "$source/weights.bin" | cut -d' ' -f1)"
jq -e --arg sha "$source_sha" '.weightsSHA256==$sha and .checkpointSHA256==$sha and .memoryWidth==256 and (.taskFeedback|not)' "$source/receipt.json" > /dev/null
jq -e --arg sha "$source_sha" '.passed and .commandReplayMaxAbsError==0 and .weightsSHA256==$sha and .taskEventHintAbsent' "$episode/../verified/result.json" > /dev/null
step="$(jq -er '.step|select(type=="number" and floor==.)' "$episode/initial.json")";rgb="$episode/actor-$step.rgb";feedback="$episode/actor-$step.feedback"
sha256sum "$ablate" "$probe" "$source/weights.bin" "$source/policy" "$source/model.pup" "$source/receipt.json" "$episode/initial.json" "$episode/../verified/result.json" "$rgb" "$feedback" > "$out/inputs.sha256"
find "$source/kernels" -type f -print0 | sort -z | xargs -0 -r sha256sum >> "$out/inputs.sha256"
mkdir "$out/policy";cp "$source/policy" "$source/model.pup" "$out/policy/";cp -a "$source/kernels" "$out/policy/kernels"
"$ablate" "$source/weights.bin" "$out/policy/weights.bin" "$out/ablation.json" > "$out/ablation.log" 2>&1
sha="$(sha256sum "$out/policy/weights.bin" | cut -d' ' -f1)"
jq -e --arg source "$source_sha" --arg sha "$sha" '.passed and .sourceSHA256==$source and .weightsSHA256==$sha and .tensor=="memory.weight_ih_T" and .driveFeedbackValuesZeroed==5 and .bytesZeroed==15360 and .nonzeroBytesChanged>0 and .contactFeedbackPreserved and .otherWeightsPreserved and (.trainingPerformed|not) and (.automaticPromotion|not)' "$out/ablation.json" > /dev/null
first="$(jq -er '.firstByte|select(type=="number" and .>=0 and floor==.)' "$out/ablation.json")";removed="$(jq -er '.bytesZeroed' "$out/ablation.json")"
cmp -n "$first" "$source/weights.bin" "$out/policy/weights.bin";cmp -i "$((first+removed))" "$source/weights.bin" "$out/policy/weights.bin"
dd if="$out/policy/weights.bin" of="$out/zeroed.bin" bs=1 skip="$first" count="$removed" status=none;cmp -n "$removed" "$out/zeroed.bin" /dev/zero
jq --arg sha "$sha" --arg parent "$source_sha" '.weightsSHA256=$sha | .checkpointSHA256=$sha | .postTrainingWeightAblation={parentWeightsSHA256:$parent,driveFeedbackValuesZeroed:5,contactFeedbackPreserved:true,trainingPerformed:false,automaticPromotion:false}' "$source/receipt.json" > "$out/policy/receipt.json"
jq -e --arg sha "$sha" --arg parent "$source_sha" '.weightsSHA256==$sha and .checkpointSHA256==$sha and .postTrainingWeightAblation.parentWeightsSHA256==$parent and (.postTrainingWeightAblation.trainingPerformed|not) and (.taskFeedback|not)' "$out/policy/receipt.json" > /dev/null
"$probe" "$source" "$out/policy" "$rgb" "$feedback" "$out/forward-probe" > "$out/forward-probe.log" 2>&1
jq -e '.passed and .cameraInputUnchanged and .contactInputUnchanged and .initialMemoryIdentical and .outputCount==263 and .originalNeutralVsAblatedError<0.00001 and .ablatedDriveVariationError<0.00001 and .singleFrameOnly and .closedLoopPerformanceNotMeasured' "$out/forward-probe/result.json" > /dev/null
sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
jq -n --arg sha "$sha" --arg parent "$source_sha" '{passed:true,weightsSHA256:$sha,parentWeightsSHA256:$parent,driveFeedbackValuesZeroed:5,contactFeedbackPreserved:true,otherWeightsPreserved:true,singleFrameForwardChecked:true,trainingPerformed:false,closedLoopPerformanceNotMeasured:true,automaticPromotion:false}' > "$out/summary.json"
echo 'Drive-feedback weight ablation frozen and checked on one recorded frame.'
