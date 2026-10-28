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
out="$root/return-correction-pilot-v1"
runtime="$root/correction-v3/runtime"
generator="$root/correction-v1/generate-diverse"
policy="$root/expanded-236-mirrored"
cohort="$root/correction-cohort-v1"
[[ ! -e "$out" ]]
/usr/bin/mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
[[ "$(< "$root/expanded-236-mirrored.exit")" == 0 && "$(< "$cohort/run.exit")" == 0 ]]
sha="$(/usr/bin/sha256sum "$policy/weights.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$sha" '.memoryWidth==256 and .weightsSHA256==$sha and (.taskFeedback|not)' "$policy/receipt.json" > /dev/null
cd "$project"
"$generator" "$out/fit" 36 37 fit > "$out/generate-fit.log"
"$generator" "$out/validation" 136 137 validation > "$out/generate-validation.log"
/usr/bin/mkdir "$out/catalog"
/usr/bin/cp -a "$out/fit/36/0" "$out/catalog/0"
/usr/bin/cp -a "$out/validation/136/0" "$out/catalog/1"
/usr/bin/cp "$cohort/prior-hashes.txt" "$out/prior-hashes.txt"
/usr/bin/jq -r '.caseSHA256,.environmentSHA256' "$cohort/catalog.jsonl" >> "$out/prior-hashes.txt"
for episode in 0 1; do
    scene="$out/catalog/$episode"; layout=36; role=true
    if (( episode )); then layout=136; role=false; fi
    /usr/bin/jq -e --argjson layout "$layout" --argjson fit "$role" '.layoutId==$layout and .fit==$fit' "$scene/layout.json" > /dev/null
    for file in case.json environment.bin; do hash="$(/usr/bin/sha256sum "$scene/$file" | /usr/bin/cut -d' ' -f1)"; reject_known_hash "$hash" "$out/prior-hashes.txt"; printf '%s\n' "$hash" >> "$out/prior-hashes.txt"; done
done
/usr/bin/sha256sum "$generator" "$runtime/build/flex/control/control" "$runtime/build/flex/control/simulator" "$policy/weights.bin" "$policy/policy" "$policy/receipt.json" "$out"/catalog/{0,1}/{case.json,environment.bin,layout.json} > "$out/inputs.sha256"
export PATH="$base/unseen-benchmark-v2/native-path"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1 PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
cd "$runtime"
./build/flex/control/control correct --policy "$policy" --output "$out/runs" --scene-catalog "$out/catalog" --episodes 2 --validation 1 --rollin 30 --rollin-min 30 --label-rollin --return-rollin --return-via-home --approach-side 1 --horizon 354 --seed 1930000 --large-model > "$out/collect.log" 2>&1
./build/flex/control/control pack-data --data "$out/runs/data.bin" --output "$out/packed" > "$out/pack.log" 2>&1
./build/flex/control/control verify-data --run "$out/runs" --data "$out/packed/data.bin" --output "$out/verified" > "$out/verify.log" 2>&1
data_sha="$(/usr/bin/sha256sum "$out/packed/data.bin" | /usr/bin/cut -d' ' -f1)"
student="$(/usr/bin/jq -r '.studentRollinActions' "$out/runs/report.json")"
/usr/bin/jq -e --arg data "$data_sha" --argjson student "$student" '.passed and .episodes==2 and .studentPolicies256==2 and .studentRollinCommandsReplayed==$student and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .denseOracleLabels and .taskEventHintAbsent and .dataSHA256==$data' "$out/verified/result.json" > /dev/null
for episode in 0 1; do
    run="$out/runs/expert-$episode"
    /usr/bin/jq -e --arg sha "$sha" '.studentMemoryWidth==256 and .studentWeightsSHA256==$sha and .studentBeginsAfterConsumption and .studentStartAction>0 and .denseOracleLabels and .scheduledRollinActions==30 and .studentActions>=1 and .studentActions<=30' "$run/supervision.json" > /dev/null
    /usr/bin/jq -e '.success and .found and .maximumBrickDistanceM==0.35' "$run/result.json" > /dev/null
    for file in case.json environment.bin; do /usr/bin/cmp "$out/catalog/$episode/$file" "$run/scene/$file"; done
done
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
/usr/bin/jq -n --arg sha "$data_sha" --argjson student "$student" '{passed:true,episodes:2,fittingHistories:1,validationHistories:1,studentCommandsReplayed:$student,dataSHA256:$sha,teacherReachedBrickBeforeStudentRollin:true,teacherLabelsTrainingOnly:true,actorTaskEventHint:false,studentAutonomousSuccessClaimed:false,automaticMerge:false}' > "$out/summary.json"
