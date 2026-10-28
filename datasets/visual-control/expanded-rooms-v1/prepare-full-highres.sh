#!/usr/bin/env bash
set -euo pipefail

project="${PUPPYBOT_PROJECT:?Project root is required}"
base="$project/build/flex/sim/expanded-rooms-v1"
out="$base/highres-full-data-v2"
source="$base/return-admission-v1/merged-7"
labels="$base/return-labels-v1/targets"
[[ ! -e "$out/run.exit" && ! -e "$out/audit" ]]
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
# Avoid competing for GPU memory with training and its episode comparisons.
for name in contact-training-v1 return-training-v1 highres-development-run-v2; do
    while [[ ! -f "$base/$name/run.exit" ]]; do
        [[ -f "$base/$name/run.pid" ]] && kill -0 "$(< "$base/$name/run.pid")" || { echo "$name ended without a terminal status" >&2; exit 1; }
        /usr/bin/sleep 10
    done
done
cd "$project"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1
"$out/control" verify-data --run "$source" --data "$source/data.bin" --output "$out/audit" > "$out/audit.log" 2>&1
/usr/bin/jq -e '.passed and .episodes==236 and .datasetEpisodes==236 and .firstEpisode==0 and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .executedCommandsMatchRecordings and .denseOracleLabels and .preActionAlignmentChecked and .zeroPaddingChecked and .taskEventHintAbsent and .dataSHA256=="74ed59242a4b7df9f9f5732458c23d743cf79f2e56a10b4394703845e9f1f833"' "$out/audit/result.json" > /dev/null
"$out/prepare" "$source/data.bin" "$source" "$out/audit/result.json" "$out/data" > "$out/prepare.log" 2>&1
"$out/verify" "$source/data.bin" "$source" "$out/data" "$out/data/independent-audit.json" > "$out/verify.log" 2>&1
/usr/bin/jq -e '.passed and .episodes==236 and .framesVerified==39294 and .independentSeparableAreaReference and .feedbackAndLabelsIdentical and .taskEventHintAbsent and .zeroPaddingChecked' "$out/data/independent-audit.json" > /dev/null
"$out/retarget" "$source/data.bin" "$labels" "$out/data" "$out/targets" > "$out/retarget.log" 2>&1
/usr/bin/jq -e '.passed and .episodes==236 and .fittingHistories==181 and .validationHistories==55 and .fittingCandidates==4785 and .validationCandidates==1451 and .actorInputsUnchanged' "$out/targets/receipt.json" > /dev/null
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
/usr/bin/jq -n --slurpfile audit "$out/audit/result.json" --slurpfile data "$out/data/independent-audit.json" --slurpfile labels "$out/targets/receipt.json" '{passed:true,episodes:$audit[0].episodes,studentCommandsReplayed:$audit[0].studentRollinCommandsReplayed,framesVerified:$data[0].framesVerified,dataSHA256:$data[0].dataSHA256,targetsSHA256:$labels[0].targetsSHA256,independentVerification:true,taskEventHintAbsent:true,trainingOrEvaluationNotImplied:true}' > "$out/result.json"
echo 'Full 128x128 data conversion and independent verification completed.'
