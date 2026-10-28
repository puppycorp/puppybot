#!/usr/bin/env bash
set -euo pipefail
reject_known_hash() {
    local status=0
    /usr/bin/rg -Fxq "$1" "$2" || status=$?
    if (( status==0 ));then echo "Duplicate file hash: $1" >&2;exit 1;fi
    if (( status!=1 ));then echo "Could not check prior hashes: $2" >&2;exit "$status";fi
}

project="${PUPPYBOT_PROJECT:?Project root is required}"
base="$project/build/flex/sim/expanded-rooms-v1"
root="$base/large-model-v1"
out="${PUPPYBOT_RETURN_COHORT_OUT:-$root/return-correction-cohort-v1}"
pilot="$root/return-correction-pilot-v1"
cohort="$root/correction-cohort-v1"
runtime="$root/correction-v3/runtime"
generator="$root/correction-v1/generate-diverse"
policy="$root/expanded-236-mirrored"
first_fit="${PUPPYBOT_RETURN_FIRST_FIT:-37}"
first_validation="${PUPPYBOT_RETURN_FIRST_VALIDATION:-137}"
workers="${PUPPYBOT_RETURN_WORKERS:-4}"
case_offset="${PUPPYBOT_RETURN_CASE_OFFSET:-0}"
seed_base="${PUPPYBOT_RETURN_SEED_BASE:-1940000}"
previous="${PUPPYBOT_RETURN_PREVIOUS_COHORT:-}"
wait_for="${PUPPYBOT_RETURN_WAIT_FOR_RUN:-}"
for number in "$first_fit" "$first_validation" "$workers" "$case_offset" "$seed_base"; do [[ "$number" =~ ^[0-9]+$ && "$number" -le 100000000 ]]; done
(( workers>=1 && workers<=16 && first_fit>=26 && first_fit+workers<=126 && first_validation>=126 && first_validation+workers<=226 && case_offset+workers<=16 && seed_base+workers*1000+1<=2147483647 ))
[[ ! -e "$out" ]]
/usr/bin/mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
if [[ -n "$wait_for" ]]; then
    while [[ ! -f "$wait_for.exit" ]]; do
        [[ -f "$wait_for.pid" ]] && kill -0 "$(< "$wait_for.pid")" || { echo "$wait_for ended without a status." >&2; exit 1; }
        /usr/bin/sleep 20
    done
    printf 'Prior screen exit: %s\n' "$(< "$wait_for.exit")"
fi
[[ "$(< "$pilot/run.exit")" == 0 && "$(< "$cohort/run.exit")" == 0 && "$(< "$root/expanded-236-mirrored.exit")" == 0 ]]
sha="$(/usr/bin/sha256sum "$policy/weights.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$sha" '.memoryWidth==256 and .weightsSHA256==$sha and (.taskFeedback|not)' "$policy/receipt.json" > /dev/null
cd "$project"
"$generator" "$out/rooms-fit" "$first_fit" "$((first_fit+workers))" fit > "$out/generate-fit.log"
"$generator" "$out/rooms-validation" "$first_validation" "$((first_validation+workers))" validation > "$out/generate-validation.log"
/usr/bin/mkdir "$out/catalog"
/usr/bin/cp "$cohort/prior-hashes.txt" "$out/prior-hashes.txt"
/usr/bin/jq -r '.caseSHA256,.environmentSHA256' "$cohort/catalog.jsonl" >> "$out/prior-hashes.txt"
for scene in "$pilot"/catalog/{0,1}; do
    /usr/bin/sha256sum "$scene/case.json" "$scene/environment.bin" | /usr/bin/cut -d' ' -f1 >> "$out/prior-hashes.txt"
done
if [[ -n "$previous" ]]; then
    [[ "$(< "$previous/run.exit")" == 0 ]]
    /usr/bin/jq -e '.complete and .failedWorkers==0 and (.automaticMerge|not)' "$previous/summary.json" > /dev/null
    /usr/bin/jq -r '.caseSHA256,.environmentSHA256' "$previous/catalog.jsonl" >> "$out/prior-hashes.txt"
fi
declare -A seen_cases=() seen_environments=()
for ((worker=0;worker<workers;worker++)); do
    fit=$((first_fit+worker)); validation=$((first_validation+worker)); scene_index=$((case_offset+worker))
    /usr/bin/mkdir "$out/catalog/$worker"
    /usr/bin/cp -a "$out/rooms-fit/$fit/$scene_index" "$out/catalog/$worker/0"
    /usr/bin/cp -a "$out/rooms-validation/$validation/$scene_index" "$out/catalog/$worker/1"
    for episode in 0 1; do
        scene="$out/catalog/$worker/$episode"; layout="$fit"; role=true
        if (( episode )); then layout="$validation"; role=false; fi
        /usr/bin/jq -e --argjson layout "$layout" --argjson fit "$role" '.layoutId==$layout and .fit==$fit and (.rooms|length)==(1+($layout%2))' "$scene/layout.json" > /dev/null
        case_sha="$(/usr/bin/sha256sum "$scene/case.json" | /usr/bin/cut -d' ' -f1)"
        env_sha="$(/usr/bin/sha256sum "$scene/environment.bin" | /usr/bin/cut -d' ' -f1)"
        reject_known_hash "$case_sha" "$out/prior-hashes.txt"
        reject_known_hash "$env_sha" "$out/prior-hashes.txt"
        [[ ! "${seen_cases[$case_sha]+yes}" && ! "${seen_environments[$env_sha]+yes}" ]]
        seen_cases["$case_sha"]=1; seen_environments["$env_sha"]=1
        /usr/bin/jq -cn --argjson worker "$worker" --argjson episode "$episode" --argjson layout "$layout" --argjson sceneIndex "$scene_index" --argjson fit "$role" --arg case "$case_sha" --arg environment "$env_sha" '{worker:$worker,episode:$episode,layout:$layout,sceneIndex:$sceneIndex,fit:$fit,caseSHA256:$case,environmentSHA256:$environment}'
    done
done > "$out/catalog.jsonl"
/usr/bin/sha256sum "$generator" "$runtime/build/flex/control/control" "$runtime/build/flex/control/simulator" "$runtime/build/flex/sim/puppybot.bin" "$policy/weights.bin" "$policy/policy" "$policy/receipt.json" > "$out/inputs.sha256"
/usr/bin/find "$runtime/build/flex/control/kernels" "$out/catalog" -type f -print0 | /usr/bin/sort -z | /usr/bin/xargs -0 /usr/bin/sha256sum >> "$out/inputs.sha256"
for scene in "$out"/catalog/*/{0,1}; do /usr/bin/sha256sum "$scene/environment.bin" "$scene/layout.json" >> "$out/inputs.sha256"; done
export PATH="$base/unseen-benchmark-v2/native-path"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1 PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
cd "$runtime"
failed() { /usr/bin/jq -n --argjson worker "$1" --arg reason "$2" '{worker:$worker,passed:false,reason:$reason,partialArtifactsRetained:true}' > "$out/worker-$1.json"; }
collect() {
    local worker="$1" seed=$((seed_base+$1*1000)) work="$out/worker-$1"
    /usr/bin/mkdir "$work"
    if ! ./build/flex/control/control correct --policy "$policy" --output "$work/runs" --scene-catalog "$out/catalog/$worker" --episodes 2 --validation 1 --rollin 60 --rollin-min 60 --label-rollin --return-rollin --return-via-home --approach-side 1 --horizon 354 --seed "$seed" --large-model > "$work/collect.log" 2>&1; then failed "$worker" collection_failed; return 0; fi
    if ! ./build/flex/control/control pack-data --data "$work/runs/data.bin" --output "$work/packed" > "$work/pack.log" 2>&1; then failed "$worker" pack_failed; return 0; fi
    if ! ./build/flex/control/control verify-data --run "$work/runs" --data "$work/packed/data.bin" --output "$work/verified" > "$work/verify.log" 2>&1; then failed "$worker" audit_failed; return 0; fi
    local data_sha student
    data_sha="$(/usr/bin/sha256sum "$work/packed/data.bin" | /usr/bin/cut -d' ' -f1)"
    student="$(/usr/bin/jq -r '.studentRollinActions' "$work/runs/report.json")"
    if ! /usr/bin/jq -e --arg data "$data_sha" --argjson student "$student" '.passed and .episodes==2 and .studentPolicies256==2 and .studentRollinCommandsReplayed==$student and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .executedCommandsMatchRecordings and .denseOracleLabels and .preActionAlignmentChecked and .zeroPaddingChecked and .taskEventHintAbsent and .dataSHA256==$data' "$work/verified/result.json" > /dev/null; then failed "$worker" audit_receipt_failed; return 0; fi
    for episode in 0 1; do
        local run="$work/runs/expert-$episode" scene="$out/catalog/$worker/$episode"
        if ! /usr/bin/jq -e --arg sha "$sha" '.studentMemoryWidth==256 and .studentWeightsSHA256==$sha and .studentBeginsAfterConsumption and .studentStartAction>0 and .denseOracleLabels and .scheduledRollinActions==60 and .studentActions>=1 and .studentActions<=60' "$run/supervision.json" > /dev/null; then failed "$worker" supervision_receipt_failed; return 0; fi
        if ! /usr/bin/jq -e '.success and .found and .maximumBrickDistanceM==0.35' "$run/result.json" > /dev/null; then failed "$worker" teacher_incomplete; return 0; fi
        for file in case.json environment.bin; do if ! /usr/bin/cmp "$scene/$file" "$run/scene/$file"; then failed "$worker" scene_mismatch; return 0; fi; done
    done
    /usr/bin/jq -n --argjson worker "$worker" --argjson student "$student" --arg data "$data_sha" --arg path "$work/packed/data.bin" '{worker:$worker,passed:true,episodes:2,studentCommandsReplayed:$student,dataSHA256:$data,dataFile:$path,teacherAssisted:true,studentAutonomousSuccessClaimed:false}' > "$out/worker-$worker.json"
}
for ((worker=0;worker<workers;worker++)); do collect "$worker"; done
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
/usr/bin/jq -s '{complete:true,attemptedWorkers:length,successfulWorkers:(map(select(.passed))|length),auditedHistories:(map(select(.passed)|.episodes)|add // 0),studentCommandsReplayed:(map(select(.passed)|.studentCommandsReplayed)|add // 0),failedWorkers:(map(select(.passed|not))|length),partialArtifactsRetained:true,automaticMerge:false,teacherAssisted:true,studentAutonomousSuccessClaimed:false,rows:sort_by(.worker)}' "$out/"worker-*.json > "$out/summary.json"
