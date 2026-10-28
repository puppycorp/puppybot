#!/usr/bin/env bash
# Preserve a pre-horizon-field recording and record its original dataset horizon.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
base="$project/build/flex/sim/expanded-rooms-v1"
root="$base/large-model-v1"
pilot="$root/student-only-search-pilot-v1"
runtime="$root/incomplete-correction-tests-v4/runtime"
out="${PUPPYBOT_STUDENT_HORIZON_OUT:?New output directory required}"
[[ ! -e "$out" ]]
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
while [[ ! -f "$pilot/run.exit" ]];do [[ -f "$pilot/run.pid" ]] && kill -0 "$(< "$pilot/run.pid")" || { echo 'Student-only pilot ended without a status.' >&2;exit 1; }; /usr/bin/sleep 20;done
[[ "$(< "$pilot/run.exit")" == 0 ]]
data="$pilot/packed/data.bin";raw="$pilot/runs/data.bin";sha="$(/usr/bin/sha256sum "$data" | /usr/bin/cut -d' ' -f1)";raw_sha="$(/usr/bin/sha256sum "$raw" | /usr/bin/cut -d' ' -f1)"
read -r n fit horizon < <(/usr/bin/od -An -v -tu8 -j8 -N24 "$raw" | /usr/bin/tr '\n' ' '; echo)
read -r packed_n packed_fit packed_length < <(/usr/bin/od -An -v -tu8 -j8 -N24 "$data" | /usr/bin/tr '\n' ' '; echo)
[[ "$(/usr/bin/head -c 8 "$raw")" == PVDATA03 && "$(/usr/bin/head -c 8 "$data")" == PVDATA03 && "$n" == 2 && "$fit" == 1 && "$horizon" == 300 && "$packed_n" == "$n" && "$packed_fit" == "$fit" && "$packed_length" -ge 1 && "$packed_length" -le "$horizon" && "$(/usr/bin/stat -c %s "$raw")" -eq $((32+n*horizon*21224)) && "$(/usr/bin/stat -c %s "$data")" -eq $((32+n*packed_length*21224)) ]]
/usr/bin/jq -e --arg raw "$raw_sha" --arg sha "$sha" --argjson horizon "$horizon" --argjson length "$packed_length" '.episodes==2 and .sourceSHA256==$raw and .dataSHA256==$sha and .originalSequenceLength==$horizon and .sequenceLength==$length and .completeHistoriesPreserved and .onlyTrailingPaddingRemoved' "$pilot/packed/report.json" > /dev/null
/usr/bin/jq -e --arg sha "$sha" '.passed and .episodes==2 and .dataSHA256==$sha and .denseOracleLabels and .teacherLabelsTrainingOnly and (.studentAutonomousSuccessClaimed|not)' "$pilot/summary.json" > /dev/null
/usr/bin/jq -e --arg sha "$sha" '.passed and .episodes==2 and .dataSHA256==$sha and .studentRollinMaxAbsError==0 and .denseOracleLabels and .taskEventHintAbsent and (.incompleteEpisodesClaimedSuccessful|not)' "$pilot/verified/result.json" > /dev/null
for episode in 0 1;do
    /usr/bin/jq -e --argjson horizon "$horizon" '.allowIncomplete and .studentStartAction==0 and .scheduledRollinActions==$horizon and .maximumRollinActions==$horizon and .studentActions>=1 and .studentActions<=$horizon and (has("recordedHorizon")|not)' "$pilot/runs/expert-$episode/supervision.json" > /dev/null
done
/usr/bin/sha256sum "$data" "$raw" "$pilot/packed/report.json" "$pilot/summary.json" "$pilot/verified/result.json" "$pilot/runs/expert-0/supervision.json" "$pilot/runs/expert-1/supervision.json" "$runtime/build/flex/control/control" > "$out/inputs.sha256"
cp -a --reflink=auto "$pilot/runs" "$out/runs"
for episode in 0 1;do
    file="$out/runs/expert-$episode/supervision.json"
    /usr/bin/jq --argjson horizon "$horizon" '.+{recordedHorizon:$horizon}' "$file" > "$out/meta-$episode.json"
    /usr/bin/mv "$out/meta-$episode.json" "$file"
done
export PATH="$base/unseen-benchmark-v2/native-path:$PATH" XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1 PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
cd "$runtime"
./build/flex/control/control verify-data --run "$out/runs" --data "$data" --output "$out/verified" --allow-incomplete --large-model > "$out/verify.log" 2>&1
/usr/bin/jq -e --arg sha "$sha" '.passed and .episodes==2 and .dataSHA256==$sha and .studentRollinMaxAbsError==0 and .denseOracleLabels and .zeroPaddingChecked and .taskEventHintAbsent and (.incompleteEpisodesClaimedSuccessful|not)' "$out/verified/result.json" > /dev/null
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
/usr/bin/jq -n --arg sha "$sha" --argjson horizon "$horizon" '{passed:true,dataSHA256:$sha,episodes:2,recordedHorizon:$horizon,horizonDerivedFromOriginalDataHeader:true,originalMetadataUnchanged:true,replayVerified:true,actorInputsUnchanged:true,incompleteEpisodesClaimedSuccessful:false}' > "$out/result.json"
echo 'Original episode horizon recorded in an independently replayed metadata copy.'
