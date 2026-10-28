#!/usr/bin/env bash
# Exploratory new-camera correction data; never merge it with old-pose images.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
base="$project/build/flex/sim/expanded-rooms-v1"
pilot="$base/camera-forward-pilot-v3"
screen="$pilot/actor-screen-v1"
out="$base/forward-correction-pilot-v1"
policy="$base/return-quick-v1/model"
[[ ! -e "$out/run.exit" && ! -e "$out/runs" ]]
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
while [[ ! -f "$screen/run.exit" ]];do
    [[ -f "$screen/run.pid" ]] && kill -0 "$(< "$screen/run.pid")" || { echo 'Forward-camera screen ended without a terminal status.' >&2;exit 1; }
    /usr/bin/sleep 10
done
[[ "$(< "$screen/run.exit")" == 0 ]] || { echo 'Forward-camera screen did not pass its audits.' >&2;exit 1; }
cd "$project"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
/usr/bin/jq -e '.exploratory and (.trainedForNewCameraPose|not) and .matchedCases and .candidate.episodes==8 and .candidate.auditedEpisodes==8 and .candidate.auditFailures==0' "$screen/comparison.json" > /dev/null
sha="$(/usr/bin/sha256sum "$policy/weights.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$sha" '.weightsSHA256==$sha and (.taskFeedback|not)' "$policy/receipt.json" > /dev/null
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1 PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
cd "$pilot/runtime"
./build/flex/control/control correct --policy "$policy" --output "$out/runs" --scene-catalog "$out/catalog" --episodes 4 --validation 2 --rollin 30 --rollin-min 30 --label-rollin --return-via-home --approach-side 1 --horizon 354 --seed 1910000 > "$out/collection.log" 2>&1
./build/flex/control/control pack-data --data "$out/runs/data.bin" --output "$out/packed" > "$out/packed.log" 2>&1
./build/flex/control/control verify-data --run "$out/runs" --data "$out/packed/data.bin" --output "$out/verified" > "$out/verified.log" 2>&1
data_sha="$(/usr/bin/sha256sum "$out/packed/data.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$data_sha" '.passed and .episodes==4 and .datasetEpisodes==4 and .studentRollinCommandsReplayed>=4 and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .executedCommandsMatchRecordings and .denseOracleLabels and .preActionAlignmentChecked and .zeroPaddingChecked and .taskEventHintAbsent and .dataSHA256==$sha' "$out/verified/result.json" > /dev/null
for i in 0 1 2 3;do
    run="$out/runs/expert-$i";frame="$(/usr/bin/jq -r '.totalSteps' "$run/initial.json")"
    /usr/bin/jq -e --argjson frame "$frame" '.view=="tcp" and .frameId==$frame and .forward[2]< -0.51 and .forward[2]> -0.56' "$run/sensor/frame-$frame.png.camera.json" > /dev/null
    /usr/bin/jq -e --arg sha "$sha" '.studentWeightsSHA256==$sha and .denseOracleLabels and (.studentBeginsAfterConsumption|not) and .studentActions>=1 and .studentActions<=30' "$run/supervision.json" > /dev/null
    for file in case.json environment.bin;do /usr/bin/cmp "$out/catalog/$i/$file" "$run/scene/$file";done
done
cd "$project"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
sim_sha="$(/usr/bin/sha256sum "$pilot/runtime/build/flex/control/simulator" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -n --arg data "$data_sha" --arg policy "$sha" --arg simulator "$sim_sha" --slurpfile audit "$out/verified/result.json" '{passed:true,exploratory:true,cameraProfile:"compact-balanced-400mm-85deg-radial20mm",cameraPoseBoundToSimulatorSHA256:$simulator,oldPosePolicySHA256:$policy,episodes:4,fittingHistories:2,validationHistories:2,studentCommandsReplayed:$audit[0].studentRollinCommandsReplayed,studentReplayMaxAbsError:$audit[0].studentRollinMaxAbsError,dataSHA256:$data,teacherPrivileged:true,actorTaskEventHint:false,oldPoseDatasetNotMerged:true,wholeEpisodePerformanceNotEstablished:true}' > "$out/result.json"
echo 'New-camera student roll-ins and teacher corrections audited; no training or promotion implied.'
