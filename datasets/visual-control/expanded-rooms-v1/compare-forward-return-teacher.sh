#!/usr/bin/env bash
# Compare teacher-assisted routes with and without a higher return reverse cost.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
base="$project/build/flex/sim/expanded-rooms-v1";root="$base/large-model-v1"
build="${PUPPYBOT_FORWARD_TEACHER_BUILD:?Teacher build required}"
audit="${PUPPYBOT_FORWARD_TEACHER_AUDIT:?Frozen coverage audit required}"
summary="${PUPPYBOT_FORWARD_TEACHER_SUMMARY:?Native demonstration summary required}"
out="${PUPPYBOT_FORWARD_TEACHER_OUT:?New output directory required}"
runtime="$root/incomplete-return-runtime-v1/runtime";policy="$root/neutral-drive-training-v2/policy"
scene_set="${PUPPYBOT_FORWARD_TEACHER_SCENE_SET:-wide-heading}"
if [[ "$scene_set" == wide-heading ]];then catalog="$root/wide-return-catalog-v1";first=0;second=3
elif [[ "$scene_set" == known-return ]];then catalog="$root/coverage-v2-teacher-cohort-v1";first=0;second=5
else echo 'Expected wide-heading or known-return scenes.' >&2;exit 2;fi
[[ ! -e "$out" ]];mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
jq -e '.passed and .teacherReturnReverseCost==4 and .defaultReverseCost==1.5 and .searchAndStudentCostsUnchanged and .reverseStillPermitted and .oracleCacheKeysIncludePhase and .sourceSnapshotOnly and .trainingOracleOnly and (.automaticPromotion|not)' "$build/summary.json" > /dev/null
if [[ "$scene_set" == wide-heading ]];then jq -e '.passed and .episodes==4 and .wideHeading and .geometryChecked and .reservedFinalUntouched' "$catalog/summary.json" > /dev/null
else jq -e '.passed and .episodes==8 and .teacherSearchGoalsReconstructed and .teacherAssistedCompleted>=2 and (.studentAutonomousSuccessClaimed|not)' "$catalog/summary.json" > /dev/null;fi
[[ "$(< "$root/neutral-drive-training-v2/run.exit")" == 0 ]]
sha="$(sha256sum "$policy/weights.bin" | cut -d' ' -f1)"
jq -e --arg sha "$sha" '.weightsSHA256==$sha and .memoryWidth==256 and (.taskFeedback|not)' "$policy/receipt.json" > /dev/null
sha256sum -c "$build/outputs.sha256" > "$out/build-integrity-before.log"
mkdir "$out/catalog";cp -a "$catalog/catalog/$first" "$out/catalog/0";cp -a "$catalog/catalog/$second" "$out/catalog/1"
sha256sum "$audit" "$(dirname "$audit")/audit-coverage-teacher-v2.jq" "$summary" "$runtime/build/flex/control/control" "$runtime/build/flex/sim/puppybot.bin" "$policy/weights.bin" "$policy/policy" "$policy/receipt.json" "$out"/catalog/{0,1}/{case.json,environment.bin,layout.json} > "$out/inputs.sha256"
find "$runtime/build/flex/control/kernels" -type f -print0 | sort -z | xargs -0 -r sha256sum >> "$out/inputs.sha256"
export PATH="$base/unseen-benchmark-v2/native-path:$PATH" XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1 PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
for kind in reference forward;do
    work="$out/$kind";mkdir "$work";cp -a --reflink=auto "$runtime" "$work/runtime"
    executable="$build/reference-simulator";if [[ "$kind" == forward ]];then executable="$build/forward-return-simulator";fi
    cp "$executable" "$work/runtime/build/flex/control/simulator";cmp "$executable" "$work/runtime/build/flex/control/simulator"
    (cd "$work/runtime" && ./build/flex/control/control correct --policy "$policy" --scene-catalog "$out/catalog" --output "$work/runs" --episodes 2 --validation 1 --rollin 1 --rollin-min 1 --horizon 354 --label-rollin --allow-incomplete --coverage-teacher --seed 1998000 --large-model) > "$work/collect.log" 2>&1
    (cd "$work/runtime" && ./build/flex/control/control pack-data --data "$work/runs/data.bin" --output "$work/packed") > "$work/pack.log" 2>&1
    (cd "$work/runtime" && ./build/flex/control/control verify-data --run "$work/runs" --data "$work/packed/data.bin" --output "$work/verified" --allow-incomplete --large-model) > "$work/verify.log" 2>&1
    data_sha="$(sha256sum "$work/packed/data.bin" | cut -d' ' -f1)"
    jq -e --arg sha "$data_sha" '.passed and .episodes==2 and .datasetEpisodes==2 and .studentPolicies256==2 and .studentRollinCommandsReplayed==2 and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .executedCommandsMatchRecordings and .denseOracleLabels and .preActionAlignmentChecked and .zeroPaddingChecked and .taskEventHintAbsent and .dataSHA256==$sha and (.incompleteEpisodesClaimedSuccessful|not)' "$work/verified/result.json" > /dev/null
    for index in 0 1;do
        run="$work/runs/expert-$index";scene="$out/catalog/$index"
        jq -e --arg sha "$sha" '.studentWeightsSHA256==$sha and .studentActions==1 and .studentStartAction==0 and .denseOracleLabels and .allowIncomplete and .searchTeacher=="coverage-camera-v2" and (.searchGoalsUseUnseenBrickPosition|not)' "$run/supervision.json" > /dev/null
        for file in case.json environment.bin;do cmp "$scene/$file" "$run/scene/$file";done
        jq -n --slurpfile scene "$scene/layout.json" --slurpfile initial "$run/initial.json" 'def abs: if .<0 then -. else . end; all(range(0;3); . as $i | (($scene[0].startPose[$i]-$initial[0].pose[$i])|abs)<0.00001)' | jq -e . > /dev/null
        bash "$audit" "$run" "$work/goal-audit-$index" > "$work/goal-audit-$index.log" 2>&1
        jq -e '.passed and .brickPositionNotReadBySearchReconstruction and .oracleLabelsMatched' "$work/goal-audit-$index/result.json" > /dev/null
        jq -sS 'reduce .[] as $r ({active:true,rows:[]}; if .active then .rows += [{rgbSHA256:$r.rgbSHA256,proprio:$r.proprio,action:$r.action,pose:$r.state.pose,phase:$r.state.findReturn.phase}] | .active=($r.state.findReturn.phase=="search") else . end) | .rows' "$run/decisions.jsonl" > "$work/search-prefix-$index.json"
    done
    "$summary" "$work/packed/data.bin" > "$work/dataset-summary.json"
    jq -e --arg sha "$data_sha" '.datasetSHA256==$sha and .episodes==2 and .fittingHistories==1' "$work/dataset-summary.json" > /dev/null
done
for index in 0 1;do cmp "$out/reference/search-prefix-$index.json" "$out/forward/search-prefix-$index.json";done
sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
sha256sum -c "$build/outputs.sha256" > "$out/build-integrity-after.log"
jq -n --arg scene_set "$scene_set" --slurpfile reference "$out/reference/runs/report.json" --slurpfile forward "$out/forward/runs/report.json" --slurpfile a "$out/reference/dataset-summary.json" --slurpfile b "$out/forward/dataset-summary.json" --slurpfile r0 "$out/reference/runs/expert-0/result.json" --slurpfile r1 "$out/reference/runs/expert-1/result.json" --slurpfile f0 "$out/forward/runs/expert-0/result.json" --slurpfile f1 "$out/forward/runs/expert-1/result.json" '
 def stats($report;$data;$rows): {teacherCompleted:$report.teacherCompleted,found:([$rows[]|select(.found)]|length),incomplete:$report.incompleteEpisodes,returnForward:([$data.expertActionClasses[1][0:3][],$data.expertActionClasses[3][0:3][]]|add),returnReverse:([$data.expertActionClasses[1][3:6][],$data.expertActionClasses[3][3:6][]]|add),rows:$rows};
 {complete:true,episodes:2,sceneSet:$scene_set,reusedTrainingScenes:($scene_set=="known-return"),identicalSearchPrefixes:true,studentActionsPerEpisode:1,teacherAssisted:true,teacherSearchGoalsReconstructed:true,reference:stats($reference[0];$a[0];[$r0[0],$r1[0]]),forward:stats($forward[0];$b[0];[$f0[0],$f1[0]]),autonomousWholeEpisodeSuccessClaimed:false,automaticMerge:false}' > "$out/comparison.json"
jq -e '.complete and .identicalSearchPrefixes and .teacherAssisted and .teacherSearchGoalsReconstructed and (.autonomousWholeEpisodeSuccessClaimed|not) and (.automaticMerge|not)' "$out/comparison.json" > /dev/null
echo 'Compared forward-preferring and reference teachers on matched search prefixes.'
