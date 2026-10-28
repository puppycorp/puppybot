#!/usr/bin/env bash
# Test split, replay and incomplete-success guards with isolated fixtures.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]];mkdir "$out"
mock="$out/mock";base="$mock/build/flex/sim/expanded-rooms-v1";root="$base/large-model-v1";old="$root/incomplete-return-admission-v1";wide="$root/forward-return-teacher-comparison-v1";known="$root/forward-return-known-comparison-v1";runtime="$root/incomplete-return-runtime-v1/runtime";bin="$root/source/admission-cohort-v3/bin"
mkdir -p "$old/expanded" "$old/targets" "$runtime/build/flex/control" "$bin" "$base/return-labels-v1" "$root/empty-target-build-v2"
printf '0\n' > "$old/run.exit";printf 'old data\n' > "$old/expanded/data.bin";printf 'old targets\n' > "$old/targets/targets.bin";printf '{}\n' > "$old/targets/receipt.json"
sha="$(sha256sum "$old/expanded/data.bin" | cut -d' ' -f1)";jq -n --arg sha "$sha" '{passed:true,episodes:354,fittingHistories:240,validationHistories:114,dataSHA256:$sha,newHistoriesIndependentlyAudited:true,teacherLabelsTrainingOnly:true,actorInputsUnchanged:true,automaticPromotion:false}' > "$old/coverage.json"
for source in "$wide" "$known";do
    mkdir -p "$source/forward/packed" "$source/forward/runs" "$source/forward/verified" "$source/catalog";printf '0\n' > "$source/run.exit"
    printf '{"complete":true,"episodes":2,"identicalSearchPrefixes":true,"teacherAssisted":true,"teacherSearchGoalsReconstructed":true,"autonomousWholeEpisodeSuccessClaimed":false,"automaticMerge":false}\n' > "$source/comparison.json"
    printf '%s data\n' "$source" > "$source/forward/packed/data.bin";sha="$(sha256sum "$source/forward/packed/data.bin" | cut -d' ' -f1)"
    jq -n --arg sha "$sha" '{passed:true,episodes:2,datasetEpisodes:2,studentPolicies256:2,studentRollinCommandsReplayed:2,studentRollinMaxAbsError:0,datasetInputsMatchActualRGBAndOwnFeedback:true,executedCommandsMatchRecordings:true,denseOracleLabels:true,preActionAlignmentChecked:true,zeroPaddingChecked:true,taskEventHintAbsent:true,dataSHA256:$sha,incompleteEpisodesClaimedSuccessful:false}' > "$source/forward/verified/result.json"
    sha256sum "$source/comparison.json" > "$source/inputs.sha256"
    for i in 0 1;do mkdir -p "$source/catalog/$i" "$source/forward/goal-audit-$i";for file in case.json environment.bin;do printf '%s %s %s\n' "$source" "$i" "$file" > "$source/catalog/$i/$file";done;printf '{"passed":true,"brickPositionNotReadBySearchReconstruction":true,"oracleLabelsMatched":true}\n' > "$source/forward/goal-audit-$i/result.json";done
done
for spec in "$wide:0:239" "$wide:1:352" "$known:0:213" "$known:1:328";do source="${spec%%:*}";rest="${spec#*:}";index="${rest%%:*}";original="${rest##*:}";mkdir -p "$old/expanded/expert-$original/scene";cp "$source/catalog/$index/"{case.json,environment.bin} "$old/expanded/expert-$original/scene/";done
cat > "$base/return-labels-v1/survey" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ "$4" == 2 ]];printf '{}\n' > "$3";printf 'candidates\n' > "$6"
EOF
cat > "$root/empty-target-build-v2/prepare" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
mkdir "$7";printf 'targets\n' > "$7/targets.bin";jq -n --arg sha "$5" '{passed:true,sourceDataSHA256:$sha,allowEmptyCandidateSplits:true,projectionAndPixelsIndependentlyRechecked:true,actorInputsUnchanged:true}' > "$7/receipt.json"
EOF
cat > "$root/empty-target-build-v2/merge-targets" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
mkdir "$2";printf 'merged targets\n' > "$2/targets.bin"
EOF
cat > "$bin/merge-dense-many" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
mkdir "$1";printf '%s\n' "$1" > "$1/data.bin"
EOF
cat > "$bin/data-preserve-added" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
old=354;n=356;fit=241
if [[ "$2" == */known/* ]];then n=358;fit=242;if [[ "$1" == */wide/* ]];then old=356;fi;fi
jq -n --argjson old "$old" --argjson n "$n" --argjson fit "$fit" '{passed:true,existingHistoriesPreserved:$old,expandedHistories:$n,expandedFittingHistories:$fit}' > "$3"
EOF
cp "$bin/data-preserve-added" "$bin/target-preserve-added"
cat > "$bin/preflight-expanded-targets" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '{"passed":true,"episodes":358,"fittingHistories":242,"validationHistories":116,"actorInputsUnchanged":true}\n' > "$3"
EOF
cat > "$runtime/build/flex/control/control" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ "$1" == verify-data ]];shift;start='';count='';allow=false
while (( $# ));do case "$1" in --output) output="$2";shift 2;; --data) data="$2";shift 2;; --audit-start) start="$2";shift 2;; --audit-count) count="$2";shift 2;; --allow-incomplete) allow=true;shift;; *) shift;; esac;done
[[ "$count" == 1 && "$allow" == true && ( "$start" == 240 || "$start" == 241 || "$start" == 356 || "$start" == 357 ) ]];mkdir "$output";sha="$(sha256sum "$data" | cut -d' ' -f1)";incomplete=0;successful=1;if [[ "$start" == 240 ]];then incomplete=1;successful=0;fi;if [[ "${PUPPYBOT_TEST_FALSE_SUCCESS:-0}" == 1 && "$start" == 240 ]];then incomplete=0;successful=1;fi
jq -n --arg sha "$sha" --argjson incomplete "$incomplete" --argjson successful "$successful" '{passed:true,datasetEpisodes:358,episodes:1,dataSHA256:$sha,studentPolicies256:1,studentRollinCommandsReplayed:1,studentRollinMaxAbsError:0,denseOracleLabels:true,datasetInputsMatchActualRGBAndOwnFeedback:true,executedCommandsMatchRecordings:true,taskEventHintAbsent:true,incompleteEpisodesClaimedSuccessful:false,incompleteEpisodes:$incomplete,successfulEpisodes:$successful}' > "$output/result.json"
EOF
chmod +x "$base/return-labels-v1/survey" "$root/empty-target-build-v2/prepare" "$root/empty-target-build-v2/merge-targets" "$bin"/* "$runtime/build/flex/control/control"
driver="$project/datasets/visual-control/expanded-rooms-v1/admit-forward-return-pilot.sh"
export PUPPYBOT_PROJECT="$mock"
PUPPYBOT_FORWARD_RETURN_ADMISSION_OUT="$out/admitted" bash "$driver" > "$out/admitted.log" 2>&1
jq -e '.passed and .episodes==358 and .fittingHistories==242 and .validationHistories==116 and .addedTeacherHistories==4 and .reusedScenesSameSplit and .studentActionsReplayed==4 and (.incompleteEpisodesClaimedSuccessful|not) and (.automaticPromotion|not)' "$out/admitted/coverage.json" > /dev/null
printf 'wrong scene\n' > "$known/catalog/0/case.json"
if PUPPYBOT_FORWARD_RETURN_ADMISSION_OUT="$out/bad-scene" bash "$driver" > "$out/bad-scene.log" 2>&1;then echo 'Changed scene was admitted.' >&2;exit 1;fi
[[ "$(< "$out/bad-scene/run.exit")" != 0 && ! -e "$out/bad-scene/coverage.json" ]]
cp "$old/expanded/expert-213/scene/case.json" "$known/catalog/0/case.json"
if PUPPYBOT_TEST_FALSE_SUCCESS=1 PUPPYBOT_FORWARD_RETURN_ADMISSION_OUT="$out/false-success" bash "$driver" > "$out/false-success.log" 2>&1;then echo 'False incomplete success was admitted.' >&2;exit 1;fi
[[ "$(< "$out/false-success/run.exit")" != 0 && ! -e "$out/false-success/coverage.json" ]]
echo 'Forward-return admission guards split identity, replay and incomplete success.'
