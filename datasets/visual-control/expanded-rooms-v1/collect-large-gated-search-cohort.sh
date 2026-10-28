#!/usr/bin/env bash
# Collect on-policy search states and oracle labels in new generated rooms.
set -euo pipefail
reject_known_hash() {
    local status=0
    /usr/bin/rg -Fxq "$1" "$2" || status=$?
    if (( status==0 ));then echo "Duplicate file hash: $1" >&2;exit 1;fi
    if (( status!=1 ));then echo "Could not check prior hashes: $2" >&2;exit "$status";fi
}
project="${PUPPYBOT_PROJECT:?Project root required}"
base="$project/build/flex/sim/expanded-rooms-v1"
root="$base/large-model-v1"
old="$root/gated-search-admission-v1"
pilot="$root/gated-search-pilot-v1"
runtime="$root/phase-large-tests-v1/runtime"
generator="$root/correction-v1/generate-diverse"
policy="$root/phase-screen-v1/policy"
out="${PUPPYBOT_GATED_SEARCH_COHORT_OUT:?New output directory required}"
[[ ! -e "$out" ]]
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
[[ "$(< "$old/run.exit")" == 0 && "$(< "$pilot/run.exit")" == 0 ]]
old_data="$old/expanded/data.bin"
old_sha="$(/usr/bin/sha256sum "$old_data" | /usr/bin/cut -d' ' -f1)"
policy_sha="$(/usr/bin/sha256sum "$policy/weights.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$old_sha" '.passed and .episodes==282 and .fittingHistories==204 and .validationHistories==78 and .dataSHA256==$sha and .newHistoriesIndependentlyAudited and .teacherLabelsTrainingOnly and .actorInputsUnchanged' "$old/coverage.json" > /dev/null
/usr/bin/jq -e --arg sha "$policy_sha" '.memoryWidth==256 and .weightsSHA256==$sha and .phaseGatedNavigation and (.taskFeedback|not)' "$policy/receipt.json" > /dev/null
"$generator" "$out/rooms-fit" 50 54 fit > "$out/generate-fit.log"
"$generator" "$out/rooms-validation" 150 154 validation > "$out/generate-validation.log"
for ((index=0;index<282;index++));do
    for file in case.json environment.bin;do /usr/bin/sha256sum "$old/expanded/expert-$index/scene/$file" | /usr/bin/tee -a "$out/prior-inputs.sha256" | /usr/bin/cut -d' ' -f1;done
done > "$out/prior-hashes.txt"
for layout in 18 19 20 21 22 23;do
    parent=generalization-benchmark-v1; if (( layout<20 ));then parent=unseen-benchmark-v2;fi
    for scene in {0..15};do for file in case.json environment.bin;do /usr/bin/sha256sum "$base/$parent/scenes/$layout/$scene/$file" | /usr/bin/tee -a "$out/prior-inputs.sha256" | /usr/bin/cut -d' ' -f1;done;done
done >> "$out/prior-hashes.txt"
mkdir "$out/catalog"
for ((worker=0;worker<4;worker++));do
    mkdir "$out/catalog/$worker"
    for episode in 0 1;do
        layout=$((50+worker)); role=true; source="$out/rooms-fit"
        if (( episode ));then layout=$((150+worker));role=false;source="$out/rooms-validation";fi
        cp -a "$source/$layout/$((worker+4))" "$out/catalog/$worker/$episode"
        scene="$out/catalog/$worker/$episode"
        /usr/bin/jq -e --argjson layout "$layout" --argjson role "$role" '.layoutId==$layout and .fit==$role and (.rooms|length)==(1+($layout%2))' "$scene/layout.json" > /dev/null
        for file in case.json environment.bin;do
            digest="$(/usr/bin/sha256sum "$scene/$file" | /usr/bin/cut -d' ' -f1)"
            reject_known_hash "$digest" "$out/prior-hashes.txt"
            printf '%s\n' "$digest" >> "$out/prior-hashes.txt"
        done
        /usr/bin/jq -cn --argjson worker "$worker" --argjson episode "$episode" --argjson layout "$layout" --argjson fit "$role" '{worker:$worker,episode:$episode,layout:$layout,fit:$fit}'
    done
done > "$out/catalog.jsonl"
/usr/bin/sha256sum "$generator" "$runtime/build/flex/control/control" "$runtime/build/flex/control/simulator" "$runtime/build/flex/sim/puppybot.bin" "$old_data" "$old/coverage.json" "$policy/weights.bin" "$policy/policy" "$policy/receipt.json" > "$out/inputs.sha256"
find "$runtime/build/flex/control/kernels" "$out/catalog" -type f -print0 | /usr/bin/sort -z | /usr/bin/xargs -0 /usr/bin/sha256sum >> "$out/inputs.sha256"
for scene in "$out"/catalog/*/{0,1};do /usr/bin/sha256sum "$scene/environment.bin" "$scene/layout.json" >> "$out/inputs.sha256";done
export PATH="$base/unseen-benchmark-v2/native-path:$PATH" XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1 PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
cd "$runtime"
failed() { /usr/bin/jq -n --argjson worker "$1" --arg reason "$2" '{worker:$worker,passed:false,reason:$reason,partialArtifactsRetained:true}' > "$out/worker-$1.json"; }
collect() {
    local worker="$1" seed work extra=()
    seed=$((1980000+worker*1000));work="$out/worker-$worker"
    mkdir "$work"
    if (( worker%2 ));then extra+=(--hidden-target);fi
    if ! ./build/flex/control/control correct --policy "$policy" --output "$work/runs" --scene-catalog "$out/catalog/$worker" --episodes 2 --validation 1 --rollin 120 --rollin-min 120 --label-rollin --return-via-home --approach-side 1 --horizon 354 --seed "$seed" --large-model "${extra[@]}" > "$work/collect.log" 2>&1;then failed "$worker" collection_failed;return 0;fi
    if ! ./build/flex/control/control pack-data --data "$work/runs/data.bin" --output "$work/packed" > "$work/pack.log" 2>&1;then failed "$worker" pack_failed;return 0;fi
    if ! ./build/flex/control/control verify-data --run "$work/runs" --data "$work/packed/data.bin" --output "$work/verified" --large-model > "$work/verify.log" 2>&1;then failed "$worker" replay_failed;return 0;fi
    local data_sha student
    data_sha="$(/usr/bin/sha256sum "$work/packed/data.bin" | /usr/bin/cut -d' ' -f1)"
    student="$(/usr/bin/jq -r '.studentRollinActions' "$work/runs/report.json")"
    if ! /usr/bin/jq -e --arg sha "$data_sha" --argjson student "$student" '.passed and .episodes==2 and .studentPolicies256==2 and .studentRollinCommandsReplayed==$student and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .executedCommandsMatchRecordings and .denseOracleLabels and .preActionAlignmentChecked and .zeroPaddingChecked and .taskEventHintAbsent and .dataSHA256==$sha' "$work/verified/result.json" > /dev/null;then failed "$worker" replay_receipt_failed;return 0;fi
    for episode in 0 1;do
        local run="$work/runs/expert-$episode"
        if ! /usr/bin/jq -e --arg sha "$policy_sha" '.studentMemoryWidth==256 and .studentWeightsSHA256==$sha and (.studentBeginsAfterConsumption|not) and .studentStartAction==0 and .denseOracleLabels and .scheduledRollinActions==120 and .studentActions>=1 and .studentActions<=120' "$run/supervision.json" > /dev/null;then failed "$worker" supervision_failed;return 0;fi
        if ! /usr/bin/jq -e '.success and .found and .maximumBrickDistanceM==0.35' "$run/result.json" > /dev/null;then failed "$worker" teacher_incomplete;return 0;fi
        for file in case.json environment.bin;do if ! /usr/bin/cmp "$out/catalog/$worker/$episode/$file" "$run/scene/$file";then failed "$worker" scene_mismatch;return 0;fi;done
    done
    /usr/bin/jq -n --argjson worker "$worker" --argjson student "$student" --arg data "$data_sha" '{worker:$worker,passed:true,episodes:2,studentCommandsReplayed:$student,dataSHA256:$data,teacherAssisted:true,studentAutonomousSuccessClaimed:false}' > "$out/worker-$worker.json"
}
for ((worker=0;worker<4;worker++));do collect "$worker";done
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
/usr/bin/sha256sum -c "$out/prior-inputs.sha256" > "$out/prior-integrity-after.log"
/usr/bin/jq -s '{complete:true,attemptedWorkers:length,successfulWorkers:(map(select(.passed))|length),auditedHistories:(map(select(.passed)|.episodes)|add // 0),studentCommandsReplayed:(map(select(.passed)|.studentCommandsReplayed)|add // 0),failedWorkers:(map(select(.passed|not))|length),partialArtifactsRetained:true,automaticMerge:false,teacherAssisted:true,studentAutonomousSuccessClaimed:false,rows:sort_by(.worker)}' "$out/"worker-*.json > "$out/summary.json"
echo 'Long-search collection complete; inspect successful workers before admission.'
