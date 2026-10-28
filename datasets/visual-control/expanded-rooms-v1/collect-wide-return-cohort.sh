#!/usr/bin/env bash
# Teacher searches, then the student controls a return window before recovery.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
base="$project/build/flex/sim/expanded-rooms-v1";root="$base/large-model-v1"
catalog="$root/wide-return-catalog-v1";training="$root/coverage-scale-training-v1";policy="$training/policy";runtime="$root/coverage-return-tests-v1/runtime"
audit="${PUPPYBOT_WIDE_RETURN_AUDIT:?Frozen teacher audit required}"
capacity="${PUPPYBOT_WIDE_RETURN_WAIT_RUN:?Previous GPU job required}"
out="${PUPPYBOT_WIDE_RETURN_OUT:?New output directory required}"
[[ ! -e "$out" ]];mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
for job in "$catalog/run" "$training/run";do [[ "$(< "$job.exit")" == 0 ]];done
while [[ ! -f "$capacity.exit" ]];do [[ -f "$capacity.pid" ]] && kill -0 "$(< "$capacity.pid")" || { echo 'Previous GPU job ended without a status.' >&2;exit 1; };sleep 20;done
printf '%s\n' "$(< "$capacity.exit")" > "$out/prior-gpu-status.txt"
jq -e '.passed and .episodes==4 and .fittingLayouts==2 and .validationLayouts==2 and .openLayouts==2 and .twoRoomLayouts==2 and .uniqueStartingPoses==4 and .wideHeading and .geometryChecked and .exactFilesDisjointFrom350CorpusAndOtherScenes and .reservedFinalUntouched and .physicalSpawnNotYetChecked' "$catalog/summary.json" > /dev/null
sha="$(sha256sum "$policy/weights.bin" | cut -d' ' -f1)"
jq -e --arg sha "$sha" '.weightsSHA256==$sha and .memoryWidth==256 and (.taskFeedback|not)' "$policy/receipt.json" > /dev/null
cmp "$runtime/build/flex/control/simulator" "$root/workspace/build/flex/control/simulator"
sha256sum -c "$catalog/inputs.sha256" > "$out/catalog-integrity-before.log"
sha256sum -c "$catalog/prior-inputs.sha256" > "$out/prior-integrity-before.log"
sha256sum "$audit" "$(dirname "$audit")/audit-coverage-teacher-v2.jq" "$runtime/build/flex/control/control" "$runtime/build/flex/control/simulator" "$runtime/build/flex/sim/puppybot.bin" "$policy/weights.bin" "$policy/policy" "$policy/receipt.json" "$catalog/summary.json" > "$out/inputs.sha256"
find "$runtime/build/flex/control/kernels" -type f -print0 | sort -z | xargs -0 -r sha256sum >> "$out/inputs.sha256"
mkdir "$out/catalog"
for worker in 0 1;do mkdir "$out/catalog/$worker";cp -a "$catalog/catalog/$worker" "$out/catalog/$worker/0";cp -a "$catalog/catalog/$((worker+2))" "$out/catalog/$worker/1";done
sha256sum "$out"/catalog/{0,1}/{0,1}/{case.json,environment.bin,layout.json} >> "$out/inputs.sha256"
export PATH="$base/unseen-benchmark-v2/native-path:$PATH" XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1 PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
cd "$runtime"
for worker in 0 1;do
    work="$out/worker-$worker";mkdir "$work";seed=$((1998000+worker*1000));reason=''
    if ! ./build/flex/control/control correct --policy "$policy" --scene-catalog "$out/catalog/$worker" --output "$work/runs" --episodes 2 --validation 1 --rollin 60 --rollin-min 60 --horizon 354 --label-rollin --return-rollin --coverage-teacher --seed "$seed" --large-model > "$work/collect.log" 2>&1;then reason=collection_failed
    elif ! ./build/flex/control/control pack-data --data "$work/runs/data.bin" --output "$work/packed" > "$work/pack.log" 2>&1;then reason=pack_failed
    elif ! ./build/flex/control/control verify-data --run "$work/runs" --data "$work/packed/data.bin" --output "$work/verified" --large-model > "$work/verify.log" 2>&1;then reason=replay_failed
    else
        data_sha="$(sha256sum "$work/packed/data.bin" | cut -d' ' -f1)"
        if ! jq -e --arg sha "$data_sha" '.passed and .episodes==2 and .datasetEpisodes==2 and .dataSHA256==$sha and .studentPolicies256==2 and .studentRollinCommandsReplayed>=2 and .studentRollinCommandsReplayed<=120 and .studentRollinMaxAbsError==0 and .denseOracleLabels and .datasetInputsMatchActualRGBAndOwnFeedback and .executedCommandsMatchRecordings and .taskEventHintAbsent' "$work/verified/result.json" > /dev/null;then reason=replay_receipt_invalid;fi
    fi
    if [[ -z "$reason" ]];then
        for i in 0 1;do
            run="$work/runs/expert-$i";scene="$out/catalog/$worker/$i"
            if ! jq -e --arg sha "$sha" '.studentMemoryWidth==256 and .studentWeightsSHA256==$sha and .studentBeginsAfterConsumption and .studentStartAction>=1 and .studentActions>=1 and .studentActions<=60 and .denseOracleLabels and .searchTeacher=="coverage-camera-v2" and .teacherPlannerUsesPrivilegedGeometry and (.searchGoalsUseUnseenBrickPosition|not)' "$run/supervision.json" > /dev/null;then reason=window_invalid;break;fi
            if ! cmp "$scene/case.json" "$run/scene/case.json" || ! cmp "$scene/environment.bin" "$run/scene/environment.bin";then reason=scene_changed;break;fi
            if ! jq -n --slurpfile scene "$scene/layout.json" --slurpfile initial "$run/initial.json" 'def abs: if .<0 then -. else . end; all(range(0;3); . as $i | (($scene[0].startPose[$i]-$initial[0].pose[$i])|abs)<0.00001)' | jq -e . > /dev/null;then reason=pose_changed;break;fi
            if ! bash "$audit" "$run" "$work/goal-audit-$i" > "$work/goal-audit-$i.log" 2>&1;then reason=goal_audit_failed;break;fi
            if ! jq -e '.passed and .brickPositionNotReadBySearchReconstruction and .oracleLabelsMatched' "$work/goal-audit-$i/result.json" > /dev/null;then reason=goal_audit_invalid;break;fi
        done
    fi
    if [[ -n "$reason" ]];then jq -n --argjson worker "$worker" --arg reason "$reason" '{worker:$worker,passed:false,reason:$reason,partialArtifactsRetained:true}' > "$out/worker-$worker.json";continue;fi
    jq -n --argjson worker "$worker" --slurpfile verified "$work/verified/result.json" --slurpfile a "$work/runs/expert-0/supervision.json" --slurpfile b "$work/runs/expert-1/supervision.json" '{worker:$worker,passed:true,studentReturnActionsReplayed:$verified[0].studentRollinCommandsReplayed,studentReturnCompletions:([$a[0],$b[0]]|map(select(.studentCompletedBeforeHandoff))|length),teacherAssisted:true,initialPhysicalPosesChecked:true,automaticMerge:false}' > "$out/worker-$worker.json"
done
sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
sha256sum -c "$catalog/inputs.sha256" > "$out/catalog-integrity-after.log"
sha256sum -c "$catalog/prior-inputs.sha256" > "$out/prior-integrity-after.log"
jq -s '{complete:true,workers:length,successfulWorkers:(map(select(.passed))|length),failedWorkers:(map(select(.passed|not))|length),studentReturnActionsReplayed:([.[]|select(.passed)|.studentReturnActionsReplayed]|add // 0),studentReturnCompletions:([.[]|select(.passed)|.studentReturnCompletions]|add // 0),teacherAssisted:true,autonomousWholeEpisodeSuccessClaimed:false,automaticMerge:false,rows:.}' "$out"/worker-{0,1}.json > "$out/summary.json"
echo 'Wide-heading return cohort finished; successful pairs require separate admission.'
