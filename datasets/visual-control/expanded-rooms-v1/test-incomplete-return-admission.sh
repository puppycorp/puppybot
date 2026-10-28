#!/usr/bin/env bash
# A retained incomplete pair must match its original and remain unsuccessful.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]];mkdir "$out"
mock="$out/mock";base="$mock/build/flex/sim/expanded-rooms-v1";root="$base/large-model-v1";old="$root/wide-return-admission-v1";cohort="$root/wide-return-cohort-v1";source="$cohort/worker-0/runs";replay="$root/incomplete-return-replay-test-v1";goals="$root/incomplete-return-goal-audit-v1";runtime="$root/incomplete-return-runtime-v1/runtime";bin="$root/source/admission-cohort-v3/bin"
mkdir -p "$old/expanded" "$old/targets" "$source" "$replay/runs" "$replay/verified" "$goals" "$runtime/build/flex/control" "$bin" "$base/return-labels-v1" "$root/empty-target-build-v2"
printf '0\n' > "$old/run.exit";printf '0\n' > "$cohort/run.exit";printf 'old data\n' > "$old/expanded/data.bin";printf 'old targets\n' > "$old/targets/targets.bin";printf '{}\n' > "$old/targets/receipt.json"
old_sha="$(sha256sum "$old/expanded/data.bin" | cut -d' ' -f1)"
jq -n --arg sha "$old_sha" '{passed:true,episodes:352,fittingHistories:239,validationHistories:113,dataSHA256:$sha,existingDataBytePreserved:true,existingTargetsBytePreserved:true,newHistoriesIndependentlyAudited:true,teacherLabelsTrainingOnly:true,actorInputsUnchanged:true}' > "$old/coverage.json"
for ((i=0;i<352;i++));do mkdir -p "$old/expanded/expert-$i/scene";for file in case.json environment.bin;do printf 'old %s %s\n' "$i" "$file" > "$old/expanded/expert-$i/scene/$file";done;done
for name in diverse-development-v1 wide-heading-development-v1;do parent="$root/$name";mkdir -p "$parent/catalog";printf '0\n' > "$parent/run.exit";for ((i=0;i<8;i++));do mkdir "$parent/catalog/$i";for file in case.json environment.bin;do printf '%s %s %s\n' "$name" "$i" "$file" > "$parent/catalog/$i/$file";done;done;done
printf '{"complete":true,"rows":[{"reason":"collection_failed","partialArtifactsRetained":true}],"automaticMerge":false}\n' > "$cohort/summary.json"
printf 'partial data\n' > "$source/data.partial.bin";cp "$source/data.partial.bin" "$replay/runs/data.bin";new_sha="$(sha256sum "$replay/runs/data.bin" | cut -d' ' -f1)"
jq -n --arg sha "$new_sha" '{passed:true,episodes:2,datasetEpisodes:2,dataSHA256:$sha,successfulEpisodes:1,incompleteEpisodes:1,studentPolicies256:2,studentRollinCommandsReplayed:96,studentRollinMaxAbsError:0,denseOracleLabels:true,datasetInputsMatchActualRGBAndOwnFeedback:true,executedCommandsMatchRecordings:true,preActionAlignmentChecked:true,zeroPaddingChecked:true,taskEventHintAbsent:true,incompleteEpisodesClaimedSuccessful:false}' > "$replay/verified/result.json"
for i in 0 1;do
    original="$source/expert-$i";run="$replay/runs/expert-$i";mkdir -p "$original/scene" "$run/scene" "$goals/$i"
    for file in case.json environment.bin;do printf 'retained %s %s\n' "$i" "$file" > "$original/scene/$file";cp "$original/scene/$file" "$run/scene/$file";done
    printf '{"studentBeginsAfterConsumption":true,"studentActions":60}\n' > "$original/supervision.json";printf '{}\n' > "$original/decisions.jsonl";printf '{"steps":354}\n' > "$original/result.json"
    reason=horizon;if (( i==1 ));then reason=success;fi
    jq --arg reason "$reason" '.allowIncomplete=true | .recordedHorizon=354 | .terminationReason=$reason' "$original/supervision.json" > "$run/supervision.json"
    cp "$original/decisions.jsonl" "$run/decisions.jsonl";cp "$original/result.json" "$run/result.json"
    printf '{"passed":true,"oracleLabelsMatched":true,"brickPositionNotReadBySearchReconstruction":true,"actorInputsChecked":false}\n' > "$goals/$i/result.json"
    sha256sum "$run/scene/case.json" "$run/scene/environment.bin" "$goals/$i/result.json" > "$goals/$i/inputs.sha256"
done
sha256sum "$source/data.partial.bin" "$source"/expert-{0,1}/{supervision.json,result.json,decisions.jsonl} > "$replay/source-inputs.sha256"
cat > "$base/return-labels-v1/survey" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ "$4" == 2 ]];printf '{}\n' > "$3";printf 'candidates\n' > "$6"
EOF
cat > "$root/empty-target-build-v2/prepare" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
mkdir "$7";printf 'new targets\n' > "$7/targets.bin";jq -n --arg sha "$5" '{passed:true,sourceDataSHA256:$sha,allowEmptyCandidateSplits:true,projectionAndPixelsIndependentlyRechecked:true,actorInputsUnchanged:true}' > "$7/receipt.json"
EOF
cat > "$root/empty-target-build-v2/merge-targets" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
mkdir "$2";printf 'merged targets\n' > "$2/targets.bin"
EOF
cat > "$bin/merge-dense-many" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
mkdir "$1";printf 'merged data\n' > "$1/data.bin"
EOF
cat > "$bin/data-preserve-added" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '{"passed":true,"existingHistoriesPreserved":352,"expandedHistories":354,"expandedFittingHistories":240}\n' > "$3"
EOF
cp "$bin/data-preserve-added" "$bin/target-preserve-added"
cat > "$bin/preflight-expanded-targets" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '{"passed":true,"episodes":354,"fittingHistories":240,"validationHistories":114,"actorInputsUnchanged":true}\n' > "$3"
EOF
cat > "$runtime/build/flex/control/control" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ "$1" == verify-data ]];shift;start="";count="";allow=false
while (( $# ));do case "$1" in --output) output="$2";shift 2;; --data) data="$2";shift 2;; --audit-start) start="$2";shift 2;; --audit-count) count="$2";shift 2;; --allow-incomplete) allow=true;shift;; *) shift;; esac;done
[[ "$count" == 1 && "$allow" == true && ( "$start" == 239 || "$start" == 353 ) ]];mkdir "$output";sha="$(sha256sum "$data" | cut -d' ' -f1)";actions=36;incomplete=1;successful=0;if [[ "$start" == 353 ]];then actions=60;incomplete=0;successful=1;fi
jq -n --arg sha "$sha" --argjson actions "$actions" --argjson incomplete "$incomplete" --argjson successful "$successful" '{passed:true,datasetEpisodes:354,episodes:1,dataSHA256:$sha,studentRollinCommandsReplayed:$actions,incompleteEpisodes:$incomplete,successfulEpisodes:$successful,studentRollinMaxAbsError:0,incompleteEpisodesClaimedSuccessful:false}' > "$output/result.json"
EOF
printf 'simulator\n' > "$runtime/build/flex/control/simulator";chmod +x "$base/return-labels-v1/survey" "$root/empty-target-build-v2/prepare" "$root/empty-target-build-v2/merge-targets" "$bin"/* "$runtime/build/flex/control/control"
driver="$project/datasets/visual-control/expanded-rooms-v1/admit-incomplete-return.sh"
export PUPPYBOT_PROJECT="$mock"
PUPPYBOT_INCOMPLETE_RETURN_ADMISSION_OUT="$out/admitted" bash "$driver" > "$out/admitted.log" 2>&1
jq -e '.passed and .episodes==354 and .fittingHistories==240 and .validationHistories==114 and .addedReturnHistories==2 and .incompleteAddedEpisodes==1 and .studentReturnActionsReplayed==96 and (.incompleteEpisodesClaimedSuccessful|not) and (.automaticPromotion|not)' "$out/admitted/coverage.json" > /dev/null
jq '.terminationReason="success"' "$replay/runs/expert-0/supervision.json" > "$out/bad-metadata.json";cp "$out/bad-metadata.json" "$replay/runs/expert-0/supervision.json"
if PUPPYBOT_INCOMPLETE_RETURN_ADMISSION_OUT="$out/rejected" bash "$driver" > "$out/rejected.log" 2>&1;then echo 'False success metadata was admitted.' >&2;exit 1;fi
[[ "$(< "$out/rejected/run.exit")" != 0 && ! -e "$out/rejected/coverage.json" ]]
jq '.allowIncomplete=true | .recordedHorizon=354 | .terminationReason="horizon"' "$source/expert-0/supervision.json" > "$replay/runs/expert-0/supervision.json"
printf 'changed\n' > "$replay/runs/expert-0/decisions.jsonl"
if PUPPYBOT_INCOMPLETE_RETURN_ADMISSION_OUT="$out/changed-recording" bash "$driver" > "$out/changed-recording.log" 2>&1;then echo 'Changed recording was admitted.' >&2;exit 1;fi
[[ "$(< "$out/changed-recording/run.exit")" != 0 && ! -e "$out/changed-recording/coverage.json" ]]
echo 'Incomplete return admission preserves data and rejects false success or changed recordings.'
