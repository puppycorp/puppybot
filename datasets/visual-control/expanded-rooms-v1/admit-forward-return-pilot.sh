#!/usr/bin/env bash
# Build an experimental corpus with four replayed forward-return demonstrations.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
base="$project/build/flex/sim/expanded-rooms-v1";root="$base/large-model-v1"
old="$root/incomplete-return-admission-v1";wide="$root/forward-return-teacher-comparison-v1";known="$root/forward-return-known-comparison-v1"
runtime="$root/incomplete-return-runtime-v1/runtime";bin="$root/source/admission-cohort-v3/bin";survey="$base/return-labels-v1/survey";prepare="$root/empty-target-build-v2/prepare";merge_targets="$root/empty-target-build-v2/merge-targets"
out="${PUPPYBOT_FORWARD_RETURN_ADMISSION_OUT:?New output directory required}"
[[ ! -e "$out" ]];mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
for job in "$old/run" "$wide/run" "$known/run";do [[ "$(< "$job.exit")" == 0 ]];done
old_data="$old/expanded/data.bin";old_sha="$(sha256sum "$old_data" | cut -d' ' -f1)"
jq -e --arg sha "$old_sha" '.passed and .episodes==354 and .fittingHistories==240 and .validationHistories==114 and .dataSHA256==$sha and .newHistoriesIndependentlyAudited and .teacherLabelsTrainingOnly and .actorInputsUnchanged and (.automaticPromotion|not)' "$old/coverage.json" > /dev/null
for source in "$wide" "$known";do
    jq -e '.complete and .episodes==2 and .identicalSearchPrefixes and .teacherAssisted and .teacherSearchGoalsReconstructed and (.autonomousWholeEpisodeSuccessClaimed|not) and (.automaticMerge|not)' "$source/comparison.json" > /dev/null
    data="$source/forward/packed/data.bin";sha="$(sha256sum "$data" | cut -d' ' -f1)"
    jq -e --arg sha "$sha" '.passed and .episodes==2 and .datasetEpisodes==2 and .studentPolicies256==2 and .studentRollinCommandsReplayed==2 and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .executedCommandsMatchRecordings and .denseOracleLabels and .preActionAlignmentChecked and .zeroPaddingChecked and .taskEventHintAbsent and .dataSHA256==$sha and (.incompleteEpisodesClaimedSuccessful|not)' "$source/forward/verified/result.json" > /dev/null
    sha256sum -c "$source/inputs.sha256" > "$out/$(basename "$source")-integrity-before.log"
    for i in 0 1;do jq -e '.passed and .brickPositionNotReadBySearchReconstruction and .oracleLabelsMatched' "$source/forward/goal-audit-$i/result.json" > /dev/null;done
done
# These scenes already occur in the corpus; verify that each reused scene is
# in the same split and matches both exact geometry files. This is not a novel
# scene or held-out evaluation.
for spec in "$wide:0:239" "$wide:1:352" "$known:0:213" "$known:1:328";do
    source="${spec%%:*}";rest="${spec#*:}";index="${rest%%:*}";original="${rest##*:}"
    if (( index==0 ));then (( original<240 ));else (( original>=240 ));fi
    for file in case.json environment.bin;do cmp "$source/catalog/$index/$file" "$old/expanded/expert-$original/scene/$file";done
done
sha256sum "$bin"/* "$runtime/build/flex/control/control" "$survey" "$prepare" "$merge_targets" "$old_data" "$old/targets/targets.bin" "$old/targets/receipt.json" "$old/coverage.json" "$wide/comparison.json" "$wide/forward/packed/data.bin" "$wide/forward/verified/result.json" "$known/comparison.json" "$known/forward/packed/data.bin" "$known/forward/verified/result.json" > "$out/inputs.sha256"
sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
old_input="$old_data";old_runs="$old/expanded";old_targets="$old/targets"
for kind in wide known;do
    source="$wide";if [[ "$kind" == known ]];then source="$known";fi
    work="$out/$kind";mkdir -p "$work/labels";data="$source/forward/packed/data.bin";runs="$source/forward/runs";sha="$(sha256sum "$data" | cut -d' ' -f1)"
    "$survey" "$data" "$runs" "$work/labels/survey.json" 2 "$sha" "$work/labels/candidates.jsonl" > "$work/labels/survey.log" 2>&1
    candidates="$(sha256sum "$work/labels/candidates.jsonl" | cut -d' ' -f1)"
    "$prepare" "$data" "$runs" "$work/labels/candidates.jsonl" "$work/labels/survey.json" "$sha" "$candidates" "$work/labels/targets" --allow-empty-splits > "$work/labels/prepare.log" 2>&1
    jq -e --arg sha "$sha" '.passed and .sourceDataSHA256==$sha and .allowEmptyCandidateSplits and .projectionAndPixelsIndependentlyRechecked and .actorInputsUnchanged' "$work/labels/targets/receipt.json" > /dev/null
    "$bin/merge-dense-many" "$work/expanded" "$old_input" "$old_runs" "$data" "$runs" > "$work/expanded.log"
    "$merge_targets" "$work/expanded" "$work/targets" "$old_input" "$old_targets" "$data" "$work/labels/targets" > "$work/targets.log"
    "$bin/data-preserve-added" "$old_input" "$work/expanded/data.bin" "$work/data-preserved.json"
    "$bin/target-preserve-added" "$old_targets/targets.bin" "$work/targets/targets.bin" "$work/targets-preserved.json"
    expected=354;expanded=356;fit=241;if [[ "$kind" == known ]];then expected=356;expanded=358;fit=242;fi
    for report in "$work/data-preserved.json" "$work/targets-preserved.json";do jq -e --argjson old "$expected" --argjson n "$expanded" --argjson fit "$fit" '.passed and .existingHistoriesPreserved==$old and .expandedHistories==$n and .expandedFittingHistories==$fit' "$report" > /dev/null;done
    old_input="$work/expanded/data.bin";old_runs="$work/expanded";old_targets="$work/targets"
done
"$bin/data-preserve-added" "$old_data" "$out/known/expanded/data.bin" "$out/old-data-preserved.json"
"$bin/target-preserve-added" "$old/targets/targets.bin" "$out/known/targets/targets.bin" "$out/old-targets-preserved.json"
"$bin/preflight-expanded-targets" "$out/known/expanded/data.bin" "$out/known/targets" "$out/preflight.json"
for report in "$out/old-data-preserved.json" "$out/old-targets-preserved.json";do jq -e '.passed and .existingHistoriesPreserved==354 and .expandedHistories==358 and .expandedFittingHistories==242' "$report" > /dev/null;done
jq -e '.passed and .episodes==358 and .fittingHistories==242 and .validationHistories==116 and .actorInputsUnchanged' "$out/preflight.json" > /dev/null
expanded_sha="$(sha256sum "$out/known/expanded/data.bin" | cut -d' ' -f1)"
export PATH="$base/unseen-benchmark-v2/native-path:$PATH" XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1 PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
cd "$runtime"
for index in 240 241 356 357;do
    ./build/flex/control/control verify-data --run "$out/known/expanded" --data "$out/known/expanded/data.bin" --output "$out/audit-$index" --audit-start "$index" --audit-count 1 --allow-incomplete --large-model > "$out/audit-$index.log" 2>&1
    jq -e --arg sha "$expanded_sha" '.passed and .datasetEpisodes==358 and .episodes==1 and .dataSHA256==$sha and .studentPolicies256==1 and .studentRollinCommandsReplayed==1 and .studentRollinMaxAbsError==0 and .denseOracleLabels and .datasetInputsMatchActualRGBAndOwnFeedback and .executedCommandsMatchRecordings and .taskEventHintAbsent and (.incompleteEpisodesClaimedSuccessful|not)' "$out/audit-$index/result.json" > /dev/null
done
jq -e '.incompleteEpisodes==1 and .successfulEpisodes==0' "$out/audit-240/result.json" > /dev/null
for index in 241 356 357;do jq -e '.incompleteEpisodes==0 and .successfulEpisodes==1' "$out/audit-$index/result.json" > /dev/null;done
sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
for source in "$wide" "$known";do sha256sum -c "$source/inputs.sha256" > "$out/$(basename "$source")-integrity-after.log";done
jq -n --arg old "$old_sha" --arg sha "$expanded_sha" '{passed:true,episodes:358,fittingHistories:242,validationHistories:116,addedTeacherHistories:4,incompleteAddedEpisodes:1,studentActionsReplayed:4,oldDataSHA256:$old,dataSHA256:$sha,reusedScenesSameSplit:true,existingDataBytePreserved:true,existingTargetsBytePreserved:true,newHistoriesIndependentlyAudited:true,teacherSearchGoalsReconstructed:true,teacherLabelsTrainingOnly:true,actorInputsUnchanged:true,teacherAssisted:true,incompleteEpisodesClaimedSuccessful:false,autonomousWholeEpisodeSuccessClaimed:false,automaticPromotion:false}' > "$out/coverage.json"
echo 'Four forward-return teacher histories replayed and admitted to an experimental corpus.'
