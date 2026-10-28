#!/usr/bin/env bash
# Dense oracle labels on a fully student-controlled episode, including failures.
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
corpus="$root/gated-search-cohort-admission-v2"
audit="$root/gated-search-cohort-post-audit-v2"
runtime="$root/incomplete-correction-tests-v2/runtime"
generator="$root/correction-v1/generate-diverse"
policy="$root/phase-screen-v1/policy"
out="${PUPPYBOT_STUDENT_ONLY_PILOT_OUT:?New output directory required}"
[[ ! -e "$out" ]]
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
for job in "$corpus/run" "$audit/run";do
    while [[ ! -f "$job.exit" ]];do [[ -f "$job.pid" ]] && kill -0 "$(< "$job.pid")" || { echo "$job ended without a status." >&2;exit 1; }; /usr/bin/sleep 20;done
    [[ "$(< "$job.exit")" == 0 ]] || { echo "$job failed; collection not started." >&2;exit 1; }
done
data="$corpus/expanded/data.bin";data_sha="$(/usr/bin/sha256sum "$data" | /usr/bin/cut -d' ' -f1)";policy_sha="$(/usr/bin/sha256sum "$policy/weights.bin" | /usr/bin/cut -d' ' -f1)"
n="$(/usr/bin/jq -r '.episodes' "$corpus/coverage.json")"
[[ "$n" =~ ^[0-9]+$ && "$n" -ge 284 && "$n" -le 290 ]]
/usr/bin/jq -e --arg sha "$data_sha" '.passed and .dataSHA256==$sha and .newHistoriesIndependentlyAudited and .actorInputsUnchanged' "$corpus/coverage.json" > /dev/null
/usr/bin/jq -e --arg sha "$data_sha" '.passed and .dataSHA256==$sha and .bothReplayReceiptsMatchDataset and .actorInputsUnchanged' "$audit/result.json" > /dev/null
/usr/bin/jq -e --arg sha "$policy_sha" '.weightsSHA256==$sha and .memoryWidth==256 and (.taskFeedback|not)' "$policy/receipt.json" > /dev/null
"$generator" "$out/fit" 54 55 fit > "$out/generate-fit.log"
"$generator" "$out/validation" 154 155 validation > "$out/generate-validation.log"
mkdir "$out/catalog";cp -a "$out/fit/54/4" "$out/catalog/0";cp -a "$out/validation/154/4" "$out/catalog/1"
for ((index=0;index<n;index++));do for file in case.json environment.bin;do /usr/bin/sha256sum "$corpus/expanded/expert-$index/scene/$file" | /usr/bin/tee -a "$out/prior-inputs.sha256" | /usr/bin/cut -d' ' -f1;done;done > "$out/prior-hashes.txt"
for layout in 18 19 20 21 22 23;do
    parent=generalization-benchmark-v1;if (( layout<20 ));then parent=unseen-benchmark-v2;fi
    for scene in {0..15};do for file in case.json environment.bin;do /usr/bin/sha256sum "$base/$parent/scenes/$layout/$scene/$file" | /usr/bin/tee -a "$out/prior-inputs.sha256" | /usr/bin/cut -d' ' -f1;done;done
done >> "$out/prior-hashes.txt"
for episode in 0 1;do
    scene="$out/catalog/$episode";layout=54;fit=true;if (( episode ));then layout=154;fit=false;fi
    /usr/bin/jq -e --argjson layout "$layout" --argjson fit "$fit" '.layoutId==$layout and .fit==$fit and (.rooms|length)==1' "$scene/layout.json" > /dev/null
    for file in case.json environment.bin;do digest="$(/usr/bin/sha256sum "$scene/$file" | /usr/bin/cut -d' ' -f1)";reject_known_hash "$digest" "$out/prior-hashes.txt";printf '%s\n' "$digest" >> "$out/prior-hashes.txt";done
done
/usr/bin/sha256sum "$generator" "$runtime/build/flex/control/control" "$runtime/build/flex/control/simulator" "$runtime/build/flex/sim/puppybot.bin" "$data" "$corpus/coverage.json" "$audit/result.json" "$policy/weights.bin" "$policy/policy" "$policy/receipt.json" "$out"/catalog/{0,1}/{case.json,environment.bin,layout.json} > "$out/inputs.sha256"
find "$runtime/build/flex/control/kernels" -type f -print0 | /usr/bin/sort -z | /usr/bin/xargs -0 /usr/bin/sha256sum >> "$out/inputs.sha256"
export PATH="$base/unseen-benchmark-v2/native-path:$PATH" XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1 PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
cd "$runtime"
./build/flex/control/control correct --policy "$policy" --output "$out/runs" --scene-catalog "$out/catalog" --episodes 2 --validation 1 --rollin 300 --rollin-min 300 --horizon 300 --label-rollin --allow-incomplete --seed 1990000 --large-model > "$out/collect.log" 2>&1
./build/flex/control/control pack-data --data "$out/runs/data.bin" --output "$out/packed" > "$out/pack.log" 2>&1
./build/flex/control/control verify-data --run "$out/runs" --data "$out/packed/data.bin" --output "$out/verified" --allow-incomplete --large-model > "$out/verify.log" 2>&1
sha="$(/usr/bin/sha256sum "$out/packed/data.bin" | /usr/bin/cut -d' ' -f1)";actions="$(/usr/bin/jq -r '.studentRollinActions' "$out/runs/report.json")"
/usr/bin/jq -e --arg sha "$sha" --argjson actions "$actions" '.passed and .episodes==2 and .studentPolicies256==2 and .studentRollinCommandsReplayed==$actions and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .executedCommandsMatchRecordings and .denseOracleLabels and .preActionAlignmentChecked and .zeroPaddingChecked and .taskEventHintAbsent and .dataSHA256==$sha and (.incompleteEpisodesClaimedSuccessful|not)' "$out/verified/result.json" > /dev/null
for episode in 0 1;do
    run="$out/runs/expert-$episode"
    /usr/bin/jq -e --arg sha "$policy_sha" '.studentMemoryWidth==256 and .studentWeightsSHA256==$sha and (.studentBeginsAfterConsumption|not) and .studentStartAction==0 and .denseOracleLabels and .allowIncomplete and .scheduledRollinActions==300 and .studentActions>=1 and .studentActions<=300 and (.terminationReason=="horizon" or .terminationReason=="oracle-unavailable" or .terminationReason=="success")' "$run/supervision.json" > /dev/null
    for file in case.json environment.bin;do /usr/bin/cmp "$out/catalog/$episode/$file" "$run/scene/$file";done
done
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
/usr/bin/sha256sum -c "$out/prior-inputs.sha256" > "$out/prior-integrity-after.log"
/usr/bin/jq -n --arg sha "$sha" --argjson actions "$actions" --slurpfile audit "$out/verified/result.json" '{passed:true,episodes:2,studentRollinActionsReplayed:$actions,incompleteEpisodes:$audit[0].incompleteEpisodes,successfulEpisodes:$audit[0].successfulEpisodes,dataSHA256:$sha,denseOracleLabels:true,teacherLabelsTrainingOnly:true,actorTaskEventHint:false,studentAutonomousSuccessClaimed:false,automaticMerge:false}' > "$out/summary.json"
echo 'Student-only episodes passed replay; incomplete prefixes remain explicitly marked.'
