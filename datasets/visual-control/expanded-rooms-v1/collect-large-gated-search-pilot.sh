#!/usr/bin/env bash
# On-policy search histories from new rooms; the oracle supplies labels only.
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
out="${PUPPYBOT_GATED_SEARCH_OUT:?New output directory required}"
runtime="$root/phase-large-tests-v1/runtime"
generator="$root/correction-v1/generate-diverse"
policy="$root/phase-screen-v1/policy"
previous="$root/return-correction-cohort-v2"
[[ ! -e "$out" ]]
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
[[ "$(< "$root/phase-screen-v1/run.exit")" == 0 && "$(< "$previous/run.exit")" == 0 ]]
/usr/bin/jq -e '.complete and .successfulWorkers==8 and .failedWorkers==0' "$previous/summary.json" > /dev/null
sha="$(/usr/bin/sha256sum "$policy/weights.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$sha" '.memoryWidth==256 and .weightsSHA256==$sha and .phaseGatedNavigation and (.taskFeedback|not)' "$policy/receipt.json" > /dev/null
"$generator" "$out/fit" 49 50 fit > "$out/generate-fit.log"
"$generator" "$out/validation" 149 150 validation > "$out/generate-validation.log"
mkdir "$out/catalog"
cp -a "$out/fit/49/0" "$out/catalog/0"
cp -a "$out/validation/149/0" "$out/catalog/1"
cp "$previous/prior-hashes.txt" "$out/prior-hashes.txt"
/usr/bin/jq -r '.caseSHA256,.environmentSHA256' "$previous/catalog.jsonl" >> "$out/prior-hashes.txt"
for layout in 20 21 22 23;do
    for scene in {0..15};do
        for file in case.json environment.bin;do /usr/bin/sha256sum "$base/generalization-benchmark-v1/scenes/$layout/$scene/$file" | /usr/bin/cut -d' ' -f1;done
    done
done >> "$out/prior-hashes.txt"
for episode in 0 1;do
    scene="$out/catalog/$episode"; layout=49; fit=true
    if (( episode ));then layout=149;fit=false;fi
    /usr/bin/jq -e --argjson layout "$layout" --argjson fit "$fit" '.layoutId==$layout and .fit==$fit and (.rooms|length)==2' "$scene/layout.json" > /dev/null
    for file in case.json environment.bin;do
        digest="$(/usr/bin/sha256sum "$scene/$file" | /usr/bin/cut -d' ' -f1)"
        reject_known_hash "$digest" "$out/prior-hashes.txt"
        printf '%s\n' "$digest" >> "$out/prior-hashes.txt"
    done
done
/usr/bin/sha256sum "$generator" "$runtime/build/flex/control/control" "$runtime/build/flex/control/simulator" "$runtime/build/flex/sim/puppybot.bin" "$policy/weights.bin" "$policy/policy" "$policy/receipt.json" "$out"/catalog/{0,1}/{case.json,environment.bin,layout.json} > "$out/inputs.sha256"
find "$runtime/build/flex/control/kernels" -type f -print0 | /usr/bin/sort -z | /usr/bin/xargs -0 /usr/bin/sha256sum >> "$out/inputs.sha256"
export PATH="$base/unseen-benchmark-v2/native-path:$PATH" XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1 PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
cd "$runtime"
./build/flex/control/control correct --policy "$policy" --output "$out/runs" --scene-catalog "$out/catalog" --episodes 2 --validation 1 --rollin 120 --rollin-min 120 --label-rollin --hidden-target --return-via-home --approach-side 1 --horizon 354 --seed 1970000 --large-model > "$out/collect.log" 2>&1
./build/flex/control/control pack-data --data "$out/runs/data.bin" --output "$out/packed" > "$out/pack.log" 2>&1
./build/flex/control/control verify-data --run "$out/runs" --data "$out/packed/data.bin" --output "$out/verified" --large-model > "$out/verify.log" 2>&1
data="$(/usr/bin/sha256sum "$out/packed/data.bin" | /usr/bin/cut -d' ' -f1)"
student="$(/usr/bin/jq -r '.studentRollinActions' "$out/runs/report.json")"
/usr/bin/jq -e --arg data "$data" --argjson student "$student" '.passed and .episodes==2 and .studentPolicies256==2 and .studentRollinCommandsReplayed==$student and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .executedCommandsMatchRecordings and .denseOracleLabels and .preActionAlignmentChecked and .zeroPaddingChecked and .taskEventHintAbsent and .dataSHA256==$data' "$out/verified/result.json" > /dev/null
for episode in 0 1;do
    run="$out/runs/expert-$episode"
    /usr/bin/jq -e --arg sha "$sha" '.studentMemoryWidth==256 and .studentWeightsSHA256==$sha and (.studentBeginsAfterConsumption|not) and .studentStartAction==0 and .denseOracleLabels and .scheduledRollinActions==120 and .studentActions>=1 and .studentActions<=120' "$run/supervision.json" > /dev/null
    /usr/bin/jq -e '.success and .found and .maximumBrickDistanceM==0.35' "$run/result.json" > /dev/null
    for file in case.json environment.bin;do /usr/bin/cmp "$out/catalog/$episode/$file" "$run/scene/$file";done
done
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
/usr/bin/jq -n --arg data "$data" --argjson student "$student" '{passed:true,episodes:2,fittingHistories:1,validationHistories:1,studentCommandsReplayed:$student,dataSHA256:$data,denseOracleLabels:true,teacherLabelsTrainingOnly:true,actorTaskEventHint:false,studentAutonomousSuccessClaimed:false,automaticMerge:false}' > "$out/summary.json"
echo 'Two long-search roll-in histories passed independent replay; no data was merged.'
