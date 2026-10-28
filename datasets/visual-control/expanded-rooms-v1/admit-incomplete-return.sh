#!/usr/bin/env bash
# Admit a verified copy of the retained incomplete return pair, never its original.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
base="$project/build/flex/sim/expanded-rooms-v1";root="$base/large-model-v1"
old="$root/wide-return-admission-v1";cohort="$root/wide-return-cohort-v1";source="$cohort/worker-0/runs";replay="$root/incomplete-return-replay-test-v1";goals="$root/incomplete-return-goal-audit-v1"
runtime="$root/incomplete-return-runtime-v1/runtime";bin="$root/source/admission-cohort-v3/bin";survey="$base/return-labels-v1/survey";prepare="$root/empty-target-build-v2/prepare";merge_targets="$root/empty-target-build-v2/merge-targets"
out="${PUPPYBOT_INCOMPLETE_RETURN_ADMISSION_OUT:?New output directory required}"
[[ ! -e "$out" ]];mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
for job in "$old/run" "$cohort/run";do [[ "$(< "$job.exit")" == 0 ]];done
jq -e '.complete and .rows[0].reason=="collection_failed" and .rows[0].partialArtifactsRetained and (.automaticMerge|not)' "$cohort/summary.json" > /dev/null
old_data="$old/expanded/data.bin";new_data="$replay/runs/data.bin";old_sha="$(sha256sum "$old_data" | cut -d' ' -f1)";new_sha="$(sha256sum "$new_data" | cut -d' ' -f1)"
jq -e --arg sha "$old_sha" '.passed and .episodes==352 and .fittingHistories==239 and .validationHistories==113 and .dataSHA256==$sha and .existingDataBytePreserved and .existingTargetsBytePreserved and .newHistoriesIndependentlyAudited and .teacherLabelsTrainingOnly and .actorInputsUnchanged' "$old/coverage.json" > /dev/null
jq -e --arg sha "$new_sha" '.passed and .episodes==2 and .datasetEpisodes==2 and .dataSHA256==$sha and .successfulEpisodes==1 and .incompleteEpisodes==1 and .studentPolicies256==2 and .studentRollinCommandsReplayed==96 and .studentRollinMaxAbsError==0 and .denseOracleLabels and .datasetInputsMatchActualRGBAndOwnFeedback and .executedCommandsMatchRecordings and .preActionAlignmentChecked and .zeroPaddingChecked and .taskEventHintAbsent and (.incompleteEpisodesClaimedSuccessful|not)' "$replay/verified/result.json" > /dev/null
sha256sum -c "$replay/source-inputs.sha256" > "$out/source-integrity-before.log"
cmp "$source/data.partial.bin" "$new_data"
for i in 0 1;do
    original="$source/expert-$i";run="$replay/runs/expert-$i";reason=horizon;if (( i==1 ));then reason=success;fi
    jq -n -e --slurpfile original "$original/supervision.json" --slurpfile derived "$run/supervision.json" --arg reason "$reason" '($derived[0] | del(.allowIncomplete,.recordedHorizon,.terminationReason))==$original[0] and $derived[0].allowIncomplete and $derived[0].recordedHorizon==354 and $derived[0].terminationReason==$reason' > /dev/null
    diff -qr --exclude=supervision.json "$original" "$run" > "$out/episode-$i-copy-check.log"
    jq -e '.passed and .oracleLabelsMatched and .brickPositionNotReadBySearchReconstruction and (.actorInputsChecked|not)' "$goals/$i/result.json" > /dev/null
    sha256sum -c "$goals/$i/inputs.sha256" > "$out/goal-$i-integrity.log"
done
for ((i=0;i<352;i++));do for file in case.json environment.bin;do sha256sum "$old/expanded/expert-$i/scene/$file" >> "$out/prior-scenes.sha256";done;done
for spec in diverse-development-v1:8 wide-heading-development-v1:8;do parent="$root/${spec%:*}";count="${spec#*:}";[[ "$(< "$parent/run.exit")" == 0 ]];for ((i=0;i<count;i++));do for file in case.json environment.bin;do sha256sum "$parent/catalog/$i/$file" >> "$out/prior-scenes.sha256";done;done;done
cut -d' ' -f1 "$out/prior-scenes.sha256" > "$out/prior-hashes.txt"
for i in 0 1;do for file in case.json environment.bin;do digest="$(sha256sum "$replay/runs/expert-$i/scene/$file" | cut -d' ' -f1)";status=0;rg -Fxq "$digest" "$out/prior-hashes.txt" || status=$?;if (( status==0 ));then echo 'Retained return scene duplicates current corpus or development.' >&2;exit 1;fi;if (( status!=1 ));then exit "$status";fi;printf '%s\n' "$digest" >> "$out/prior-hashes.txt";done;done
sha256sum "$bin"/* "$runtime/build/flex/control/control" "$runtime/build/flex/control/simulator" "$survey" "$prepare" "$merge_targets" "$old_data" "$old/targets/targets.bin" "$old/targets/receipt.json" "$old/coverage.json" "$new_data" "$replay/verified/result.json" "$replay/source-inputs.sha256" "$goals"/{0,1}/{result.json,inputs.sha256} > "$out/inputs.sha256"
sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
mkdir "$out/labels"
"$survey" "$new_data" "$replay/runs" "$out/labels/survey.json" 2 "$new_sha" "$out/labels/candidates.jsonl" > "$out/labels/survey.log" 2>&1
candidates="$(sha256sum "$out/labels/candidates.jsonl" | cut -d' ' -f1)"
"$prepare" "$new_data" "$replay/runs" "$out/labels/candidates.jsonl" "$out/labels/survey.json" "$new_sha" "$candidates" "$out/labels/targets" --allow-empty-splits > "$out/labels/prepare.log" 2>&1
jq -e --arg sha "$new_sha" '.passed and .sourceDataSHA256==$sha and .allowEmptyCandidateSplits and .projectionAndPixelsIndependentlyRechecked and .actorInputsUnchanged' "$out/labels/targets/receipt.json" > /dev/null
"$bin/merge-dense-many" "$out/expanded" "$old_data" "$old/expanded" "$new_data" "$replay/runs" > "$out/expanded.log"
"$merge_targets" "$out/expanded" "$out/targets" "$old_data" "$old/targets" "$new_data" "$out/labels/targets" > "$out/targets.log"
"$bin/data-preserve-added" "$old_data" "$out/expanded/data.bin" "$out/data-preserved.json"
"$bin/target-preserve-added" "$old/targets/targets.bin" "$out/targets/targets.bin" "$out/targets-preserved.json"
"$bin/preflight-expanded-targets" "$out/expanded/data.bin" "$out/targets" "$out/preflight.json"
for report in "$out/data-preserved.json" "$out/targets-preserved.json";do jq -e '.passed and .existingHistoriesPreserved==352 and .expandedHistories==354 and .expandedFittingHistories==240' "$report" > /dev/null;done
jq -e '.passed and .episodes==354 and .fittingHistories==240 and .validationHistories==114 and .actorInputsUnchanged' "$out/preflight.json" > /dev/null
expanded_sha="$(sha256sum "$out/expanded/data.bin" | cut -d' ' -f1)"
export PATH="$base/unseen-benchmark-v2/native-path:$PATH" XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1 PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
cd "$runtime"
./build/flex/control/control verify-data --run "$out/expanded" --data "$out/expanded/data.bin" --output "$out/audit-fit" --audit-start 239 --audit-count 1 --allow-incomplete --large-model > "$out/audit-fit.log" 2>&1
./build/flex/control/control verify-data --run "$out/expanded" --data "$out/expanded/data.bin" --output "$out/audit-validation" --audit-start 353 --audit-count 1 --allow-incomplete --large-model > "$out/audit-validation.log" 2>&1
jq -e --arg sha "$expanded_sha" '.passed and .datasetEpisodes==354 and .episodes==1 and .dataSHA256==$sha and .studentRollinCommandsReplayed==36 and .incompleteEpisodes==1 and .successfulEpisodes==0 and .studentRollinMaxAbsError==0 and (.incompleteEpisodesClaimedSuccessful|not)' "$out/audit-fit/result.json" > /dev/null
jq -e --arg sha "$expanded_sha" '.passed and .datasetEpisodes==354 and .episodes==1 and .dataSHA256==$sha and .studentRollinCommandsReplayed==60 and .incompleteEpisodes==0 and .successfulEpisodes==1 and .studentRollinMaxAbsError==0' "$out/audit-validation/result.json" > /dev/null
sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
sha256sum -c "$out/prior-scenes.sha256" > "$out/prior-scenes-after.log"
sha256sum -c "$replay/source-inputs.sha256" > "$out/source-integrity-after.log"
jq -n --arg old "$old_sha" --arg sha "$expanded_sha" '{passed:true,episodes:354,fittingHistories:240,validationHistories:114,addedReturnHistories:2,incompleteAddedEpisodes:1,studentReturnActionsReplayed:96,oldDataSHA256:$old,dataSHA256:$sha,existingDataBytePreserved:true,existingTargetsBytePreserved:true,newHistoriesIndependentlyAudited:true,teacherSearchGoalsReconstructed:true,teacherLabelsTrainingOnly:true,actorInputsUnchanged:true,teacherAssisted:true,incompleteEpisodesClaimedSuccessful:false,autonomousWholeEpisodeSuccessClaimed:false,automaticPromotion:false}' > "$out/coverage.json"
echo 'A retained incomplete return and its companion were verified and admitted without modifying the original.'
